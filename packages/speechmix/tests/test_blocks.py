"""Lohkotaso: puhujan oman puheen jaksot samalle tasolle ennen ketjua.

Sääntö on mitattu käyttäjän korvalla tehdyistä korjauksista (vst s13e03,
2026-10-05): Ollin intro oli +8…+13 dB hänen tasonsa yllä ja se laskettiin
−5,3…−12,2 dB, jättäen +0,7…+2,5. Alle ~2 dB:n poikkeamiin ei koskettu,
eikä lohkoihin joiden lukema nousi yhden painokkaan purskeen takia.
"""

from __future__ import annotations

import numpy as np

from speechmix import blocks
from speechmix.grid import HOP_SEC


def _curve(spans, seconds=120.0, floor=-80.0):
    """Tasokäyrä (dB, HOP) ja oma puhe: ``spans`` = (alku, loppu, taso)."""
    n = int(seconds / HOP_SEC)
    db = np.full(n, floor, dtype=np.float32)
    own = np.zeros(n, dtype=bool)
    for a, b, level in spans:
        i, j = int(a / HOP_SEC), int(b / HOP_SEC)
        db[i:j] = level
        own[i:j] = True
    return db, own


NORMAL = [(10, 20, -30.0), (25, 35, -30.0), (40, 50, -31.0), (55, 65, -29.0)]


def _gain_at(found, t):
    for block in found:
        if block.start <= t < block.end:
            return block.gain_db
    return 0.0


def test_a_hot_block_comes_down_most_of_the_way():
    db, own = _curve([(0, 8, -20.0), *NORMAL])
    found = blocks.block_gains(db, own)
    gain = _gain_at(found, 4.0)
    # Poikkeama +10 dB, korjaus 80 %: −8 dB. Käyttäjä: +10,0 → −7,5.
    assert abs(gain - -8.0) < 0.5
    assert all(_gain_at(found, t) == 0.0 for t in (15, 30, 45, 60))


def test_small_deviations_are_left_alone():
    db, own = _curve([(0, 8, -28.0), *NORMAL])
    assert _gain_at(blocks.block_gains(db, own), 4.0) == 0.0


def test_one_loud_burst_does_not_move_the_block():
    """Ollin 36:41: viisi sekuntia huutoa 14 sekunnin lohkon alussa. Koko
    lohkon keskiarvo oli +8,5 dB, ilman pursketta +1,1 — käyttäjä ei
    korjannut. Mediaani ei liiku purskeesta."""
    db, own = _curve([(0, 5, -18.0), (5, 14, -30.0)] + [(s + 20, e + 20, lv) for s, e, lv in NORMAL])
    assert _gain_at(blocks.block_gains(db, own), 8.0) == 0.0


def test_correction_is_capped():
    db, own = _curve([(0, 8, -5.0), *NORMAL])
    assert _gain_at(blocks.block_gains(db, own), 4.0) == -blocks.MAX_CORRECTION_DB


def test_gain_curve_changes_in_the_gap_without_a_step():
    db, own = _curve([(0, 8, -20.0), *NORMAL])
    found = blocks.block_gains(db, own)
    rate = 1000
    curve = blocks.gain_curve(found, int(120 * rate), rate)
    assert curve.shape == (120 * rate,)
    # Lohkon sisällä täysi korjaus, seuraavassa lohkossa ei mitään.
    assert abs(20 * np.log10(curve[4 * rate]) - _gain_at(found, 4.0)) < 1e-6
    assert abs(curve[15 * rate] - 1.0) < 1e-9
    # Muutos tapahtuu tauon (8–10 s) keskellä, liukuen: ei hyppyä näytteiden välillä.
    step = np.max(np.abs(np.diff(20 * np.log10(curve))))
    assert step < 0.5
    assert abs(20 * np.log10(curve[int(8.5 * rate)]) - _gain_at(found, 4.0)) < 1e-6
