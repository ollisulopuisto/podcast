"""Mielivaltainen äänenvoimakkuuskäyrä Hindenburgin `<Fade>`-luiskiksi.

Hindenburgin luiska kulkee edellisestä tasosta arvoon ``Gain``
raised-cosine-muodossa ja jää sinne (``nhsx.mix.Ramp``, mitattu). Käyttäjän
omat häivytykset ovat toista muotoa: vst s13e03:n musiikkipohjissa nousu
−68 dB:stä −8 dB:iin kesti noin 8,6 s, alussa noin −8 dB / 0,5 s ja sitten
loivenevasti. Yksi luiska ei osaa sitä. Lyhyinä paloina se osaa: palojen
välissä käyrä kulkee pisteestä pisteeseen, ja palojen raised-cosine-mutka
jää toleranssin alle.

``segments``in pilkkominen on ahne: jokainen luiska venytetään niin pitkäksi kuin se
pysyy toleranssissa. Tasanne ei tarvitse luiskaa lainkaan, koska taso jää
edellisen luiskan päätearvoon.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .mix import FADE_ELEMENT, _share
from .read import localname, seconds_to_time

#: Kuinka paljon kirjoitettu käyrä saa poiketa tavoitteesta, dB, siellä
#: missä musiikki kuuluu. Puoli desibeliä on alle sen mitä tasoeron korva
#: erottaa musiikista puheen alla.
TOLERANCE_DB = 0.5
#: Sovitus tehdään tätä tiukemmin. Käyrä tarkistetaan vain annetuissa
#: pisteissä ja ajat pyöristetään millisekunteihin, joten pisteiden väliin
#: jää virhettä jota sovitus ei näe: 0,05 s pisteillä ja 0,5 dB:n
#: sovituksella mitattu pahin oli 0,501 dB 10 ms välein luettuna.
FIT_DB = 0.4
#: Tämän alla musiikki ei kuulu puheen alta, ja riittää että käyrä pysyy
#: täällä alhaalla. Ilman rajaa −68 dB:n hännän seuraaminen puolen desibelin
#: tarkkuudella vaatisi kymmeniä luiskia joita kukaan ei kuule.
AUDIBLE_DB = -40.0
#: Kuulumattoman alla käyrä saa poiketa näin paljon. Ilman rajaa kaikki
#: −40 dB:n alla kelpasi, ja vst s13e03:n INTRO-pohjan lasku −42,6 dB:stä
#: hiljaisuuteen kirjoitettiin yhdeksi 71,75 s luiskaksi: musiikki soi
#: −43…−52 dB:ssä koko keskustelun alla. Kahdentoista desibelin rajalla
#: hiljaisuus (−90) tulee sekunnin murto-osassa.
QUIET_TOLERANCE_DB = 12.0
#: Hiljaisuus kirjoitetaan lukuna. ``-inf`` ei ole attribuuttiarvo jonka
#: Hindenburgin tiedetään hyväksyvän.
SILENCE_DB = -90.0
#: Alueen taso on 0 dB ensimmäiseen luiskaan asti. Jos käyrä alkaa muualta,
#: ensimmäinen luiska vie sinne näin nopeasti. **Varmistettava
#: Hindenburgissa**: soiko tämä 10 ms naksahduksena alueen alussa.
FIRST_RAMP_S = 0.010
#: ... ja siksi alue alkaa häivytyksellä hiljaisuudesta (``FadeIn``), joka
#: peittää sen 10 ms:n luiskan. Ilman sitä vst s13e03:n END-pohja alkoi
#: 10 ms purskeella −11 dBFS:ssä, ja käyttäjä kuuli sen. Luiskan huippu
#: −56,66 dB:iin kulkevalla luiskalla: ilman häivytystä 0 dB, 100 ms:llä
#: −50, 200 ms:llä −62 dB. Sen jälkeen käyrä on jo kuulumaton, joten
#: häivytys ei muuta mitään kuuluvaa.
START_FADE_IN_S = 0.200


@dataclass(frozen=True)
class Segment:
    """Yksi kirjoitettava `<Fade>`: ``start`` alueen alusta, sekunteja."""

    start: float
    length: float
    gain_db: float


def _clean(db: float) -> float:
    if not math.isfinite(db) or db < SILENCE_DB:
        return SILENCE_DB
    return round(db, 2)


def _lin(db: float) -> float:
    return 10.0 ** (db / 20.0)


def _fits(points, i: int, j: int) -> bool:
    """Kulkeeko luiska pisteestä ``i`` pisteeseen ``j`` välipisteiden kautta."""
    t0, d0 = points[i]
    t1, d1 = points[j]
    g0, g1 = _lin(d0), _lin(d1)
    for k in range(i + 1, j):
        t, want = points[k]
        got = 20.0 * math.log10(max(g0 + (g1 - g0) * _share((t - t0) / (t1 - t0)), 1e-12))
        audible = want >= AUDIBLE_DB or got >= AUDIBLE_DB
        allowed = FIT_DB if audible else QUIET_TOLERANCE_DB
        if abs(got - want) > allowed:
            return False
    return True


def segments(points: list[tuple[float, float]]) -> list[Segment]:
    """Käyrä ``[(aika alueen alusta, dB), ...]`` luiskiksi.

    Pisteiden on oltava aikajärjestyksessä ja alettava hetkestä 0. Tiheys
    on kutsujan: luiskat taittuvat vain annettuihin pisteisiin.
    """
    pts = [(float(t), _clean(db)) for t, db in points]
    if not pts:
        return []
    out = [Segment(0.0, FIRST_RAMP_S, pts[0][1])]
    i = 0
    while i < len(pts) - 1:
        j = i + 1
        while j + 1 < len(pts) and _fits(pts, i, j + 1):
            j += 1
        if pts[j][1] != pts[i][1] or not _flat(pts, i, j):
            start = max(pts[i][0], FIRST_RAMP_S)
            out.append(Segment(start, pts[j][0] - start, pts[j][1]))
        i = j
    return _merge_holds(out)


#: Sovituksen hakuväli, s. Luiskan alku ja pituus haetaan tällä tarkkuudella.
FIT_GRID_S = 0.05


def long_segments(points: list[tuple[float, float]]) -> list[Segment]:
    """Käyrä luiskiksi: jokainen yhtäjaksoinen muutos on yksi luiska, yli
    ``RISE_TWO_RAMPS_DB``:n nousu kaksi.

    ``segments`` pilkkoo nousun lyhyiksi paloiksi, ja raised-cosine-luiskan
    nollanopeus joka liitoksessa kuuluu sätkimisenä (vst s13e03 INTRO: 21
    luiskaa, nousu 11,7 dB / 1,9 s, 17 % ajasta lähes nollanopeudella).
    Täällä jokainen tasanteiden välinen vaihe saa yhden luiskan, jonka alku
    ja pituus haetaan niin että pahin poikkeama kuuluvalla alueella on
    pienin. Hindenburgin luiska on lineaarista amplitudia, käyttäjän nousu
    suoraa desibeleinä, joten poikkeama jää: mitattu 13,7 dB pahimmillaan
    8,5 s nousussa hiljaisuudesta (alku 1,5 s, pituus 7,0 s). Siksi nousu
    saa kaksi luiskaa (``_fit_two``): liitoksen taso on käyrän arvo
    liitoskohdassa, ja pysähdys liitoksessa on sekunnin luokan luiskilla
    kaukana sätkimisnopeudesta.
    """
    import numpy as np

    pts = [(float(t), _clean(db)) for t, db in points]
    if not pts:
        return []
    out = [Segment(0.0, FIRST_RAMP_S, pts[0][1])]
    times = np.array([t for t, _ in pts])
    wants = np.array([d for _, d in pts])
    i = 0
    while i < len(pts) - 1:
        if pts[i + 1][1] == pts[i][1]:
            i += 1
            continue
        j = i + 1
        while j + 1 < len(pts) and pts[j + 1][1] != pts[j][1]:
            j += 1
        rising = wants[j] - wants[i] >= RISE_TWO_RAMPS_DB
        out.extend(_fit_two(times, wants, i, j) if rising else [_fit_run(times, wants, i, j)])
        i = j
    return _merge_holds(out)


#: Tätä suurempi nousu saa kaksi luiskaa. Käyttäjän nousu on suora
#: desibeleinä, ja yksi amplitudiluiska poikkeaa siitä 13,7 dB (vst s13e03,
#: −68 → −8 dB, 8,5 s). Kaksi luiskaa liittyy vain kerran, joten
#: sätkimistä ei synny.
RISE_TWO_RAMPS_DB = 30.0
#: Kahden luiskan haku on kolmen muuttujan haku, joten ruudukko on karkeampi.
FIT_TWO_GRID_S = 0.1


def _fit_two(times, wants, i: int, j: int) -> list[Segment]:
    """Kaksi peräkkäistä luiskaa nousulle: alku, liitos ja loppu haetaan.

    Liitoksen taso on käyrän arvo liitoskohdassa, joten haettavia on vain
    kolme aikaa. Kriteeri on sama kuin ``_fit_run``: pahin poikkeama
    kuuluvalla alueella pienin.
    """
    import numpy as np

    g0, g1 = _lin(float(wants[i])), _lin(float(wants[j]))
    t0, t1 = float(times[i]), float(times[j])
    window = times[i : j + 1]
    want = wants[i : j + 1]
    steps = max(3, round((t1 - t0) / FIT_TWO_GRID_S))
    first = max(t0, FIRST_RAMP_S)
    grid = [t0 + k * FIT_TWO_GRID_S for k in range(steps + 1)]
    level = [_lin(float(np.interp(t, times[i : j + 1], want))) for t in grid]
    audible_want = want >= AUDIBLE_DB
    best = (math.inf, None)
    for a in range(steps - 1):
        start = max(grid[a], first)
        for m in range(a + 1, steps):
            if grid[m] - start < FIT_TWO_GRID_S:
                continue
            x = np.clip((window - start) / (grid[m] - start), 0.0, 1.0)
            gm = level[m]
            first_part = g0 + (gm - g0) * (1.0 - np.cos(np.pi * x)) / 2.0
            for e in range(m + 1, steps + 1):
                y = np.clip((window - grid[m]) / (grid[e] - grid[m]), 0.0, 1.0)
                second = gm + (g1 - gm) * (1.0 - np.cos(np.pi * y)) / 2.0
                gain = np.where(window < grid[m], first_part, second)
                got = 20.0 * np.log10(np.maximum(gain, 1e-12))
                audible = audible_want | (got >= AUDIBLE_DB)
                err = float(np.max(np.where(audible, np.abs(got - want), 0.0)))
                if err < best[0]:
                    best = (err, (start, a, m, e))
    start, a, m, e = best[1]
    junction_db = _clean(20.0 * math.log10(max(level[m], 1e-12)))
    return [
        Segment(start, grid[m] - start, junction_db),
        Segment(grid[m], grid[e] - grid[m], float(wants[j])),
    ]


def _fit_run(times, wants, i: int, j: int) -> Segment:
    """Yksi luiska pisteestä ``i`` pisteeseen ``j``: paras alku ja pituus."""
    import numpy as np

    g0, g1 = _lin(float(wants[i])), _lin(float(wants[j]))
    t0, t1 = float(times[i]), float(times[j])
    window = times[i : j + 1]
    want = wants[i : j + 1]
    steps = max(1, round((t1 - t0) / FIT_GRID_S))
    best = (math.inf, max(t0, FIRST_RAMP_S), t1 - max(t0, FIRST_RAMP_S))
    for a in range(steps):
        start = max(t0 + a * FIT_GRID_S, FIRST_RAMP_S)
        for b in range(a + 1, steps + 1):
            end = t0 + b * FIT_GRID_S
            if end - start < FIT_GRID_S:
                continue
            x = np.clip((window - start) / (end - start), 0.0, 1.0)
            gain = g0 + (g1 - g0) * (1.0 - np.cos(np.pi * x)) / 2.0
            got = 20.0 * np.log10(np.maximum(gain, 1e-12))
            audible = (want >= AUDIBLE_DB) | (got >= AUDIBLE_DB)
            err = float(np.max(np.where(audible, np.abs(got - want), 0.0)))
            if err < best[0]:
                best = (err, start, end - start)
    return Segment(best[1], best[2], float(wants[j]))


def _flat(points, i: int, j: int) -> bool:
    return all(points[k][1] == points[i][1] for k in range(i, j + 1))


def _merge_holds(out: list[Segment]) -> list[Segment]:
    """Peräkkäiset luiskat samaan tasoon ovat yksi luiska ja tasanne."""
    merged = [out[0]]
    for seg in out[1:]:
        if seg.gain_db == merged[-1].gain_db:
            continue
        merged.append(seg)
    return merged


def write(region_elem, segs: list[Segment]) -> None:
    """Korvaa alueen `<Fade>`-lapset luiskilla ``segs``.

    Vanhat poistetaan: kaksi käyrää samassa alueessa seuraisivat toisiaan
    eivätkä summautuisi (``docs/hindenburg-nhsx-format.md`` §7), eli
    tulos olisi kumpikaan.
    """
    for child in list(region_elem):
        if localname(child) == FADE_ELEMENT:
            region_elem.remove(child)
    tail = region_elem.text
    if segs and segs[0].gain_db < 0.0:
        region_elem.set("FadeIn", seconds_to_time(START_FADE_IN_S))
    for seg in segs:
        child = region_elem.makeelement(FADE_ELEMENT, {})
        if seg.start > 0:
            child.set("Start", seconds_to_time(seg.start))
        child.set("Length", seconds_to_time(seg.length))
        child.set("Gain", f"{seg.gain_db:g}")
        region_elem.append(child)
    region_elem.text = tail
