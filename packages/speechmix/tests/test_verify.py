"""The two checks that catch a plug-in lying about what it did.

The sample count must not change: the export references the processed file
with the same times as the original. And shift is measured separately, because
length alone cannot detect a plug-in that reports its latency wrongly.
"""

import numpy as np
import pytest
from speechmix import verify
from speechmix.errors import LengthChanged

RATE = 48000


def test_a_changed_sample_count_is_an_error():
    before = np.zeros(1000)
    with pytest.raises(LengthChanged) as excinfo:
        verify.assert_same_length(before, np.zeros(995), "plug-in")
    assert "-5 samples" in str(excinfo.value)


def test_an_unchanged_count_passes_through():
    after = np.ones(1000)
    assert verify.assert_same_length(np.zeros(1000), after, "plug-in") is after


def test_a_latency_the_length_cannot_see_is_measured():
    """4641 samples is dxRevive's latency with ``reset=False``.

    Rolled rather than padded, so the length is identical and only the
    correlation can find it.
    """
    rng = np.random.default_rng(1)
    reference = rng.normal(0, 1, 5 * RATE)
    for shift in (0, 4641, -320):
        assert verify.measure_shift(reference, np.roll(reference, shift)) == shift


def test_a_shifted_stage_is_an_error_even_at_the_same_length():
    rng = np.random.default_rng(2)
    reference = rng.normal(0, 1, 2 * RATE)
    with pytest.raises(LengthChanged) as excinfo:
        verify.assert_no_shift(reference, np.roll(reference, 128), "plug-in")
    assert "+128 samples" in str(excinfo.value)
    assert verify.assert_no_shift(reference, reference.copy(), "plug-in") == 0


def test_the_correlation_is_an_fft():
    """``np.correlate(..., "full")`` is O(n^2) and took 132 s on a 20-minute
    file -- longer than the plug-in whose latency it was checking. Twenty
    minutes here would make the point better; one is enough to fail loudly if
    anyone swaps the implementation back.
    """
    import time

    rng = np.random.default_rng(3)
    reference = rng.normal(0, 1, 60 * RATE)
    started = time.monotonic()
    assert verify.measure_shift(reference, np.roll(reference, 1024)) == 1024
    assert time.monotonic() - started < 10.0
