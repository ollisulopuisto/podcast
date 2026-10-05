"""Musiikkipohjan äänenvoimakkuuskäyrä puheen mukaan.

Käyttäjä asettaa pohjan raidalle; tämä päättää miten se nousee, pysyy ja
laskee. Säännöt ja muodot on mitattu vst s13e03:n kolmesta korvalla
häivytetystä pohjasta (häivytetyn ja häivyttämättömän tiedoston suhde,
0,1 s ikkunat, local-hburg 2026-10-05). **Yksi jakso**: luvut ovat
lähtöarvoja, ja seuraava jakso joko vahvistaa ne tai muuttaa ne.

Mitattu kuvio:

* Tasanne saavutetaan pian viimeisen sanan jälkeen (0,9 / 1,3 / 2,2 s).
* Nousu on aina sama käyrä: hiljaisuudesta tasanteelle 8,5 sekunnissa,
  suunnilleen 8 dB/s. MID ja END ovat sama käyrä 9 s siirrettynä.
* Tasanne kestää vähintään noin 4,5 s (MID 4,4, END 4,6).
* Lasku päättyy pohjan loppuun, ei puheeseen: MID 0,5 s ja END 1,0 s ennen
  alueen loppua. Lasku on 3,1 s, ja MID:ssä se puristui 1,5 sekuntiin
  koska tasanne vei tilan.
* Kylmän alun alla (intro) pohja soi 12 dB tasanteen alla. Kun juontaja
  aloittaa, pohja painuu 0,4 s ennen ensimmäistä sanaa 9,3 dB tasanteen
  alle, pysyy siellä 2,8 s ja laskee pois.

Käyrä on desibeleinä **tasanteeseen nähden**. Tasanteen oma taso on
kutsujan: se riippuu pohjatiedoston voimakkuudesta.
"""

from __future__ import annotations

from itertools import pairwise

from .fades import SILENCE_DB

#: Tasanne saavutetaan näin kauan viimeisen sanan jälkeen. Mediaani
#: mitatuista 0,89 (INTRO), 1,34 (MID) ja 2,18 s (END).
PLATEAU_AFTER_S = 1.34
#: Lyhyempi puhetauko ei ole pohjan paikka vaan lauseiden väli.
MIN_GAP_S = 4.0
#: Tasanne kestää vähintään tämän. MID 4,4 s, END 4,6 s.
PLATEAU_MIN_S = 4.5
#: Lasku päättyy näin kauan ennen alueen loppua. MID 0,5, END 1,05.
END_MARGIN_S = 0.75
#: ... ja näin kauan ennen seuraavaa sanaa, jos se tulee ennen alueen
#: loppua. MID: pohja hiljaa noin 1,0 s ennen seuraavaa sanaa.
ONSET_MARGIN_S = 1.0
#: Laskua ei puristeta tätä lyhyemmäksi.
MIN_FALL_S = 1.0
#: Kylmän alun alla soiva taso. INTRO t 0,6–13 s mediaani noin −22 dB,
#: tasanne −10,0.
COLD_OPEN_UNDER_DB = -12.0
#: Juontajan alle painuminen alkaa näin kauan ennen ensimmäistä sanaa.
DROP_LEAD_S = 0.4
#: Hylly juontajan alla: INTRO t 25,7–28,0 mediaani noin −19,3, tasanne
#: −10,0.
TAIL_UNDER_DB = -9.3
#: Hyllyn kesto ennen laskua. INTRO t 25,7–28,5.
TAIL_S = 2.8

#: Nousu, (s, dB tasanteeseen nähden). END-pohja t 0–8,5 s, tasanne −8,17;
#: kohinaisilla kohdilla (END t 6,2–7,1) MID-pohjan samat pisteet 9 s
#: myöhemmin. Ei raised-cosine eikä suora: alussa jyrkempi.
RISE = (
    (0.0, -67.6), (0.5, -52.9), (1.0, -48.0), (1.5, -43.6), (2.0, -39.1),
    (2.5, -35.2), (3.0, -31.4), (3.5, -28.0), (4.0, -24.6), (4.5, -21.6),
    (5.0, -18.9), (5.5, -16.8), (6.0, -14.8), (6.5, -12.6), (7.0, -10.7),
    (7.5, -6.8), (8.0, -2.9), (8.5, 0.0),
)
#: Lasku tasanteelta. END-pohja t 13,1–16,2 s. Kiihtyy loppua kohti.
FALL = (
    (0.0, 0.0), (0.4, -3.6), (0.9, -6.7), (1.4, -9.8), (1.9, -14.7),
    (2.4, -22.4), (2.9, -32.3), (3.1, -37.1),
)
#: Painuminen juontajan alle. INTRO-pohja t 23,9–25,7 s tasoitettuna;
#: alkuperäinen on transienttien kohdalla ±1,5 dB kohinainen.
DROP = ((0.0, 0.0), (0.3, -3.5), (0.8, -6.5), (1.2, -8.0), (1.8, TAIL_UNDER_DB))

#: Käyrän pistetiheys. ``fades.segments`` taittaa luiskat vain näihin.
STEP_S = 0.05


def _interp(shape, t: float, scale: float = 1.0) -> float:
    """Muodon arvo hetkellä ``t``; ``scale`` venyttää aikaa."""
    pts = [(a * scale, b) for a, b in shape]
    if t <= pts[0][0]:
        return pts[0][1]
    for (t0, d0), (t1, d1) in pairwise(pts):
        if t <= t1:
            return d0 + (d1 - d0) * (t - t0) / (t1 - t0)
    return pts[-1][1]


def _gap(start: float, end: float, speech):
    """Ensimmäinen vähintään ``MIN_GAP_S`` pitkä puhetauko pohjan alueella.

    Palauttaa ``(viimeinen sana ennen taukoa, seuraava sana tai None)``.
    """
    spans = sorted(speech)
    previous_end = None
    for a, b in spans:
        if b <= start:
            previous_end = b
            continue
        silence_from = previous_end if previous_end is not None else start
        if a - max(silence_from, start) >= MIN_GAP_S and a > start:
            return silence_from, a
        previous_end = b
        if previous_end >= end:
            return None
    if previous_end is None:
        return start - PLATEAU_AFTER_S, None
    if end - max(previous_end, start) >= MIN_GAP_S:
        return previous_end, None
    return None


def curve(start: float, end: float, speech, cold_open: bool = False):
    """Pohjan käyrä ``[(s alueen alusta, dB tasanteeseen nähden), ...]``.

    ``speech`` on aikajanan puhevälit (``activity.speech_intervals``).
    ``cold_open``: pohja soi puheen alla ennen nousuaan (intro). Muuten se
    nousee hiljaisuudesta.

    ``None``, jos pohjan alueella ei ole yhtään ``MIN_GAP_S``:n taukoa: sille
    ei ole mitattua sääntöä, eikä arvaus ole parempi kuin ei mitään.
    """
    gap = _gap(start, end, speech)
    if gap is None:
        return None
    last_word, next_word = gap
    plateau = last_word + PLATEAU_AFTER_S
    rise_from = plateau - RISE[-1][0]

    limit = end - END_MARGIN_S
    tail = (
        next_word is not None
        and limit - next_word >= DROP[-1][0] + TAIL_S + FALL[-1][0]
    )
    if tail:
        drop_from = next_word - DROP_LEAD_S
        fall_from = drop_from + DROP[-1][0] + TAIL_S
        fall_scale = 1.0
        floor = TAIL_UNDER_DB
    else:
        drop_from = None
        fall_end = limit if next_word is None else min(limit, next_word - ONSET_MARGIN_S)
        fall_from = max(fall_end - FALL[-1][0], plateau + PLATEAU_MIN_S)
        fall_from = min(fall_from, fall_end - MIN_FALL_S)
        fall_scale = (fall_end - fall_from) / FALL[-1][0]
        floor = 0.0

    def level(t: float) -> float:
        if t < plateau:
            rise = _interp(RISE, t - rise_from) if t >= rise_from else SILENCE_DB
            return max(rise, COLD_OPEN_UNDER_DB) if cold_open else rise
        if drop_from is not None and t >= drop_from and t < fall_from:
            return _interp(DROP, t - drop_from)
        if t >= fall_from:
            fallen = floor + _interp(FALL, t - fall_from, fall_scale)
            past = t - fall_from > FALL[-1][0] * fall_scale
            return SILENCE_DB if past else fallen
        return 0.0

    count = int((end - start) / STEP_S) + 1
    return [(i * STEP_S, round(level(start + i * STEP_S), 2)) for i in range(count)]
