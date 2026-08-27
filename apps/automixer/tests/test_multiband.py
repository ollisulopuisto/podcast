import mlx.core as mx
import numpy as np
from src.automixer.domain.processor import MultibandCompressorProcessor


def test_multiband_summation():
    """Ensures that the 3-band crossover sums back to (roughly) the original signal when auto-gain is disabled."""
    sr = 44100
    duration = 1.0
    noise_np = np.random.normal(0, 0.1, int(duration * sr)).astype(np.float32)
    noise_mx = mx.array(noise_np)

    # We need a way to disable auto-gain.
    # Let's mock _apply_auto_dynamics to just return the input for this test.
    mb = MultibandCompressorProcessor(peak_enabled=False, lev_enabled=False)
    mb._apply_auto_dynamics = lambda sig, sr: sig

    processed = mb.process(noise_mx, sr)

    # Subtraction crossover should sum perfectly
    np.testing.assert_allclose(np.array(processed), noise_np, atol=1e-5)


def test_multiband_dynamics():
    """Verifies that multiband dynamics actually reduce gain on loud signals."""
    sr = 44100
    # A loud low-frequency tone (100Hz)
    t = np.linspace(0, 1, sr)
    tone = 0.8 * np.sin(2 * np.pi * 100 * t)
    signal = mx.array(tone.astype(np.float32))

    mb = MultibandCompressorProcessor(peak_enabled=True, lev_enabled=True)
    processed = mb.process(signal, sr)

    # Loud signal should be compressed (smaller peak)
    assert mx.max(mx.abs(processed)).item() < 0.8
