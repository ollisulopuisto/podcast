"""Fixtures for the measurement tests.  The material itself is in ``material.py``."""

import numpy as np
import pytest
from scipy import signal as sp_signal

from material import RATE, bleed_path, speech_like


@pytest.fixture
def rate():
    return RATE


@pytest.fixture
def two_mic_session(rate):
    """Two microphones, turn-taking with an overlap, each hearing the other.

    Returns a dict with the raw microphones, the isolated voices, and the true
    turn-taking gates, so a test can measure what a stage did to the leakage
    *and* what it did to the speaker's own voice.
    """
    seconds = 40
    n = seconds * rate
    a_voice = speech_like(seconds, rate, f0=118.0, seed=1)
    b_voice = speech_like(seconds, rate, f0=196.0, seed=2)

    gate_a = np.zeros(n, dtype=bool)
    gate_b = np.zeros(n, dtype=bool)
    gate_a[: 15 * rate] = True
    gate_b[15 * rate : 30 * rate] = True
    gate_a[30 * rate :] = True  # the last ten seconds overlap
    gate_b[30 * rate :] = True

    a_voice = a_voice * gate_a
    b_voice = b_voice * gate_b

    # Bleed levels from real material: hot enough to comb-filter the sum, quiet
    # enough that each microphone is still mostly its owner.  The estimate is
    # made from the *other* microphone, which carries some of this one's voice
    # in turn, so these two numbers bound how well any linear estimate can do.
    into_a = sp_signal.fftconvolve(b_voice, bleed_path(rate, level_db=-24.0))[:n]
    into_b = sp_signal.fftconvolve(a_voice, bleed_path(rate, delay_ms=3.4, level_db=-27.0))[:n]

    return {
        "rate": rate,
        "mic_a": a_voice + into_a,
        "mic_b": b_voice + into_b,
        "voice_a": a_voice,
        "voice_b": b_voice,
        "gate_a": gate_a,
        "gate_b": gate_b,
        "a_only": gate_a & ~gate_b,
        "b_only": gate_b & ~gate_a,
    }


@pytest.fixture
def varied_speech(rate):
    """Ten seconds of one speaker, bursts at uneven levels."""
    return speech_like(10, rate, f0=124.0, seed=5)
