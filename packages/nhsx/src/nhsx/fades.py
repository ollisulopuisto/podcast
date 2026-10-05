"""Mielivaltainen äänenvoimakkuuskäyrä Hindenburgin `<Fade>`-luiskiksi.

Hindenburgin luiska kulkee edellisestä tasosta arvoon ``Gain``
raised-cosine-muodossa ja jää sinne (``nhsx.mix.Ramp``, mitattu). Käyttäjän
omat häivytykset ovat toista muotoa: vst s13e03:n musiikkipohjissa nousu
−68 dB:stä −8 dB:iin kesti noin 8,6 s, alussa noin −8 dB / 0,5 s ja sitten
loivenevasti. Yksi luiska ei osaa sitä. Lyhyinä paloina se osaa: palojen
välissä käyrä kulkee pisteestä pisteeseen, ja palojen raised-cosine-mutka
jää toleranssin alle.

Pilkkominen on ahne: jokainen luiska venytetään niin pitkäksi kuin se
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
