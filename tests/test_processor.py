import pytest
import mlx.core as mx
import numpy as np
from src.automixer.domain.processor import DuckingProcessor

def test_ducking():
    sr = 1000
    duration = 5
    n_samples = duration * sr
    
    # Music: constant signal (1.0)
    music = mx.ones((n_samples,))
    
    # Speech: burst of 1.0 at 2s-3s
    speech = mx.zeros((n_samples,))
    speech[2*sr:3*sr] = 1.0
    
    ducker = DuckingProcessor(trigger_signal=speech, threshold_db=-10, ratio=10.0)
    ducked_music = ducker.process(music, sr)
    
    # At 2.5s, it should be ducked significantly
    ducked_val = ducked_music[int(2.5 * sr)].item()
    assert ducked_val < 0.5
    
    # At 0.5s, it should be 1.0 (no speech)
    initial_val = ducked_music[int(0.5 * sr)].item()
    assert initial_val == pytest.approx(1.0, rel=1e-3)
    
    # At 4.5s, it should recover to ~1.0
    recovered_val = ducked_music[int(4.5 * sr)].item()
    assert recovered_val > 0.9
