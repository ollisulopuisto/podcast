"""Lohkotaso: puhujan oman puheen jaksot samalle tasolle ennen ketjua.

Kolme aikaskaalaa, hitain ensin:

* **lohko** (tämä) — vakio vahvistus koko lohkolle: eri päivä, eri otto,
  mikin etäisyys. Käyttäjä tekee tämän Hindenburgissa alueen vahvistuksella.
* **tasonkuljettaja** (``chain.ride``) — ~3 s, ±6 dB: ajautuminen lohkon
  sisällä. Se palaa nollaan jokaisen lohkon välissä ja nousee 4 sekunnissa,
  joten lohkon alku soi korjaamatta, eikä se yllä yli kuuden desibelin.
* **kompressori** — tavut ja huiput.

Sääntö on mitattu käyttäjän korvalla tehdyistä korjauksista (vst s13e03,
local-hburg 2026-10-05): Ollin intro oli +12,8 / +10,0 / +7,8 dB hänen
tasonsa yllä ja hän laski sen −12,2 / −7,5 / −5,3 dB, eli jätti sen
+0,7…+2,5 dB kuumaksi. Alle ~2 dB:n poikkeamiin hän ei koskenut, eikä
lohkoihin joiden lukema nousi yhden purskeen takia: 26:18 (+4,7 koko
lohkosta, ilman neljän sekunnin painokasta loppua −0,1) ja 36:41 (+8,5,
ilman viiden sekunnin huutoa +1,1). Siksi lohkon taso on **mediaani**
oman puheen kehyksistä eikä keskiarvo: purske joka on alle puolet lohkosta
ei liikuta sitä.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise

import numpy as np

from .grid import HOP_SEC

#: Tätä lyhyempi tauko ei katkaise lohkoa: lauseiden väli on puhetta.
#: Sama luku kuin ``chain.RIDER_MAX_DB``:n mittauksessa ja ``nhsx.activity``ssä.
GAP_CLOSE_S = 1.5
#: Lyhyempää lohkoa ei korjata: mediaani ei ole luotettava muutamasta tavusta.
MIN_BLOCK_S = 1.0
#: Viitetaso lasketaan vähintään näin pitkistä lohkoista (s13e03:n mittaus).
MIN_REFERENCE_S = 5.0
#: Pienempään poikkeamaan ei kosketa. Käyttäjä jätti ≤ 2 dB koskematta;
#: kolme jättää tilaa mittauksen hajonnalle.
THRESHOLD_DB = 3.0
#: Kuinka suuren osan poikkeamasta korjaus vie. Käyttäjä: 12,2/12,8,
#: 7,5/10,0, 5,3/7,8 — keskimäärin noin 0,8.
SHARE = 0.8
#: Suurin korjaus, dB. Ollin intron suurin oli 12,2.
MAX_CORRECTION_DB = 12.0
#: Vahvistuksen muutos tauon keskellä, raised-cosine tämän mittaisena.
RAMP_S = 0.05


@dataclass(frozen=True)
class Block:
    """Yksi lohko: aikajanan sekunnit, oman puheen kesto, taso ja korjaus."""

    start: float
    end: float
    own_s: float
    level_db: float
    deviation_db: float
    gain_db: float


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    edges = np.diff(np.concatenate(([0], mask.astype(np.int8), [0])))
    return list(zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1), strict=True))


def _weighted_median(values, weights) -> float:
    order = np.argsort(values)
    v, w = np.asarray(values)[order], np.asarray(weights)[order]
    cum = np.cumsum(w)
    return float(v[np.searchsorted(cum, cum[-1] / 2.0)])


def block_gains(level_db: np.ndarray, own: np.ndarray, hop: float = HOP_SEC) -> list[Block]:
    """Lohkot ja niiden korjaukset tasokäyrästä ja oman puheen maskista.

    ``level_db`` ja ``own`` ovat samassa ``hop``-ruudukossa aikajanan
    alusta (``rms.envelope_for``, ``masks``).
    """
    level_db = np.asarray(level_db, dtype=np.float64)
    own = np.asarray(own, dtype=bool)[: len(level_db)]
    gap = int(round(GAP_CLOSE_S / hop))
    merged: list[list[int]] = []
    for a, b in _runs(own):
        if merged and a - merged[-1][1] <= gap:
            merged[-1][1] = b
        else:
            merged.append([a, b])

    found = []
    for a, b in merged:
        mine = own[a:b]
        seconds = float(mine.sum()) * hop
        found.append((a, b, seconds, float(np.median(level_db[a:b][mine]))))
    if not found:
        return []
    long_enough = [f for f in found if f[2] >= MIN_REFERENCE_S] or found
    reference = _weighted_median([f[3] for f in long_enough], [f[2] for f in long_enough])

    out = []
    for a, b, seconds, level in found:
        deviation = level - reference
        gain = 0.0
        if seconds >= MIN_BLOCK_S and abs(deviation) > THRESHOLD_DB:
            gain = float(np.clip(-SHARE * deviation, -MAX_CORRECTION_DB, MAX_CORRECTION_DB))
        out.append(Block(a * hop, b * hop, seconds, level, deviation, round(gain, 2)))
    return out


def gain_block(found: list[Block], low: int, high: int, rate: int) -> np.ndarray:
    """Lineaarinen vahvistus näyteväliltä ``[low, high)``.

    Kukin lohko omistaa ajan puoliväliin naapureistaan; vaihto tapahtuu
    tauon keskellä ``RAMP_S``:n raised-cosinena. Tauot ovat vähintään
    ``GAP_CLOSE_S`` pitkiä, joten vaihto ei osu kenenkään puheeseen.
    Paloittain, koska koko jakson käyrä float64:nä olisi gigatavu.
    """
    t = np.arange(low, high, dtype=np.float64) / rate
    if not found:
        return np.ones(t.size)
    db = np.full(t.size, found[0].gain_db)
    for left, right in pairwise(found):
        step = right.gain_db - left.gain_db
        if not step:
            continue
        middle = (left.end + right.start) / 2.0
        share = np.clip((t - middle) / RAMP_S + 0.5, 0.0, 1.0)
        db += step * (1.0 - np.cos(np.pi * share)) / 2.0
    return 10.0 ** (db / 20.0)


def gain_curve(found: list[Block], frames: int, rate: int) -> np.ndarray:
    """Koko tiedoston vahvistus. Testeille ja lyhyille tiedostoille."""
    return gain_block(found, 0, frames, rate)
