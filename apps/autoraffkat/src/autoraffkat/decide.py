"""Päätöskerros: nopea kerros.

Saa valmiit verhokäyrät ruudukolle kohdistettuina ja päättää kynnyksistä,
vähimmäiskestoista ja päällekkäispuheen säännöstä leikkauslistan. Ajetaan
uudestaan joka kerta kun liukusäädintä liikautetaan, joten tässä ei saa olla
tiedostojen lukua eikä silmukoita yksittäisten näytteiden yli — vain numpyta ja
silmukka jaksojen (ei näytteiden) yli.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# Maskiapurit ovat kirjastossa: sama logiikka ohjaa kuvan leikkausta ja
# äänen vaimennusta, eikä siitä saa olla kahta kopiota.
from speechmix.masks import (  # noqa: F401
    drop_short,
    open_windows,
    trim_end,
)
from speechmix.masks import (
    hops as _hops,
)
from speechmix.masks import (
    open_runs as _open_runs,
)
from speechmix.masks import (
    runs as _runs,
)

from .model import (
    HOP,
    LONGTAKE_REACTION,
    LONGTAKE_REACTION_WIDE,
    LONGTAKE_STAY,
    OVERLAP_HOLD,
    OVERLAP_WIDE,
    Globals,
    Segment,
)

# Kuinka kaukaa katkaisukohtaa saa siirtää mitattuun reaktiohetkeen.
# Neljä sekuntia: tarpeeksi löytääkseen hetken, liian vähän siirtääkseen
# katkaisua paikkaan jossa puheenvuoro tuntuu jo eri kohdalta.
REACTION_REACH = 4.0

WIDE = -2  # want-taulukon erikoisarvot
HOLD = -1

WIDE_LABEL = "Laaja"


# ------------------------------------------------------------------ apurit



def _close_gaps(mask: np.ndarray, k: int) -> np.ndarray:
    """Täyttää k:ta lyhyemmät epätodet jaksot. Estää sanavälien pilkkomisen."""
    if k <= 1 or mask.size == 0:
        return mask
    out = mask.copy()
    for start, end, value in _runs(mask.astype(np.int8)):
        if not value and start > 0 and end < mask.size and (end - start) < k:
            out[start:end] = True
    return out






# ------------------------------------------------------------------ syöte


@dataclass
class SpeakerLanes:
    """Yhden puhujan aineisto ruudukolla."""

    name: str
    level: np.ndarray  # dB, vahvistuskorjaus jo mukana
    on: np.ndarray  # bool, kynnyksen ylitys
    close_key: str | None  # lähikuvan media key, None jos ei lähikuvaa
    available: np.ndarray | None = None  # missä lähikuva on olemassa


@dataclass
class Grid:
    """Päätöskerroksen syöte: kaikki ruudukolle kohdistettuna."""

    n: int  # ruudukon pituus (HOP-askelta)
    program_start: float  # aikajanan sekunneissa
    speakers: list[SpeakerLanes] = field(default_factory=list)
    wide_key: str = ""

    @property
    def duration(self) -> float:
        return self.n * HOP


@dataclass
class Decision:
    """Päätöksen tulos: leikkauslista ja esikatselun tarvitsemat taulukot."""

    segments: list[Segment]
    active: np.ndarray  # (puhujia, n) bool — esikatselupalkkia varten
    chosen: np.ndarray  # (n,) int — puhujan indeksi tai WIDE


# ------------------------------------------------------------------ päätös


def _want_array(grid: Grid, g: Globals) -> tuple[np.ndarray, np.ndarray]:
    """Kunkin hetken toivottu kuva ilman kestorajoituksia."""
    n = grid.n
    count_speakers = len(grid.speakers)
    active = np.zeros((count_speakers, n), dtype=bool)
    levels = np.full((count_speakers, n), -200.0, dtype=np.float32)
    for i, sp in enumerate(grid.speakers):
        active[i] = sp.on
        levels[i] = sp.level

    want = np.full(n, HOLD, dtype=np.int32)
    if count_speakers == 0:
        return want, active

    count = active.sum(axis=0)
    # Vertailu vain äänessä olevien kesken. Hiljaisen mikin taso voi olla
    # korkein — kuuma mikki, iso vahvistus, eläväinen huone — eikä kuva
    # kuulu silti hänelle.
    masked = np.where(active, levels, -300.0)
    loudest = np.argmax(masked, axis=0)

    # Yksi äänessä: hänen lähikuvansa.
    single = count == 1
    want[single] = np.argmax(active, axis=0)[single]

    if count_speakers >= 2:
        many = count >= 2
        # Ohikiitävä myötäily ei ole päällekkäispuhetta.
        overlap = _open_runs(many, _hops(g.min_overlap))
        brief = many & ~overlap
        want[brief] = loudest[brief]

        if g.overlap_rule == OVERLAP_WIDE:
            want[overlap] = WIDE if grid.wide_key else HOLD
        elif g.overlap_rule == OVERLAP_HOLD:
            want[overlap] = HOLD
        else:  # OVERLAP_LOUDER
            ordered = np.sort(masked, axis=0)
            margin = ordered[-1] - ordered[-2]
            strong = overlap & (margin >= g.dominance_db)
            want[strong] = loudest[strong]
            want[overlap & ~strong] = HOLD

    # Puhuja ilman lähikuvaa näytetään laajana (tai pidetään edellinen jos ei laajaa).
    for i, sp in enumerate(grid.speakers):
        if sp.close_key is None:
            want[want == i] = WIDE if grid.wide_key else HOLD
        elif sp.available is not None:
            want[(want == i) & ~sp.available] = HOLD

    return want, active


def _compute_tempo(active: np.ndarray, n: int) -> np.ndarray:
    """Keskustelun paikallinen tempo (1/f-vaihtelu liukuvalla ikkunalla).

    Reunoilla ikkuna liukuu sisäänpäin eikä kutistu: se on aina yhtä monta
    askelta, jolloin ohjelman alku ja loppu vertautuvat samaan mittaan kuin
    keskikohta. Nollilla täytetty konvoluutio näytti alun ja lopun aina
    hitaimpana mahdollisena aineistona — tempo osui alarajaan riippumatta
    siitä mitä siinä puhuttiin, ja vähimmäiskesto venyi viidenneksen
    ensimmäisten ja viimeisten 22 sekunnin ajaksi. Ohjelmaa lyhyempi ikkuna
    kattaa koko ohjelman.

    Summataulukko eikä konvoluutio: ikkuna on 2250 askelta, ja suora
    konvoluutio maksoi kahden tunnin ohjelmasta 75 ms — suurimman osan koko
    päätöskerroksesta, joka on se kerros jonka on pysyttävä millisekunneissa.
    """
    if active.size == 0 or n == 0:
        return np.ones(n, dtype=np.float32)
    changes = np.sum(
        np.abs(np.diff(active.astype(np.int8), axis=1, prepend=0)), axis=0
    ).astype(np.float64)
    window = min(_hops(45.0), n)  # 45 sekunnin liukuva ikkuna
    total = np.concatenate(([0.0], np.cumsum(changes)))
    index = np.arange(n)
    lo = np.clip(index - window // 2, 0, n)
    hi = np.clip(lo + window, 0, n)
    lo = np.maximum(hi - window, 0)
    rate = (total[hi] - total[lo]) / np.maximum(hi - lo, 1)
    mean_rate = float(np.mean(rate))
    if mean_rate <= 0.0:
        # Kukaan ei puhu: tempo on yksi, ei nollalla jakoa. Epsilon summan
        # päällä olisi harhainen — harvassa vuorottelussa keskinopeus on
        # tuhannesosia, ja tuhannesosaan lisätty epsilon siirtää temposta
        # prosentteja.
        return np.ones(n, dtype=np.float32)
    return np.clip(rate / mean_rate, 0.7, 1.4).astype(np.float32)


def _last_speech(active: np.ndarray) -> np.ndarray:
    """Kullekin hetkelle viimeisin indeksi, jolloin puhuja oli äänessä (-1 = ei koskaan).

    Kumulatiivinen maksimi kerran, jotta hännän lattian saa jokaisessa
    leikkauskohdassa vakioajassa. Silmukka jaksojen yli olisi tässä turha:
    tämä on kaksi numpy-ajoa koko taulukon yli.
    """
    if active.size == 0:
        return active.astype(np.int32)
    index = np.arange(active.shape[1], dtype=np.int32)
    return np.maximum.accumulate(np.where(active, index, -1), axis=1)


def _cut_points(
    want: np.ndarray,
    g: Globals,
    tempo: np.ndarray | None = None,
    active: np.ndarray | None = None,
    initial_target: int = WIDE,
) -> list[tuple[float, int]]:
    """Kestorajoitukset: vahvistusaika, ennakko (J-cut), häntä (L-cut), tempo.

    Ennakko ja häntä ovat saman leikkauskohdan kaksi reunaa. Ennakko vetää
    leikkausta aikaisemmaksi, seuraavan puhujan ääntä edelle; häntä on lattia,
    joka pitää edellisen puhujan kuvassa vielä hänen puheensa jälkeen. Kumpi
    voittaa, ratkeaa tauon pituudesta: pitkän tauon jälkeen leikataan
    ennakolla, nopeassa vuoronvaihdossa jäädään edelliseen kasvoihin sen
    aikaa mitä häntä sanoo — se on L-cut.

    Häntä koskee vain puhujan kuvasta lähtemistä. Laajassa ei ole kasvoja
    joihin viivähtää, joten sieltä leikataan aina ennakolla.

    Häntää pidempi vastaus ehtii kuvaan, lyhyempi ei: jos lattia siirtää
    leikkauksen jakson yli, kuva jää edelliseen puhujaan.
    """
    confirm = _hops(g.confirm)
    current = initial_target
    cuts: list[tuple[float, int]] = [(0.0, initial_target)]
    last_cut = -g.min_shot
    hang = g.hang if (g.hang > 0 and active is not None and active.size) else 0.0
    last_speech = _last_speech(active) if hang else None

    for start, end, target in _runs(want):
        if target in (HOLD, current):
            continue
        if (end - start) < confirm:
            continue

        # 1/f tempo skaalaa paikallista vähimmäiskestoa luonnollisen vaihtelun saavuttamiseksi
        if tempo is not None and start < tempo.size:
            local_min = max(0.4, g.min_shot / float(np.sqrt(tempo[start])))
        else:
            local_min = g.min_shot

        at = max(start * HOP - g.lead, last_cut + local_min, 0.0)
        if hang and current >= 0 and not active[current, start]:
            # Kuvassa oleva puhuja on jo vaiennut: hänen kasvonsa jäävät
            # hännän verran, vaikka seuraava olisi jo äänessä. Jos hän on yhä
            # äänessä — päällekkäispuhe — hännälle ei ole paikkaa: leikkaus ei
            # johdu siitä että hän lopetti.
            spoke = int(last_speech[current, start])
            if spoke >= 0:
                at = max(at, (spoke + 1) * HOP + hang)
        if at >= end * HOP:
            continue  # ennakko, häntä ja minimikesto söivät koko jakson
        cuts.append((at, target))
        current = target
        last_cut = at
    return cuts


def _find_breath_point(
    grid: Grid | None, speaker_angle: str, target_time: float, window: float = 1.5
) -> float:
    """Etsii luontevan tauko- tai hengähdyskohdan leikkaukselle."""
    if grid is None:
        return target_time
    sp = next((s for s in grid.speakers if s.close_key == speaker_angle), None)
    if sp is None or sp.on.size == 0:
        return target_time

    t_rel = target_time - grid.program_start
    t_start = max(0.0, t_rel - window)
    t_end = min(grid.duration, t_rel + window)
    i0 = int(round(t_start / HOP))
    i1 = int(round(t_end / HOP))
    if i1 <= i0:
        return target_time

    sub_on = sp.on[i0:i1]
    # 1. Ensisijaisesti etsitään taukoa (on == False)
    if not np.all(sub_on):
        runs = _runs(sub_on.astype(np.int8))
        pause_runs = [(r_start, r_end) for r_start, r_end, val in runs if not val]
        if pause_runs:
            best = max(pause_runs, key=lambda p: p[1] - p[0])
            mid_idx = i0 + (best[0] + best[1]) // 2
            return grid.program_start + mid_idx * HOP

    # 2. Jos puhe on tasaista eikä äänessä ole selkeää notkahdusta (>3 dB), pysytään tavoiteajassa
    sub_level = sp.level[i0:i1]
    if sub_level.size > 0:
        min_val = float(np.min(sub_level))
        max_val = float(np.max(sub_level))
        if max_val - min_val >= 3.0:
            min_idx = i0 + int(np.argmin(sub_level))
            return grid.program_start + min_idx * HOP

    return target_time


def _available_between(sp: SpeakerLanes, grid: Grid, start: float, end: float) -> bool:
    """Onko puhujan lähikuva olemassa koko välillä [start, end)."""
    if sp.available is None:
        return True
    lo = int(round((start - grid.program_start) / HOP))
    hi = int(round((end - grid.program_start) / HOP))
    lo, hi = max(0, lo), min(grid.n, hi)
    if hi <= lo:
        return False
    return bool(sp.available[lo:hi].all())


def _reaction_point(
    grid: Grid | None, marks, avoid_angle: str, target: float, window: float
):
    """Lähin **mitattu** reaktiohetki tavoiteajan ympäriltä.

    Aikakatkaisu tietää vain että aikaa on kulunut; mittaus tietää että
    jotain tapahtuu. Jälkimmäinen on vahvempi signaali, joten kun pitkä
    puheenvuoro on katkaistava ja lähellä on mitattu hetki, katkaisu
    siirretään siihen. Ilman sitä katkaisukohta on kellon valitsema ja
    kuunteljan kasvot sattumaa.

    Palauttaa ``(aika, kulma, nimi)`` tai ``None``. Haku on kaksi
    ``flatnonzero``ta muutaman sadan ruudun yli, eli päätöskerroksen
    millisekuntibudjetissa.
    """
    if marks is None or grid is None or not grid.speakers:
        return None
    centre = int(round((target - grid.program_start) / HOP))
    low = max(0, centre - int(round(window / HOP)))
    high = min(grid.n, centre + int(round(window / HOP)))
    if high <= low:
        return None
    best = None
    for index, speaker in enumerate(grid.speakers):
        if not speaker.close_key or speaker.close_key == avoid_angle:
            continue
        if index >= marks.shape[0]:
            continue
        hits = np.flatnonzero(marks[index, low:high])
        if not hits.size:
            continue
        pick = int(hits[np.argmin(np.abs(hits - (centre - low)))])
        at = grid.program_start + (low + pick) * HOP
        distance = abs(at - target)
        if best is None or distance < best[0]:
            best = (distance, at, speaker.close_key, speaker.name)
    return best[1:] if best else None


def _force_wide(
    segments: list[Segment],
    g: Globals,
    wide_label: str,
    wide_key: str,
    grid: Grid | None = None,
    marks=None,
) -> list[Segment]:
    """Katkaisee pitkän puheenvuoron laajaan tai reaktiokuvaan.

    Yksi lähikuva ei kanna loputtomiin: kun sama puhuja pitää lattiaa
    ``wide_every`` sekuntia, kuva vaihtuu laajaan tai reaktioon.
    """
    if g.wide_every <= 0 or not wide_key:
        return segments
    stay = g.long_take_rule == LONGTAKE_STAY
    # Kumpikin reaktiosääntö käyttää mitattuja hetkiä; ero on siinä mitä
    # katkaisun sisään mahtuu.
    reaction = g.long_take_rule in (LONGTAKE_REACTION, LONGTAKE_REACTION_WIDE)
    through_wide = g.long_take_rule == LONGTAKE_REACTION_WIDE
    hold = max(g.wide_hold, g.min_shot)

    def alt_target(speaker_angle: str, start: float, end: float) -> tuple[str, str]:
        """Mihin katkaisu menee: reaktiokuvaan jos sellainen on, muuten laajaan.

        Kulman on oltava olemassa koko sen ajan jonka se on kuvassa.
        Monikamerassa kulma voi puuttua osasta kokonaan, ja siihen
        leikkaaminen tuottaisi viennissä kuvan jota ei ole.
        """
        if reaction and grid is not None:
            for other in grid.speakers:
                if not other.close_key or other.close_key == speaker_angle:
                    continue
                if _available_between(other, grid, start, end):
                    return other.close_key, other.name
        return wide_key, wide_label

    out: list[Segment] = []
    for seg in segments:
        if seg.angle == wide_key or seg.duration <= g.wide_every:
            out.append(seg)
            continue
        if stay:
            target_cut = seg.start + g.wide_every
            cut = _find_breath_point(
                grid, seg.angle, target_cut, window=min(1.5, g.wide_every * 0.2)
            )
            measured = _reaction_point(
                grid, marks if reaction else None, seg.angle, target_cut,
                window=min(REACTION_REACH, g.wide_every * 0.35))
            if measured is not None:
                cut = measured[0]
            if cut < seg.start + g.min_shot or seg.end - cut < g.min_shot:
                cut = target_cut
            if seg.end - cut < g.min_shot:
                # Loppu on liian lyhyt omaksi kuvakseen; puhuja jatkaa.
                out.append(seg)
                continue
            insert_key, insert_label = alt_target(seg.angle, cut, seg.end)
            out.append(Segment(seg.angle, seg.label, seg.start, cut))
            out.append(Segment(insert_key, insert_label, cut, seg.end))
            continue
        cursor = seg.start
        to_alt = False
        while cursor < seg.end:
            step_len = hold if to_alt else g.wide_every
            target_stop = min(cursor + step_len, seg.end)
            if not to_alt and target_stop < seg.end and grid is not None:
                stop = _find_breath_point(
                    grid, seg.angle, target_stop, window=min(1.5, g.wide_every * 0.2)
                )
                # Mitattu hetki voittaa hengähdyskohdan: hengähdys kertoo
                # että tähän *voi* leikata, mitattu hetki että tässä on
                # jotain katsottavaa.
                measured = _reaction_point(
                    grid, marks if reaction else None, seg.angle, target_stop,
                    window=min(REACTION_REACH, g.wide_every * 0.35))
                if measured is not None:
                    stop = measured[0]
                if stop < cursor + g.min_shot or seg.end - stop < g.min_shot:
                    stop = target_stop
            else:
                stop = target_stop

            if seg.end - stop < g.min_shot:
                stop = seg.end
            if to_alt:
                insert_key, insert_label = alt_target(seg.angle, cursor, stop)
                # Reaktio, laaja, takaisin: kolme kuvaa yhden sijaan, kun
                # katkaisun kesto riittää kumpaankin omaksi kuvakseen.
                # Alle sen se olisi kaksi välähdystä eikä kahta kuvaa.
                pivot = cursor + max(g.min_shot, (stop - cursor) / 2.0)
                if (through_wide and insert_key != wide_key and wide_key
                        and stop - pivot >= g.min_shot
                        and pivot - cursor >= g.min_shot):
                    out.append(Segment(insert_key, insert_label, cursor, pivot))
                    out.append(Segment(wide_key, wide_label, pivot, stop))
                else:
                    out.append(Segment(insert_key, insert_label, cursor, stop))
            else:
                out.append(Segment(seg.angle, seg.label, cursor, stop))
            cursor = stop
            to_alt = not to_alt
    return _merge(out)


def _bookend_wide(
    segments: list[Segment], g: Globals, wide_label: str, wide_key: str
) -> list[Segment]:
    """Ohjelma alkaa ja päättyy laajaan. Aina, eikä se ole säädin.

    Se on leikkauskonventio eikä makuasia. Ensimmäinen kuva kertoo missä
    ollaan ja keitä on paikalla; lähikuvasta alkava ohjelma pudottaa
    katsojan keskelle kasvoja tietämättä huonetta. Viimeinen päästää irti,
    ja lähikuvaan päättyvä jää roikkumaan.

    Miksi ei valintana: sen poistaminen on Final Cutissa yksi veto, ja
    juuri se tekee siitä huonon säätimen. Oletuksen kääntäminen maksaa
    yhden vedon kerran; valinta maksaa jokaiselle käyttäjälle yhden
    päätöksen, ja päätöksiä on jo se määrä jonka takia ensimmäisellä
    ruudulla on järjestys eikä luettelo. Sama peruste kuin panoroinnin
    määrällä, joka ei ole liuku.

    Kesto on ohjelman oma ``min_shot`` eikä oma vakionsa: pään ja hännän
    kuvat ovat kuvia siinä missä muutkin. Oma luku ajautuisi
    rytmiprofiilien kanssa eri suuntaan, sillä hektinen 1,4 s ja
    rauhallinen 4,5 s tarkoittavat eri kuvaa. Sama valinta kuin
    reaktiokuvien marginaalilla, joka on ``min_shot`` eikä oma vakionsa.

    Jos kuvasta ei saa irrotettua laajaa jättämättä loppuosaa alle
    minimin, koko kuva on laaja: yksi kunnollinen kuva on parempi kuin
    kaksi välähdystä. Lyhyellä ohjelmalla se tarkoittaa pelkkää laajaa, ja
    se on rehellinen vastaus ohjelmalle johon ei mahdu kolmea kuvaa.
    """
    if not segments or not wide_key:
        return segments

    out = list(segments)

    first = out[0]
    if first.angle != wide_key:
        if first.duration >= 2 * g.min_shot:
            head = first.start + g.min_shot
            out[0] = Segment(first.angle, first.label, head, first.end)
            out.insert(0, Segment(wide_key, wide_label, first.start, head))
        else:
            out[0] = Segment(wide_key, wide_label, first.start, first.end)

    last = out[-1]
    if last.angle != wide_key:
        if last.duration >= 2 * g.min_shot:
            tail = last.end - g.min_shot
            out[-1] = Segment(last.angle, last.label, last.start, tail)
            out.append(Segment(wide_key, wide_label, tail, last.end))
        else:
            out[-1] = Segment(wide_key, wide_label, last.start, last.end)

    return out


def _merge(segments: list[Segment]) -> list[Segment]:
    """Yhdistää peräkkäiset saman kuvan jaksot ja pudottaa tyhjät."""
    merged: list[Segment] = []
    for seg in segments:
        if seg.end <= seg.start:
            continue
        if merged and merged[-1].angle == seg.angle:
            merged[-1].end = seg.end
        else:
            merged.append(seg)
    return merged


def decide(grid: Grid, g: Globals, marks=None) -> Decision:
    """Leikkauslista. Tämän on pyörittävä millisekunneissa.

    ``marks`` on valinnainen ``(puhujia, n)`` totuustaulukko mitatuista
    reaktiohetkistä. Taulukko eikä rajapinta: päätöskerros ei lue
    tiedostoja, ks. CLAUDE.md.
    """
    want, active = _want_array(grid, g)
    tempo = _compute_tempo(active, grid.n)
    if grid.wide_key:
        initial_target = WIDE
    else:
        initial_target = next(
            (int(t) for _, _, t in _runs(want) if t >= 0),
            0 if grid.speakers else WIDE,
        )
    cuts = _cut_points(
        want, g, tempo=tempo, active=active, initial_target=initial_target
    )
    total = grid.duration

    segments: list[Segment] = []
    for index, (at, target) in enumerate(cuts):
        end = cuts[index + 1][0] if index + 1 < len(cuts) else total
        if end <= at:
            continue
        if target == WIDE:
            key, label = grid.wide_key, WIDE_LABEL
        else:
            sp = grid.speakers[target]
            key, label = (sp.close_key or grid.wide_key), sp.name
            if not sp.close_key:
                label = WIDE_LABEL
        if not key and grid.speakers:
            first_sp = next((s for s in grid.speakers if s.close_key), None)
            if first_sp:
                key, label = first_sp.close_key, first_sp.name
        segments.append(
            Segment(key, label, grid.program_start + at, grid.program_start + end)
        )
    segments = _merge(segments)
    segments = _force_wide(segments, g, WIDE_LABEL, grid.wide_key,
                           grid=grid, marks=marks)
    segments = _merge(_bookend_wide(segments, g, WIDE_LABEL, grid.wide_key))

    # Esikatselua varten: mikä kuva milläkin hetkellä.
    chosen = np.full(grid.n, WIDE, dtype=np.int32)
    key_to_index = {
        sp.close_key: i for i, sp in enumerate(grid.speakers) if sp.close_key
    }
    for seg in segments:
        lo = int(round((seg.start - grid.program_start) / HOP))
        hi = int(round((seg.end - grid.program_start) / HOP))
        chosen[max(0, lo) : max(0, hi)] = key_to_index.get(seg.angle, WIDE)

    return Decision(segments=segments, active=active, chosen=chosen)

