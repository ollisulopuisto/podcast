"""Heavy acceptance: genuine full-rate active-limiter runs, not timing mocks.

These run in the existing standard CI speechmix suite. Allow several minutes
and at least 10.4 GB free scratch disk for the 90-minute fixture. Failure means
an acceptance gate remains open; a short fixture is not a substitute.
"""

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from speechmix import chain, programme


@pytest.mark.parametrize("minutes", [10, 30, 90])
def test_active_mastering_memory_over_long_programmes(minutes):
    script = Path(__file__).resolve().parents[1] / "benchmarks/master_stream_memory.py"
    # Isolate allocator/JIT baselines across lengths. The API itself checks free
    # scratch space before work and raises rather than silently skipping.
    completed = subprocess.run(
        [sys.executable, str(script), str(minutes)],
        capture_output=True, text=True, timeout=1200, check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    record = json.loads(completed.stdout.strip().splitlines()[-1])
    print("streaming acceptance: " + json.dumps(record), flush=True)
    assert record["rate"] == 48000
    assert record["channels"] == 2
    assert record["written_frames"] == minutes * 60 * 48000
    assert record["scratch_left"] == []
    # A generous working-window ceiling, not a fitted exact allocator result.
    # Full-duration float64 stereo at 90 minutes would exceed 4 GB.
    assert record["incremental_peak_rss"] < 256 * 1024 * 1024, record
    assert record["scratch_peak_bytes"] <= programme.master_scratch_bytes(
        record["frames"]), record
    # This transient-heavy fixture spends the limiter budget. It must report
    # the unmet global target honestly, rather than silently claim -16 LUFS.
    assert record["reached"] is False
    assert record["cost_lu"] > 0
    assert record["sample_peak"] <= 10 ** (programme.PROGRAM_PEAK_DB / 20) + 1e-5


def test_short_streaming_matches_native_mlx_reference_when_available(tmp_path):
    if not chain._gpu_peak_envelope_available():
        pytest.skip("native MLX envelope unavailable; GPU parity remains unverified")
    calls = []
    original = chain._envelope_chunks_gpu

    def observed(audio):
        calls.append(True)
        yield from original(audio)

    rate = 48000
    time = np.arange(rate * 3 + 123) / rate
    mono = 0.03 * np.sin(2 * np.pi * 137 * time)
    mono[::4000] = 0.99
    audio = np.stack([mono, mono * 0.6])
    # Patch only observation of the real GPU kernel, never replace its output.
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(chain, "_envelope_chunks_gpu", observed)
        expected, info = programme.master(audio, rate, -16)
    assert calls, "reference did not actually exercise the native GPU envelope"
    output = []
    result = programme.master_stream(
        lambda a, b: audio[:, a:b], output.append,
        audio.shape[1], 2, rate, -16, block_frames=4096, scratch_dir=tmp_path,
    )
    actual = np.concatenate(output, axis=1)
    # MLX computes float32 envelopes while CPU streaming uses float64. This
    # explicit float32-scale tolerance is separate from CPU 1e-10 parity.
    np.testing.assert_allclose(actual, expected, atol=1e-6, rtol=1e-6)
    assert result.lufs == pytest.approx(info.lufs, abs=1e-5)
    assert result.boost_db == info.boost_db
    assert result.cost_lu == info.cost_lu
    assert result.reached == info.reached
