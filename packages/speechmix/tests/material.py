"""Synthetic material shaped by what the real recordings taught us.

Two properties are load-bearing and easy to get wrong in a fixture:

* **The bursts must vary in level.**  Thresholds in the chain are absolute and
  are applied after normalisation, so a signal whose every burst is equally
  loud sits entirely below all of them -- the test then passes while measuring
  nothing.  In speech it is the loud passages that clear the threshold.
* **Two microphones hear each other.**  A single clean track cannot show any of
  the findings that matter: the bleed, the mask disagreement, or the programme
  sum.
"""

import numpy as np
from scipy import signal as sp_signal

RATE = 48000


def _voiced_burst(n, rate, f0, seed):
    t = np.arange(n) / rate
    rng = np.random.default_rng(seed)
    # A few harmonics, a little jitter, and breath noise: enough structure for
    # the band splits and the pitch-period argument to mean something.
    harmonics = sum(np.sin(2 * np.pi * f0 * k * t + rng.uniform(0, 6.28)) / k for k in range(1, 12))
    breath = sp_signal.sosfilt(
        sp_signal.butter(2, 3000, "hp", fs=rate, output="sos"), rng.normal(0, 1, n)
    )
    body = harmonics / np.max(np.abs(harmonics)) + 0.05 * breath
    return body * np.hanning(n)


def speech_like(seconds, rate=RATE, f0=120.0, seed=0, gaps=True, floor_db=-60.0):
    """Bursts of voiced material at deliberately uneven levels, with pauses."""
    rng = np.random.default_rng(seed)
    n = int(seconds * rate)
    out = rng.normal(0, 10 ** (floor_db / 20), n)
    cursor = int(0.2 * rate)
    k = 0
    # Sentence-scale emphasis: the loud passages are the ones that clear a
    # threshold, so the spread here is the whole point of the fixture.
    levels_db = [-6.0, -14.0, -3.0, -20.0, -9.0, -11.0, -4.0, -17.0]
    while cursor < n:
        length = int(rng.uniform(0.35, 0.9) * rate)
        if cursor + length >= n:
            break
        level = 10 ** (levels_db[k % len(levels_db)] / 20)
        out[cursor : cursor + length] += _voiced_burst(length, rate, f0, seed + k) * level
        cursor += length + int(rng.uniform(0.15, 0.5) * rate if gaps else 0.02 * rate)
        k += 1
    return out


def bleed_path(rate, delay_ms=3.0, level_db=-16.0, taps=512):
    """A plausible leakage path: a few milliseconds of air, dulled by the room."""
    h = np.zeros(taps)
    d = int(delay_ms * rate / 1000.0)
    h[d] = 1.0
    h[d + 6] = 0.35
    h[d + 41] = 0.12
    h = sp_signal.sosfilt(sp_signal.butter(2, 6000, "lp", fs=rate, output="sos"), h)
    h *= 10 ** (level_db / 20) / np.max(np.abs(h))
    return h
