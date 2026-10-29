"""Backend selection and bounded windows are mastering contracts."""

import numpy as np
import pytest

from speechmix import chain, programme


def test_automatic_envelope_workers_are_bounded_but_override_is_respected(monkeypatch):
    monkeypatch.setattr(chain, "worker_count", lambda requested=None: requested or 32)
    monkeypatch.delenv("SPEECHMIX_ENVELOPE_THREADS", raising=False)
    assert chain._envelope_threads() <= 4
    monkeypatch.setenv("SPEECHMIX_ENVELOPE_THREADS", "12")
    assert chain._envelope_threads() == 12


def test_streaming_uses_selected_gpu_kernel_with_bounded_reader(monkeypatch, tmp_path):
    rate = 48000
    frames = rate * 3 + 123
    time = np.arange(frames) / rate
    mono = 0.03 * np.sin(2 * np.pi * 137 * time)
    mono[::4000] = 0.99
    audio = np.stack([mono, mono * 0.6])
    calls = []

    def gpu(rows):
        calls.append(rows.shape)
        # Deterministic fake GPU rounding distinguishes it from the CPU path.
        for begin in range(0, rows.shape[1], chain._TRUE_PEAK_CHUNK):
            start, stop, piece = chain._envelope_piece(rows, begin, rows.shape[1])
            yield start, stop, piece.astype(np.float32).astype(np.float64)

    monkeypatch.setattr(chain, "_gpu_peak_envelope_available", lambda: True)
    monkeypatch.setattr(chain, "_envelope_chunks_gpu", gpu)
    expected, baseline = programme.master(audio, rate, -16)
    calls.clear()
    reads, output = [], []

    def read(start, stop):
        reads.append(stop - start)
        return audio[:, start:stop]

    result = programme.master_stream(
        read, output.append, frames, 2, rate, -16,
        block_frames=4096, scratch_dir=tmp_path,
    )
    assert calls, "streaming bypassed the selected GPU kernel"
    assert max(reads) <= chain._TRUE_PEAK_CHUNK + 2 * chain._TRUE_PEAK_PAD
    np.testing.assert_allclose(np.concatenate(output, axis=1), expected,
                               rtol=1e-10, atol=1e-10)
    assert result.boost_db == baseline.boost_db
    assert result.cost_lu == baseline.cost_lu
    assert result.lufs == pytest.approx(baseline.lufs, abs=1e-9)


def test_native_gpu_streaming_has_exact_parity_across_envelope_windows(tmp_path):
    if not chain._gpu_peak_envelope_available():
        pytest.skip("native MLX envelope unavailable")
    rate = 48000
    frames = chain._GPU_CHUNK * 3 + 123
    time = np.arange(frames) / rate
    mono = 0.03 * np.sin(2 * np.pi * 137 * time)
    mono[::4000] = 0.99
    audio = np.stack([mono, mono * 0.6])
    expected, baseline = programme.master(audio, rate, -16)
    output = []
    result = programme.master_stream(
        lambda a, b: audio[:, a:b], output.append, frames, 2, rate, -16,
        block_frames=4096, scratch_dir=tmp_path,
    )
    np.testing.assert_allclose(np.concatenate(output, axis=1), expected,
                               rtol=1e-10, atol=1e-10)
    assert result.lufs == pytest.approx(baseline.lufs, abs=1e-9)
    assert result.boost_db == baseline.boost_db
    assert result.cost_lu == baseline.cost_lu
    assert result.reached == baseline.reached
