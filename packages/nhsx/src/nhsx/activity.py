"""Milloin joku puhuu, istunnon aikajanalla.

Whisperin sana-ajat ovat arvio, ja nauru, hengitys ja «mm» jäävät usein
kokonaan ilman sanaa. Mikit kertovat sen mitä litterointi ei: tämä lukee
jokaisen puheraidan tason sen omista lähdetiedostoista, sijoittaa sen
aikajanalle alueittain ja kertoo milloin joku on äänessä.

Päätös on ``speechmix``in eikä tämän moduulin: raita on äänessä, kun sen
taso on oman pohjakohinansa yläpuolella ``grid.FLOOR_MARGIN_DB``:n verran
(``grid.lane``). Tämä moduuli vain hankkii tasot istunnosta.

Taso luetaan **raa'asta** lähteestä ilman alueen vahvistusta: marginaali on
pohjan yläpuolella, joten vahvistus ei saa siirtää kynnystä.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

import numpy as np

from speechmix import grid
from speechmix.dsp import FLOOR_DB

from .mix import plan
from .read import Session

#: Tätä lyhyempi tauko ei katkaise puhetta. Sama luku kuin
#: ``speechmix.chain.RIDER_MAX_DB``:n mittauksessa («lauseet 1,5 s aukot
#: umpeen») ja s13e03:n lohkomittauksessa: lauseiden välinen tauko on puhetta.
GAP_CLOSE_S = 1.5
#: Tätä lyhyempi ääni ei ole puhetta vaan naksahdus tai yksittäinen ruutu.
MIN_RUN_S = 0.2


def _runs(on: np.ndarray) -> list[tuple[int, int]]:
    out = []
    i = 0
    n = len(on)
    while i < n:
        if on[i]:
            j = i
            while j < n and on[j]:
                j += 1
            out.append((i, j))
            i = j
        else:
            i += 1
    return out


def _timeline_level(session: Session, track: str, envelope, n: int):
    """Raidan taso ja kelpoisuus aikajanan ruudukolla. Mykistetty alue ei kuulu."""
    level = np.full(n, FLOOR_DB, dtype=np.float32)
    valid = np.zeros(n, dtype=bool)
    for clip in plan(session).clips:
        if clip.speaker != track:
            continue
        curve = np.asarray(envelope(clip.path), dtype=np.float32)
        a = int(round(clip.start / grid.HOP_SEC))
        first = int(round(clip.file_offset / grid.HOP_SEC))
        count = int(round(clip.length / grid.HOP_SEC))
        piece = curve[first:first + count]
        b = min(n, a + len(piece))
        if b <= a:
            continue
        level[a:b] = piece[: b - a]
        valid[a:b] = True
    return level, valid


def speech_intervals(
    session: Session,
    tracks: Iterable[str],
    envelope: Callable[[str], np.ndarray] | None = None,
) -> list[tuple[float, float]]:
    """Aikajanan välit ``[(alku, loppu), ...]`` joilla jokin raidoista puhuu.

    ``envelope`` on ``polku -> dB-käyrä HOP-välein tiedoston alusta``; oletus
    on ``speechmix.rms.envelope_for`` ilman välimuistia.
    """
    if envelope is None:
        from speechmix.rms import envelope_for

        envelope = envelope_for
    duration = plan(session).duration
    n = int(np.ceil(duration / grid.HOP_SEC)) + 1
    anyone = np.zeros(n, dtype=bool)
    for track in tracks:
        level, valid = _timeline_level(session, track, envelope, n)
        if not valid.any():
            continue
        smoothed = grid.smooth(level)
        floor = grid.noise_floor(smoothed, valid)
        anyone |= valid & (smoothed > floor + grid.FLOOR_MARGIN_DB)

    gap = int(round(GAP_CLOSE_S / grid.HOP_SEC))
    runs = _runs(anyone)
    merged: list[list[int]] = []
    for a, b in runs:
        if merged and a - merged[-1][1] <= gap:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    shortest = int(round(MIN_RUN_S / grid.HOP_SEC))
    return [
        (a * grid.HOP_SEC, b * grid.HOP_SEC)
        for a, b in merged
        if b - a >= shortest
    ]
