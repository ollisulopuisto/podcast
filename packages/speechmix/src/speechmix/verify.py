"""Checks that catch the silent failures, cheaply.

**The sample count must not change.**  The export references the processed file
with the same times as the original.  Check it in more than one place and
discard anything that deviates.

**Measure shift separately**, by cross-correlation, because length alone cannot
detect a plug-in that reports its latency wrongly -- and keep that correlation
an FFT.  ``np.correlate(..., "full")`` is O(n^2) and took 132 s on a 20-minute
file, longer than the plug-in itself.
"""

import numpy as np
from scipy.fft import irfft, next_fast_len, rfft

from .errors import LengthChanged

#: A plug-in's latency is at most a few thousand samples.  Searching further
#: only buys false positives from the material's own periodicity.
DEFAULT_MAX_SHIFT = 96000


def assert_same_length(before, after, stage="stage"):
    """Raise if a stage changed the sample count."""
    n_before = np.asarray(before).shape[0]
    n_after = np.asarray(after).shape[0]
    if n_before != n_after:
        raise LengthChanged(
            f"{stage} changed the sample count: {n_before} -> {n_after} "
            f"({n_after - n_before:+d} samples). The export references this file "
            "with the same times as the original, so every edit after this point "
            "would move."
        )
    return after


def measure_shift(reference, processed, max_shift=DEFAULT_MAX_SHIFT):
    """Samples ``processed`` is delayed relative to ``reference`` (positive = later).

    By FFT, always.  A 20-minute file through ``np.correlate(..., "full")``
    took 132 s -- longer than the plug-in whose latency it was checking.
    """
    a = np.asarray(reference, dtype=np.float64).ravel()
    b = np.asarray(processed, dtype=np.float64).ravel()
    n = min(a.size, b.size)
    if n == 0:
        return 0
    a, b = a[:n] - a[:n].mean(), b[:n] - b[:n].mean()
    nfft = next_fast_len(n + max_shift)
    corr = irfft(np.conj(rfft(a, nfft)) * rfft(b, nfft), nfft)
    window = min(max_shift, nfft // 2)
    forward = corr[:window]
    backward = corr[-window:]
    best_forward = int(np.argmax(forward))
    best_backward = int(np.argmax(backward))
    if forward[best_forward] >= backward[best_backward]:
        return best_forward
    return -(window - best_backward)


def assert_no_shift(reference, processed, stage="stage", tolerance=0):
    """Raise if a stage moved the audio in time."""
    shift = measure_shift(reference, processed)
    if abs(shift) > tolerance:
        raise LengthChanged(
            f"{stage} shifted the audio by {shift:+d} samples with the length "
            "unchanged -- a plug-in reporting its latency wrongly looks exactly "
            "like this, and length alone cannot see it."
        )
    return shift
