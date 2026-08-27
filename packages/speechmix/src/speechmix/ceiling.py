"""The ceiling is the programme's, not the stem's.

Each stem limited to -1.5 dBTP is not enough, because what plays is the
**sum**.  Two stems whose peaks are both pressed to the ceiling exceed full
scale whenever those peaks coincide -- in theory +4.5 dB, and measured on a
real episode **+4.51 dBFS, 49 971 samples over full scale in 4072 bursts,
200 a minute**, median 0.23 ms.  That is audible as intermittent crackle on
loud syllables, and it is what a host application draws in red.

The fix is **not** harder per-stem limiting -- then every stem pays six
decibels of crest for what some *other* file happens to do.  The limiter's gain
curve is computed from the **summed** stems and the identical curve is
multiplied into each one.  The sum then obeys the ceiling and the balance
between speakers cannot move, because every stem gets the same number.
Measured: +4.51 -> -1.51 dBFS at a cost of 0.50 LU.

The pass is idempotent by construction -- the curve is ``min(1, ceiling/peak)``,
so a sum already at the ceiling gets 1 everywhere -- which makes it safe to run
on every processing round.

Two more rules:

* The ceiling must be a look-ahead limiter, never a static attenuation.  A
  static cut scales the whole file by what its single loudest sample demands;
  measured, that turned -14.00 LUFS into -25.74, and it makes the balance
  between speakers depend on whose loudest transient was loudest, which is to
  say random.
* ``pedalboard.Limiter`` applies makeup gain -- it lifted -20 LUFS to -15.8 and
  peaks to zero.  Use a static attenuation that never raises, or a look-ahead
  limiter of your own, which is what this is.
"""

from dataclasses import dataclass
from typing import List, Sequence

import numpy as np

from . import dsp
from .errors import Misaligned

#: Where the programme peaks land.
DEFAULT_CEILING_DBFS = -1.5

#: The limiter sees this far ahead, so the gain is already down when the peak
#: arrives instead of clipping its leading edge.
LOOKAHEAD_MS = 5.0

#: How slowly the gain comes back.  Faster than this and loud passages pump.
RELEASE_MS = 120.0


@dataclass
class CeilingReport:
    peak_before_dbfs: float
    peak_after_dbfs: float
    samples_over_full_scale: int
    bursts_over_full_scale: int
    max_reduction_db: float

    def __str__(self):
        return (
            f"programme ceiling: sum peak {self.peak_before_dbfs:+.2f} -> "
            f"{self.peak_after_dbfs:+.2f} dBFS "
            f"({self.samples_over_full_scale} samples over full scale in "
            f"{self.bursts_over_full_scale} bursts before), "
            f"{self.max_reduction_db:.2f} dB of reduction at most"
        )


def _channel_peak(audio):
    arr = np.asarray(audio, dtype=np.float64)
    return np.max(np.abs(arr), axis=1) if arr.ndim == 2 else np.abs(arr)


def _check_aligned(stems: Sequence[np.ndarray]):
    """Summing files sample-by-sample is only correct when the stems line up.

    That is a checked fact here, not an assumption: mismatched stems are left
    alone rather than summed at the wrong offset.
    """
    if not stems:
        raise Misaligned("the programme ceiling was asked for with no stems")
    shapes = {np.asarray(s).shape for s in stems}
    if len(shapes) != 1:
        raise Misaligned(
            "stems do not line up sample-for-sample "
            f"(shapes {sorted(str(s) for s in shapes)}); summing them would put "
            "the ceiling on audio that never plays together, so they are left alone"
        )


def ceiling_curve(summed, rate, ceiling_dbfs=DEFAULT_CEILING_DBFS,
                  lookahead_ms=LOOKAHEAD_MS, release_ms=RELEASE_MS):
    """The look-ahead limiter's gain curve for an already-summed programme."""
    peak = _channel_peak(summed)
    lookahead = max(1, int(lookahead_ms * rate / 1000.0))
    peak_env = dsp.moving_peak(peak, lookahead)
    ceiling_lin = dsp.db_to_lin(ceiling_dbfs)
    curve = np.minimum(1.0, ceiling_lin / np.maximum(peak_env, dsp.EPS))
    # Slow the return to unity.  The reduction itself is already ahead of the
    # peak by the look-ahead window.
    curve_db = dsp.release_smooth(dsp.lin_to_db(curve), max(1, int(release_ms * rate / 1000.0)))
    return dsp.db_to_lin(np.minimum(curve_db, 0.0))


def programme_ceiling(
    stems: Sequence[np.ndarray],
    rate,
    ceiling_dbfs=DEFAULT_CEILING_DBFS,
    lookahead_ms=LOOKAHEAD_MS,
    release_ms=RELEASE_MS,
):
    """Apply one limiter curve, computed from the sum, to every stem.

    Args:
        stems: Stems that line up sample-for-sample.  Mono or stereo, but all
            the same shape.
        rate: Sample rate.
        ceiling_dbfs: Where the programme's peaks land.

    Returns:
        ``(stems_out, CeilingReport)``.

    Raises:
        Misaligned: If the stems do not line up.
    """
    _check_aligned(stems)
    arrays = [np.asarray(s, dtype=np.float64) for s in stems]
    summed = np.sum(arrays, axis=0)

    peak_before = _channel_peak(summed)
    over = peak_before > 1.0
    bursts = int(np.count_nonzero(np.diff(over.astype(np.int8)) == 1) + (1 if over.size and over[0] else 0))

    curve = ceiling_curve(summed, rate, ceiling_dbfs, lookahead_ms, release_ms)
    shaped: List[np.ndarray] = [
        s * (curve[:, None] if s.ndim == 2 else curve) for s in arrays
    ]
    after = np.sum(shaped, axis=0)

    report = CeilingReport(
        peak_before_dbfs=dsp.peak_dbfs(summed),
        peak_after_dbfs=dsp.peak_dbfs(after),
        samples_over_full_scale=int(np.count_nonzero(over)),
        bursts_over_full_scale=bursts,
        max_reduction_db=float(-dsp.lin_to_db(curve.min())) if curve.size else 0.0,
    )
    return shaped, report
