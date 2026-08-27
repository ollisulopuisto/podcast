import pytest
import mlx.core as mx
import numpy as np
import soundfile as sf
from automixer.domain.processor import LimiterProcessor, GainProcessor
from automixer.domain.track import Track


def test_limiter_brickwall():
    sr = 1000
    duration = 1
    # Signal with a huge peak at 2.0
    sig_np = np.ones((duration * sr, 1), dtype=np.float32) * 0.5
    sig_np[500, 0] = 2.0
    signal = mx.array(sig_np)

    limiter = LimiterProcessor(threshold_db=0.0)  # 1.0 peak
    processed = limiter.process(signal, sr)

    # Peak should be exactly 1.0 (or very close)
    max_peak = mx.max(mx.abs(processed)).item()
    assert max_peak <= 1.0001
    # Rest of the signal should still be around 0.5 (or less due to release)
    # The first sample should definitely be 0.5
    assert processed[0, 0].item() == pytest.approx(0.5, rel=1e-2)


def test_gain_processor():
    signal = mx.ones((100, 1))
    gain = GainProcessor(gain_db=6.0)  # ~2x
    processed = gain.process(signal, 100)
    assert processed[0, 0].item() == pytest.approx(2.0, rel=1e-2)


def test_track_loudness_analysis(tmp_path):
    # Create a mock wav file
    sr = 44100
    duration = 2
    # Sine wave at 0.1 peak
    t = np.linspace(0, duration, sr * duration)
    data = 0.1 * np.sin(2 * np.pi * 440 * t)

    wav_path = tmp_path / "test.wav"
    sf.write(wav_path, data, sr)

    track = Track("test", str(wav_path))
    track.load()

    assert track.loudness is not None
    # A sine wave at 0.1 peak is roughly -23 LUFS
    assert -30 < track.loudness < -10
