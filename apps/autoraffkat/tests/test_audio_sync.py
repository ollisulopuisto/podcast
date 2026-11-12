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


def _reference_estimate_offset(reference, source, *, hop_seconds, max_shift_seconds,
                               min_overlap_seconds):
    """Vektorointia edeltänyt silmukkaimplementaatio (2026-11), säilytetty
    testien oraakkelina: uuden ja vanhan pitää antaa täsmälleen sama tulos."""
    import math as _math

    import numpy as _np

    from autoraffkat.audio.sync import OffsetEstimate

    ref = _np.asarray(reference, dtype=_np.float64)
    src = _np.asarray(source, dtype=_np.float64)
    max_lag = int(max_shift_seconds / hop_seconds)
    min_overlap = _math.ceil(min_overlap_seconds / hop_seconds)
    corr_size = len(ref) + len(src) - 1
    if corr_size <= 0:
        return None
    fft_size = 1 << (corr_size - 1).bit_length()
    cross = _np.fft.irfft(
        _np.fft.rfft(ref, fft_size) * _np.conjugate(_np.fft.rfft(src, fft_size)),
        fft_size,
    )
    ref_sum = _np.concatenate(([0.0], _np.cumsum(ref)))
    ref_sq_sum = _np.concatenate(([0.0], _np.cumsum(ref * ref)))
    src_sum = _np.concatenate(([0.0], _np.cumsum(src)))
    src_sq_sum = _np.concatenate(([0.0], _np.cumsum(src * src)))
    best = None
    for lag in range(-min(max_lag, len(src) - 1), min(max_lag, len(ref) - 1) + 1):
        src_start = max(0, -lag)
        ref_start = max(0, lag)
        count = min(len(src) - src_start, len(ref) - ref_start)
        if count < min_overlap:
            continue
        src_end = src_start + count
        ref_end = ref_start + count
        sx = src_sum[src_end] - src_sum[src_start]
        sy = ref_sum[ref_end] - ref_sum[ref_start]
        sxx = src_sq_sum[src_end] - src_sq_sum[src_start]
        syy = ref_sq_sum[ref_end] - ref_sq_sum[ref_start]
        dot = cross[lag if lag >= 0 else fft_size + lag]
        covariance = dot - sx * sy / count
        variance_src = sxx - sx * sx / count
        variance_ref = syy - sy * sy / count
        denominator = _math.sqrt(max(variance_src, 0.0) * max(variance_ref, 0.0))
        if denominator <= 1e-12:
            continue
        correlation = float(_np.clip(covariance / denominator, -1.0, 1.0))
        if best is None or correlation > best[0]:
            best = (correlation, lag)
    if best is None:
        return None
    correlation, lag = best
    return OffsetEstimate(lag * hop_seconds, correlation)


@pytest.mark.parametrize(
    "ref_len, src_len, offset_samples, max_shift_s",
    [
        (600, 600, 50, 2.0),     # lähde myöhässä
        (600, 600, -80, 2.0),    # lähde edellä
        (800, 400, 120, 3.0),    # eripituiset verhot
        (500, 700, -30, 1.5),
        (600, 600, 0, 0.5),      # ikkuna pienempi kuin etsintä
    ],
)
def test_vectorized_matches_the_loop_implementation(
    ref_len, src_len, offset_samples, max_shift_s
):
    rng = np.random.default_rng(7)
    signal = rng.normal(size=200)
    reference = np.zeros(ref_len)
    source = np.zeros(src_len)
    ref_at = 150
    src_at = ref_at - offset_samples
    if 0 <= src_at and src_at + len(signal) <= src_len and ref_at + len(signal) <= ref_len:
        reference[ref_at : ref_at + len(signal)] = signal
        source[src_at : src_at + len(signal)] = signal
    else:  # osittainen peitto: verhot sellaisenaan, satunnaista kohinaa mukaan
        reference[:] = rng.normal(size=ref_len)
        source[:] = rng.normal(size=src_len)

    kwargs = {"hop_seconds": 0.02, "max_shift_seconds": max_shift_s,
              "min_overlap_seconds": 1.0}
    expected = _reference_estimate_offset(reference, source, **kwargs)
    result = estimate_offset(reference, source, **kwargs)

    if expected is None:
        assert result is None
        return
    assert result is not None
    assert result.shift_seconds == expected.shift_seconds
    assert result.correlation == expected.correlation


def test_vectorized_matches_loop_on_flat_and_near_flat_audio():
    kwargs = {"hop_seconds": 0.02, "max_shift_seconds": 2.0, "min_overlap_seconds": 1.0}
    flat_ref = np.zeros(300)
    flat_src = np.zeros(300)
    assert estimate_offset(flat_ref, flat_src, **kwargs) is None
    assert _reference_estimate_offset(flat_ref, flat_src, **kwargs) is None

    rng = np.random.default_rng(11)
    quiet = rng.normal(scale=1e-9, size=300)  # käytännössä vakio: karsiutuu
    result = estimate_offset(quiet, quiet.copy(), **kwargs)
    expected = _reference_estimate_offset(quiet, quiet.copy(), **kwargs)
    assert (result is None) == (expected is None)


def test_estimate_offset_returns_none_when_an_envelope_is_empty():
    # Tyhjä mikki + lyhyt kameraverho: ei yhteistä ääntä, ei arviota.
    # (Regressio: vektoroitu versio indeksoi FFT-taulukon ohi, kun
    # tyhjän verhon pituus-1 meni negatiiviseksi.)
    reference = np.random.default_rng(11).normal(size=17)
    empty = np.array([])

    assert estimate_offset(
        reference, empty, hop_seconds=0.02,
        max_shift_seconds=300.0, min_overlap_seconds=5.0,
    ) is None
    assert estimate_offset(
        empty, reference, hop_seconds=0.02,
        max_shift_seconds=300.0, min_overlap_seconds=5.0,
    ) is None


def test_vectorized_scores_candidates_without_a_python_loop():
    # Vanha silmukka kävi jokaisen ehdokasviiveen läpi Pythonissa; vektorointi
    # pisteyttää kaikki kerrallaan. Vartiona kaikkien kutsujen määrä
    # (sys.monitoring) pisteytyksen aikana, ei jonkin apurin osuma: myös
    # min/max- tai millä tahansa apurilla kirjoitettu viivesilmukka tekee
    # vähintään yhden kutsun per viive eli yli 5000, kun vektoroitu polku
    # jää pariin tuhanteen FFT:n sisäisine kutsuineen. Deterministinen
    # työnmäärämitallus, ei kellonaikatesti.
    import sys

    calls = 0

    def count_call(code, offset, callable_, arg):
        nonlocal calls
        calls += 1

    monitoring = sys.monitoring
    monitoring.use_tool_id(monitoring.PROFILER_ID, "sync-call-count")
    monitoring.register_callback(
        monitoring.PROFILER_ID, monitoring.events.CALL, count_call)
    rng = np.random.default_rng(17)
    reference = rng.normal(size=5000)
    source = np.zeros(5000)
    source[1000:] = reference[:-1000]

    monitoring.set_events(monitoring.PROFILER_ID, monitoring.events.CALL)
    try:
        result = estimate_offset(
            reference, source, hop_seconds=0.02,
            max_shift_seconds=100.0, min_overlap_seconds=1.0,
        )
    finally:
        monitoring.set_events(monitoring.PROFILER_ID, 0)
        monitoring.register_callback(monitoring.PROFILER_ID,
                                     monitoring.events.CALL, None)
        monitoring.free_tool_id(monitoring.PROFILER_ID)

    assert result is not None
    assert result.shift_seconds == pytest.approx(-20.0, abs=0.02)
    assert calls < 4000, (
        f"pisteytys teki {calls} funktiokutsua eli viiveet käytiin "
        "Python-silmukassa"
    )
