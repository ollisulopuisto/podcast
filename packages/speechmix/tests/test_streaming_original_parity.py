"""Streaming master parity, global decisions, state and cleanup contracts."""

import numpy as np
import pytest

from speechmix import chain, programme

RATE = 48000


def _audio(channels, frames):
    t = np.arange(frames) / RATE
    body = (np.sin(2 * np.pi * 137 * t) + 0.3 * np.sin(2 * np.pi * 911 * t))
    envelope = 0.015 + 0.025 * (np.sin(2 * np.pi * 1.3 * t) > 0)
    audio = np.tile(body * envelope, (channels, 1))
    if channels == 2:
        audio[1] *= 0.6
    for point in [0, 4095, 4096, 47999, 48000, frames - 1]:
        if 0 <= point < frames:
            audio[:, point] = 0.95
    return audio


@pytest.mark.parametrize("channels", [1, 2])
@pytest.mark.parametrize("target,budget", [(-16.0, 3.0), (-4.0, 0.1)])
@pytest.mark.parametrize("block", [4096, 65536])
def test_streaming_master_matches_reference_signal_and_global_result(
    channels, target, budget, block, tmp_path,
):
    audio = _audio(channels, RATE * 2 + 123)
    expected, baseline = programme.master(audio, RATE, target, budget_lu=budget)
    output, progress, reads = [], [], []

    def read(start, stop):
        reads.append(stop - start)
        return audio[:, start:stop]

    result = programme.master_stream(
        read, output.append, audio.shape[1], channels, RATE, target,
        budget_lu=budget, block_frames=block, scratch_dir=tmp_path,
        progress=progress.append,
    )
    actual = np.concatenate(output, axis=1)
    np.testing.assert_allclose(actual, expected, rtol=1e-10, atol=1e-10)
    assert actual.shape == audio.shape
    assert result.boost_db == baseline.boost_db
    assert result.reached == baseline.reached
    assert result.cost_lu == baseline.cost_lu
    assert result.lufs == pytest.approx(baseline.lufs, abs=1e-9)
    assert chain.true_peak(actual) == pytest.approx(chain.true_peak(expected), abs=1e-9)
    def crest(x):
        return np.max(np.abs(x)) / np.sqrt(np.mean(x * x))
    assert crest(actual) == pytest.approx(crest(expected), abs=1e-9)
    if channels == 2:
        mask = np.abs(audio[1] - audio[0] * 0.6) < 1e-12
        np.testing.assert_allclose(actual[1, mask], actual[0, mask] * 0.6,
                                   atol=1e-10, rtol=1e-10)
    assert progress == sorted(progress)
    assert progress[-1] == 1.0
    assert max(reads) <= max(block, chain._TRUE_PEAK_CHUNK + 2 * chain._TRUE_PEAK_PAD)
    assert not list(tmp_path.iterdir())
