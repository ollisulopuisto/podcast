"""IIR filtering that does not stall on digital silence.

scipy's ``sosfilt`` leaves its state in denormal numbers when the input goes
silent after sound, and on CPUs that handle denormals slowly (the x86 server this
was measured on: ~25x) every operation on them costs that for the rest of the
silence. Not all CPUs do (GitHub's Linux runner showed none). A stem of a speaker who is not talking is mostly exact zeros (kuulas
mutes what is not wanted), so the band split, the de-esser and the click
detector paid that on most of their samples. ``speechmix.iir`` is the same
filter in blocks that clears a stage's state once it is far below anything that
can reach an output.
"""

from __future__ import annotations

import time

import numpy as np
import pytest
from scipy import signal as sig

from speechmix import iir

RATE = 48000


def _sos(edge=3000.0, order=4):
    return sig.butter(order, edge / (RATE / 2), output="sos")


def _stem(dtype=np.float64, seconds=3.0, seed=2):
    """Noise, then silence, then a burst: the shape of a stem."""
    rng = np.random.default_rng(seed)
    n = int(seconds * RATE)
    x = np.zeros((2, n))
    x[:, : n // 4] = rng.normal(0, 0.1, (2, n // 4))
    x[:, 3 * n // 4 :] = rng.normal(0, 0.1, (2, n - 3 * n // 4))
    return x.astype(dtype)


def _noise(dtype, n=60000, seed=5):
    """Sound all the way: no tail for the filter to clear."""
    return np.random.default_rng(seed).normal(0, 0.1, (2, n)).astype(dtype)


@pytest.mark.parametrize("dtype", [np.float32, np.float64])
@pytest.mark.parametrize("block", [1, 7, 4096, 10**9])
def test_without_a_state_the_result_is_scipys_to_the_last_bit(dtype, block, monkeypatch):
    monkeypatch.setattr(iir, "BLOCK", block)
    monkeypatch.setattr(iir, "MIN_ZEROS", 0)  # dense noise would otherwise skip the blocks
    x = _noise(dtype)
    sos = _sos()
    got = iir.sosfilt(sos, x)
    want = sig.sosfilt(sos, x, axis=-1)
    assert got.dtype == want.dtype and np.array_equal(got, want)


@pytest.mark.parametrize("dtype", [np.float32, np.float64])
def test_with_a_state_it_continues_exactly_like_scipy(dtype, monkeypatch):
    monkeypatch.setattr(iir, "BLOCK", 3000)
    monkeypatch.setattr(iir, "MIN_ZEROS", 0)
    x = _noise(dtype, 50000)
    sos = _sos(order=6)
    zi = np.zeros((sos.shape[0], 2, 2))
    got_a, zi_got = iir.sosfilt(sos, x[:, :20000], zi=zi.copy())
    got_b, zi_got = iir.sosfilt(sos, x[:, 20000:], zi=zi_got)
    want_a, zi_want = sig.sosfilt(sos, x[:, :20000], axis=-1, zi=zi.copy())
    want_b, zi_want = sig.sosfilt(sos, x[:, 20000:], axis=-1, zi=zi_want)
    assert np.array_equal(np.concatenate([got_a, got_b], axis=-1),
                          np.concatenate([want_a, want_b], axis=-1))
    assert np.array_equal(zi_got, zi_want)


def test_through_silence_everything_audible_is_scipys_and_the_rest_is_nothing():
    """After the sound stops the output of the old filter is a decaying tail
    down to 1e-300; the new one clears the state at 1e-250. Wherever the old
    output is above 1e-150 the two are the same number, and elsewhere the new
    one is below 1e-150 too. (Between 1e-250 and 1e-170 the two differ by up to
    3e-14 relative: the rounding of the recursion depends on the state it
    started from, and that memory only goes when the signal returns. 130 orders
    of magnitude below anything that reaches a sample.)"""
    x = _stem(seconds=8.0)  # 4 s of silence: the 120 Hz tail needs ~1.8 s to fall below 1e-200
    sos = _sos(edge=120.0)  # slow: the tail lasts the longest
    got = iir.sosfilt(sos, x)
    want = sig.sosfilt(sos, x, axis=-1)
    loud = np.abs(want) > 1e-150
    assert np.array_equal(got[loud], want[loud])
    assert np.abs(got[~loud]).max() < 1e-150
    assert loud.sum() > 100000 and (~loud).sum() > 20000  # both kinds were exercised


def test_the_state_is_exactly_zero_after_long_silence():
    x = np.zeros((1, 8 * RATE))
    x[:, 0] = 1.0
    sos = _sos(edge=120.0)
    _, zi = iir.sosfilt(sos, x, zi=np.zeros((sos.shape[0], 1, 2)))
    assert not zi.any()


def test_digital_silence_does_not_make_the_filter_slower():
    sos = _sos(edge=120.0)
    noise = np.random.default_rng(3).normal(0, 0.1, (1, 6 * RATE))
    silent = np.zeros((1, 6 * RATE))
    silent[:, 0] = 1.0

    def best(fn, x):
        runs = []
        for _ in range(3):
            started = time.perf_counter()
            fn(sos, x)
            runs.append(time.perf_counter() - started)
        return min(runs)

    # Not asserted: that scipy's own filter is slow on this input. It is on the
    # x86 server this was measured on (6 s: 24 ms on noise, 160-560 ms on zeros),
    # but not on GitHub's Linux runner (2.7 ms against 2.0 ms) or, as far as the
    # tests there showed, on Apple's cores: whether denormals cost anything is a
    # property of the CPU. What holds everywhere is that ours does not.
    assert best(iir.sosfilt, silent) < 3 * best(iir.sosfilt, noise)


@pytest.mark.parametrize("dtype", [np.float32, np.float64])
@pytest.mark.parametrize("shape", [(1, 30000), (2, 5000), (30000,)])
def test_sosfiltfilt_is_scipys_to_the_last_bit(dtype, shape):
    x = np.random.default_rng(4).normal(0, 0.1, shape).astype(dtype)
    sos = _sos(edge=2000.0, order=4)
    got = iir.sosfiltfilt(sos, x)
    want = sig.sosfiltfilt(sos, x)
    assert got.dtype == want.dtype and got.shape == want.shape and np.array_equal(got, want)


def test_sosfiltfilt_through_silence_agrees_where_there_is_sound():
    x = _stem(seconds=8.0)[:1]
    sos = _sos(edge=1000.0)  # the declick's low band; a 150 Hz one is ill-conditioned and drifts to 2e-9
    got, want = iir.sosfiltfilt(sos, x), sig.sosfiltfilt(sos, x)
    loud = np.abs(want) > 1e-150
    assert np.array_equal(got[loud], want[loud]) and np.abs(got[~loud]).max() < 1e-150


def test_a_signal_too_short_for_the_padding_fails_like_scipy():
    sos = _sos()
    with pytest.raises(ValueError):
        sig.sosfiltfilt(sos, np.zeros(10))
    with pytest.raises(ValueError):
        iir.sosfiltfilt(sos, np.zeros(10))


def _count_scipy_calls(monkeypatch):
    calls = []
    real = sig.sosfilt

    def counting(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(sig, "sosfilt", counting)
    return calls


def test_sound_all_the_way_is_one_scipy_call_not_blocks(monkeypatch):
    """Without a stretch of exact zeros nothing can reach the denormals, and
    the blocks only cost: 24-32 ms became 38-85 ms per minute of audio."""
    calls = _count_scipy_calls(monkeypatch)
    iir.sosfilt(_sos(), _noise(np.float32, 5 * iir.BLOCK))
    assert len(calls) == 1


def test_a_stretch_of_zeros_is_filtered_in_blocks(monkeypatch):
    calls = _count_scipy_calls(monkeypatch)
    x = _noise(np.float64, 5 * iir.BLOCK)
    x[:, 1000:1000 + iir.MIN_ZEROS] = 0.0
    iir.sosfilt(_sos(), x)
    assert len(calls) == 5


def test_zeros_a_little_below_the_limit_stay_one_call(monkeypatch):
    calls = _count_scipy_calls(monkeypatch)
    x = _noise(np.float64, 5 * iir.BLOCK)
    x[:, 1000:1000 + (iir.MIN_ZEROS - 2) // 2] = 0.0   # two channels: two fewer than MIN_ZEROS in all
    iir.sosfilt(_sos(), x)
    assert len(calls) == 1


def test_a_state_that_arrives_denormal_is_cleared_before_use():
    """The state a previous piece left behind may already be at the limit
    cycle; filtering with it would be slow from the first sample."""
    sos = _sos(edge=120.0)
    zi = np.full((sos.shape[0], 1, 2), 3e-322)
    _, zf = iir.sosfilt(sos, np.zeros((1, 100)), zi=zi)
    assert not zf.any()
