"""De-bleeding: subtract the leakage path, do not gate it.

The same voice arriving in two microphones a few milliseconds apart is a comb
filter.  That is what a summed pair sounds like when it sounds metallic.

Ducking cannot reach it.  Measured on real material: the masks fired correctly
and closed the microphone on 64 % of the frames where only the other person
spoke, and **infinite** attenuation still moved the ripple only from 6.22 dB to
6.01 -- because the gaps fall on turn-taking boundaries where the bleed is
loudest, and overlapping speech needs both microphones open anyway.

Bleed is linear, so it can be estimated and subtracted.  This module estimates
the leakage path as a least-squares FIR (2048 taps, solved from the Toeplitz
structure of the autocorrelation) over the passages where only the source
speaks, and subtracts it everywhere.  Measured: coherence 0.1069 -> 0.0098,
with the target's own speech preserved at r = 0.9993.

Two rules travel with it:

* It must run on the **raw** audio, *before* any generative restoration
  plug-in.  Such a plug-in does not preserve the linear relation between
  tracks, and after it no filter can remove the bleed.
* It measures its own output.  A filter that eats the target's own speech is
  refused with a stated reason, because that mistake is only audible after the
  export.
"""

from dataclasses import dataclass

import numpy as np
from scipy import signal as sp_signal
from scipy.fft import next_fast_len, irfft, rfft
from scipy.linalg import solve_toeplitz

from . import dsp
from .errors import Refused

#: 2048 taps at 48 kHz is 43 ms of leakage path -- far longer than any
#: microphone spacing in a room, with room for the first reflections.
DEFAULT_TAPS = 2048

#: The target's own speech must survive.  Measured on a good estimate: 0.9993.
MIN_PRESERVATION = 0.99

#: Ridge on the autocorrelation, so a near-silent source cannot produce a
#: filter with enormous gain.
RIDGE = 1e-6


@dataclass
class DebleedReport:
    """What the de-bleed did, measured on its own output."""

    applied: bool
    coherence_before: float
    coherence_after: float
    preservation: float
    bleed_removed_db: float
    taps: int
    reason: str = ""

    def __str__(self):
        if not self.applied:
            return f"de-bleed: refused ({self.reason})"
        return (
            f"de-bleed: coherence {self.coherence_before:.4f} -> {self.coherence_after:.4f}, "
            f"{self.bleed_removed_db:.1f} dB of leakage removed, "
            f"own speech preserved at r = {self.preservation:.4f}"
        )


def _fade_mask(mask, rate, fade_ms=20.0):
    """A binary mask with its edges softened.

    Multiplying by a hard mask puts a step at every boundary, and the estimator
    would then fit those steps as if they were signal.
    """
    fade = max(1, int(fade_ms * rate / 1000.0))
    window = np.hanning(2 * fade)
    kernel = window[:fade] / window[:fade].sum()
    return np.convolve(mask.astype(np.float64), kernel, mode="same")


def _correlate(a, b, taps):
    """r[k] = sum_n a[n] b[n + k] for k in [0, taps), by FFT.

    ``np.correlate(..., "full")`` is O(n^2) and took 132 s on a 20-minute file,
    longer than the plug-in it was checking.  Every correlation in this package
    is an FFT.
    """
    nfft = next_fast_len(a.size + taps)
    fa = rfft(a, nfft)
    fb = rfft(b, nfft)
    return irfft(np.conj(fa) * fb, nfft)[:taps]


def _mean_coherence(a, b, rate, low_hz=100.0, high_hz=8000.0):
    nperseg = min(2048, max(256, a.size // 8))
    freqs, coh = sp_signal.coherence(a, b, fs=rate, nperseg=nperseg)
    band = (freqs >= low_hz) & (freqs <= high_hz)
    if not band.any():
        return float("nan")
    return float(np.mean(coh[band]))


def estimate_bleed_filter(target, source, rate, source_only_mask, taps=DEFAULT_TAPS):
    """Least-squares FIR from ``source`` into ``target``.

    Estimated only over the passages where the source speaks alone: everywhere
    else the target's own voice would be fitted as if it were leakage.
    """
    x = dsp.as_mono(target, "de-bleed target")
    y = dsp.as_mono(source, "de-bleed source")
    if x.size != y.size:
        raise ValueError(
            f"de-bleed needs stems that line up: target {x.size} samples, source {y.size}"
        )
    weights = _fade_mask(np.asarray(source_only_mask, dtype=bool), rate)
    xm, ym = x * weights, y * weights

    r_yy = _correlate(ym, ym, taps)
    r_xy = _correlate(ym, xm, taps)
    if r_yy[0] <= dsp.EPS:
        raise Refused(
            "the source is silent in every frame where it was supposed to be "
            "speaking alone -- the mask is empty, not the leakage"
        )
    r_yy = r_yy.copy()
    r_yy[0] *= 1.0 + RIDGE
    return solve_toeplitz((r_yy, r_yy), r_xy)


def debleed(
    target,
    source,
    rate,
    source_only_mask,
    target_only_mask=None,
    taps=DEFAULT_TAPS,
    min_preservation=MIN_PRESERVATION,
):
    """Subtract the source's leakage from the target microphone.

    Args:
        target: The microphone to clean (mono, raw).
        source: The microphone whose voice is leaking into it (mono, raw).
        rate: Sample rate.
        source_only_mask: Boolean per-sample mask of the passages where only
            the source speaks.  This is where the filter is estimated.
        target_only_mask: Boolean mask of the passages where the target speaks
            and the source does not.  This is where preservation is measured,
            because that is where the output must come back unchanged -- where
            both speak, removing the leakage is *supposed* to change the
            signal, so measuring there would penalise a correct filter.
            Falls back to the loud frames of the target with a quiet source.
        taps: Length of the estimated leakage path.
        min_preservation: Refuse the filter below this correlation.

    Returns:
        ``(out, DebleedReport)``.  On refusal ``out`` is the untouched target
        and the report says why.  The sample count is always preserved.
    """
    x = dsp.as_mono(target, "de-bleed target")
    y = dsp.as_mono(source, "de-bleed source")
    mask = np.asarray(source_only_mask, dtype=bool)
    if not mask.any():
        raise Refused(
            "no frame has the source speaking alone, so there is nothing to "
            "estimate the leakage path from; de-bleeding was asked for and "
            "cannot be done -- this is an error, not a silence"
        )

    h = estimate_bleed_filter(x, y, rate, mask, taps=taps)
    estimated = sp_signal.fftconvolve(y, h)[: x.size]
    out = x - estimated

    if target_only_mask is None:
        x_env = dsp.moving_rms(x, max(1, int(0.050 * rate)))
        y_env = dsp.moving_rms(y, max(1, int(0.050 * rate)))
        target_only_mask = (x_env > np.median(x_env)) & (y_env < np.median(y_env))
    keep = np.asarray(target_only_mask, dtype=bool)
    if keep.sum() < taps:
        keep = np.ones_like(x, dtype=bool)

    a, b = x[keep], out[keep]
    denom = np.sqrt(np.sum((a - a.mean()) ** 2) * np.sum((b - b.mean()) ** 2))
    preservation = float(np.sum((a - a.mean()) * (b - b.mean()) / denom)) if denom > 0 else 0.0

    coh_before = _mean_coherence(x, y, rate)
    coh_after = _mean_coherence(out, y, rate)
    removed = float(
        dsp.lin_to_db(np.sqrt(np.mean(estimated**2)) + dsp.EPS)
        - dsp.lin_to_db(np.sqrt(np.mean(x**2)) + dsp.EPS)
    )

    if preservation < min_preservation:
        return x.copy(), DebleedReport(
            applied=False,
            coherence_before=coh_before,
            coherence_after=coh_after,
            preservation=preservation,
            bleed_removed_db=removed,
            taps=taps,
            reason=(
                f"the estimated filter eats the target's own speech "
                f"(r = {preservation:.4f}, needs {min_preservation:.4f}); a bad "
                "estimate is worse than the bleed and is only audible after the export"
            ),
        )

    return out, DebleedReport(
        applied=True,
        coherence_before=coh_before,
        coherence_after=coh_after,
        preservation=preservation,
        bleed_removed_db=removed,
        taps=taps,
    )
