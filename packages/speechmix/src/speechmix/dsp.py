"""Level and envelope helpers for the programme-level passes.

Nothing here knows about files, timelines or hosts: everything takes and
returns float arrays at a given sample rate.  Filtering and band splitting are
deliberately absent -- ``chain`` owns those, and a second copy here would give
the package two of each.
"""

import numpy as np
from scipy import signal as sp_signal
from scipy.ndimage import maximum_filter1d, uniform_filter1d

from .errors import NotMono

EPS = 1e-12


def as_mono(audio, name="track"):
    """Return ``audio`` as a 1-D float64 array, refusing anything multi-channel.

    A microphone is always mono out.  Two channels break the arithmetic in
    three places silently (de-bleeding reads only the first channel, the
    programme ceiling broadcasts stems of differing channel counts, and panning
    is a mono-source idea), so this refuses rather than picking a channel.
    """
    arr = np.asarray(audio)
    if arr.ndim == 2 and arr.shape[1] == 1:
        arr = arr[:, 0]
    if arr.ndim != 1:
        raise NotMono(
            f"{name}: expected a mono microphone track, got shape {arr.shape}"
        )
    return arr.astype(np.float64, copy=False)


def db_to_lin(db):
    return 10.0 ** (np.asarray(db, dtype=np.float64) / 20.0)


def lin_to_db(lin):
    return 20.0 * np.log10(np.maximum(np.asarray(lin, dtype=np.float64), EPS))


def peak_dbfs(audio):
    """Sample peak in dBFS, across channels for a 2-D array."""
    arr = np.asarray(audio, dtype=np.float64)
    if arr.size == 0:
        return -np.inf
    return float(lin_to_db(np.max(np.abs(arr))))


def moving_rms(audio, window_samples):
    """RMS over a centred rectangular window, vectorised.

    Used as the level detector in front of every dynamics stage.  The window
    length *is* the attack time: it must be longer than a pitch period or the
    gain follows the waveform instead of the level, which is harmonic
    distortion by definition (see ``dynamics.PEAK_ATTACK_MS``).
    """
    window_samples = max(1, int(window_samples))
    squared = np.asarray(audio, dtype=np.float64) ** 2
    mean_square = uniform_filter1d(squared, size=window_samples, mode="nearest")
    # The accumulator can land a hair below zero on near-silence; sqrt of that is
    # a NaN that then spreads through every dB conversion downstream.
    return np.sqrt(np.maximum(mean_square, 0.0))


def moving_peak(audio, window_samples):
    """Sliding maximum of |audio| over ``window_samples``."""
    window_samples = max(1, int(window_samples))
    return maximum_filter1d(np.abs(np.asarray(audio, dtype=np.float64)), size=window_samples)


def one_pole(x, tau_samples):
    """One-pole low-pass, implemented with ``lfilter`` so it stays vectorised.

    ``tau_samples`` is the time constant in samples.  A Python loop over a
    77-minute file is not an option, so every smoother in this package is
    either an IIR through ``lfilter`` or a filter from ``scipy.ndimage``.
    """
    tau_samples = max(1.0, float(tau_samples))
    a = float(np.exp(-1.0 / tau_samples))
    return sp_signal.lfilter([1.0 - a], [1.0, -a], np.asarray(x, dtype=np.float64))


#: A release time is quoted as the time to recover this much gain.  Ten
#: decibels is the whole working range of the bounded stages twice over.
RELEASE_RANGE_DB = 10.0


def release_smooth(gain_db, release_samples, release_range_db=RELEASE_RANGE_DB):
    """Slow the *return* to unity without slowing the reduction.

    ``gain_db`` is a gain-reduction curve (<= 0 dB) straight off the level
    detector, whose window already sets the attack.  The release is linear in
    dB: the gain may climb back towards unity by ``release_range_db`` per
    ``release_samples`` and no faster.

    ``y[i] = min(gr[i], y[i-1] + slope)`` is a recursion numpy cannot vectorise,
    but substituting ``z[i] = y[i] - slope*i`` turns it into a running minimum,
    which it does in one pass.  This matters: a one-pole low-pass looks like a
    release and is not one -- it never charges fully for an event shorter than
    its own time constant, so a sibilant would duck the gain by a decibel and
    let go immediately instead of holding a sentence down.
    """
    gain_db = np.asarray(gain_db, dtype=np.float64)
    if gain_db.size == 0:
        return gain_db
    slope = release_range_db / max(1.0, float(release_samples))
    ramp = slope * np.arange(gain_db.size)
    return np.minimum.accumulate(gain_db - ramp) + ramp
