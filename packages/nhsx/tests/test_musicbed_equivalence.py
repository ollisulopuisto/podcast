"""Exact output parity with the pre-vectorization music-bed curve."""

import random

import pytest
from reference_musicbed import curve as scalar_curve

from nhsx import musicbed


@pytest.mark.parametrize("cold_open", [False, True])
def test_unfinished_rise_takes_priority_over_overlapping_fall(cold_open):
    args = (0.0, 10.0, [(0.0, 9.0), (20.0, 30.0)])
    actual = musicbed.curve(*args, cold_open=cold_open)
    assert actual == scalar_curve(*args, cold_open=cold_open)
    if not cold_open:
        assert actual[165] == (8.25, -13.0)
        assert actual[199][1] == -2.26


def test_compressed_fade_becomes_silent_at_original_grid_point():
    args = (2976.67, 2985.12, [(2900.0, 2976.62)])
    actual = musicbed.curve(*args)
    assert actual[154][1] == musicbed.SILENCE_DB
    assert actual == scalar_curve(*args)


@pytest.mark.parametrize("seed", [234, 1337, 20261118])
def test_vectorized_curve_exactly_matches_scalar_over_varied_timelines(seed):
    rng = random.Random(seed)
    for case in range(150):
        # Quantized and arbitrary times exercise rounding boundaries as well
        # as empty speech, no gap, compressed falls and cold-open tails.
        start = rng.uniform(-10.0, 4000.0)
        duration = rng.uniform(0.0, 100.0)
        if case % 2:
            start = round(start, 2)
            duration = round(duration, 2)
        speech = []
        cursor = start - rng.uniform(0.0, 30.0)
        for _ in range(case % 7):
            cursor += rng.uniform(0.0, 15.0)
            stop = cursor + rng.uniform(0.0, 30.0)
            speech.append((cursor, stop))
            cursor = stop
        rng.shuffle(speech)
        args = (start, start + duration, speech)
        for cold_open in (False, True):
            assert musicbed.curve(*args, cold_open=cold_open) == scalar_curve(
                *args, cold_open=cold_open
            ), (seed, case, args, cold_open)


def test_interpolation_keeps_scalar_rounding_at_half_centibel():
    args = (
        167.0,
        178.35,
        [
            (159.70270429712573, 175.1416933986383),
            (183.4145874885869, 208.73895040656856),
        ],
    )
    actual = musicbed.curve(*args)
    assert actual[197][1] == -5.92
    assert actual == scalar_curve(*args)


def test_fall_interpolation_does_not_precompute_the_slope():
    args = (0.011666666666666667, 3.85, [(-20.0, -5.84), (10.0, 20.0)])
    actual = musicbed.curve(*args)
    assert actual[0] == (0.0, -0.1)
    assert actual == scalar_curve(*args)
