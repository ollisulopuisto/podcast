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


def test_a_hot_block_comes_down_all_the_way():
    """Käyttäjä 2026-10-07: «the cold open should be the same loudness as the
    rest of the show». 80 %:n korjaus (sovitettu siitä että käyttäjä jätti
    intron korvalla 1–2 dB kuumaksi) jätti Ollin +12,5 dB:n intron +2,5:een."""
    db, own = _curve([(0, 8, -20.0), *NORMAL])
    found = blocks.block_gains(db, own)
    gain = _gain_at(found, 4.0)
    assert abs(gain - -10.0) < 0.5
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


def _mixed(spans, seconds=120.0, floor=-80.0, seed=0):
    """Kuten ``_curve``, mutta lohkon kehyksistä osuus ``soft`` on 15 dB
    hiljaisempia (tavujen hännät, hengitys): ``(alku, loppu, taso, soft)``."""
    rng = np.random.default_rng(seed)
    n = int(seconds / HOP_SEC)
    db = np.full(n, floor, dtype=np.float32)
    own = np.zeros(n, dtype=bool)
    for a, b, level, soft in spans:
        i, j = int(a / HOP_SEC), int(b / HOP_SEC)
        quiet = rng.random(j - i) < soft
        db[i:j] = np.where(quiet, level - 15.0, level)
        own[i:j] = True
    return db, own


def test_a_block_with_more_soft_frames_is_not_quiet():
    """Olli 0:33 (27 s): kehysten mediaani luki −7,3 dB ja olisi nostanut
    +5,9 dB; LUFS luki −2,4 ja käyttäjä ei koskenut. Taso on energiaa,
    ei hiljaisten kehysten osuus."""
    normal = [(s, e, -30.0, 0.3) for s, e, _ in NORMAL]
    db, own = _mixed([(0, 7.5, -30.0, 0.6), *normal])
    assert _gain_at(blocks.block_gains(db, own), 4.0) == 0.0


def test_a_short_loud_part_still_counts_when_it_is_the_block():
    """Ollin ensimmäinen introlohko: LUFS +12,8, käyttäjä −12,2. Kehysten
    mediaani näki siitä +4,3 ja korjasi vain −3,4."""
    normal = [(s, e, -30.0, 0.3) for s, e, _ in NORMAL]
    db, own = _mixed([(0, 7, -14.0, 0.7), *normal])
    gain = _gain_at(blocks.block_gains(db, own), 3.0)
    assert gain <= -8.0


def test_slivers_are_not_corrected():
    """Kari 16:16, 40:41, 42:49; Panu 1:24, 38:12: 1–2 s, −51…−61 dB —
    hengitys tai vuoto. Kehysten mediaani nosti ne +12 dB:llä."""
    db, own = _curve([(0, 1.5, -60.0), *NORMAL])
    assert _gain_at(blocks.block_gains(db, own), 0.7) == 0.0


def test_boosts_are_capped_lower_than_cuts():
    db, own = _curve([(0, 8, -45.0), *NORMAL])
    assert _gain_at(blocks.block_gains(db, own), 4.0) == blocks.MAX_BOOST_DB


def test_a_loud_stretch_inside_a_block_is_flagged_not_changed():
    """Ollin 36:41: viisi sekuntia huutoa +7 dB lohkonsa yllä. Käyttäjä ei
    korjannut — se on painotusta, ja painotus on sisältöä. Työkalu merkitsee
    sen kuunneltavaksi eikä muuta tasoa."""
    db, own = _curve([(0, 5, -23.0), (5, 14, -30.0), *[(s + 20, e + 20, lv) for s, e, lv in NORMAL]])
    found = blocks.block_gains(db, own)
    flags = blocks.loud_spans(db, own, found)
    assert len(flags) == 1
    flag = flags[0]
    assert abs(flag.start - 0.0) < 0.5 and abs(flag.end - 5.0) < 0.5
    assert abs(flag.excess_db - 7.0) < 0.5
    assert _gain_at(found, 2.0) == 0.0          # lohkoa ei korjattu


def test_a_short_spike_or_a_small_rise_is_not_flagged():
    spike = [(0, 4, -30.0), (4, 4.5, -20.0), (4.5, 9, -30.0)]
    rise = [(30, 33, -27.0), (33, 39, -30.0)]
    db, own = _curve([*spike, *rise, *[(s + 40, e + 40, lv) for s, e, lv in NORMAL]])
    assert blocks.loud_spans(db, own, blocks.block_gains(db, own)) == []


def test_a_short_hot_line_is_cut():
    """Kylmä alku äänitetään usein eri aikaan, ja repliikit ovat lyhyitä
    (käyttäjä, 2026-10-07): 1,5 sekunnin +10 dB:n repliikki lasketaan.
    Nosto vaatii edelleen 3 s, koska lyhyt hiljainen pätkä on usein
    hengitystä tai vuotoa (``test_slivers_are_not_corrected``)."""
    db, own = _curve([(0, 1.5, -20.0), *NORMAL])
    assert abs(_gain_at(blocks.block_gains(db, own), 0.7) - -10.0) < 0.5
