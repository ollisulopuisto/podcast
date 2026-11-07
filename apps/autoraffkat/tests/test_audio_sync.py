"""Ääniverhojen aikasiirron sovitus tunnettuun lähderaitaan."""

import numpy as np
import pytest

from autoraffkat.audio.sync import estimate_offset


@pytest.mark.parametrize("source_start, expected_shift", [(70, 0.5), (170, -0.5)])
def test_estimate_offset_returns_shift_to_apply(source_start, expected_shift):
    rng = np.random.default_rng(42)
    signal = rng.normal(size=400)
    reference = np.zeros(600)
    source = np.zeros(600)
    reference[120:520] = signal
    source[source_start : source_start + len(signal)] = signal

    result = estimate_offset(
        reference,
        source,
        hop_seconds=0.01,
        max_shift_seconds=1.0,
        min_overlap_seconds=3.0,
    )

    assert result is not None
    assert result.shift_seconds == pytest.approx(expected_shift)
    assert result.correlation == pytest.approx(1.0)


def test_estimate_offset_returns_none_for_flat_audio():
    result = estimate_offset(
        np.zeros(100),
        np.zeros(100),
        hop_seconds=0.1,
        max_shift_seconds=2.0,
        min_overlap_seconds=1.0,
    )

    assert result is None


def test_estimate_offset_respects_search_limit():
    rng = np.random.default_rng(73)
    signal = rng.normal(size=300)
    reference = np.zeros(500)
    source = np.zeros(500)
    reference[150:450] = signal
    source[50:350] = signal

    result = estimate_offset(
        reference,
        source,
        hop_seconds=0.01,
        max_shift_seconds=0.25,
        min_overlap_seconds=2.0,
    )

    assert result is not None
    assert abs(result.shift_seconds) <= 0.25


def test_estimate_offset_rejects_incompatible_envelopes():
    with pytest.raises(ValueError, match="yksiulotteisia"):
        estimate_offset(
            np.zeros((2, 10)),
            np.zeros(10),
            hop_seconds=0.1,
            max_shift_seconds=1.0,
            min_overlap_seconds=0.5,
        )
