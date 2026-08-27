"""The loudness target is the programme's, not one stem's.

Two microphones each normalised to -14 LUFS sum above it -- measured -12.2,
because the speakers overlap and the microphones hear each other.  So the sum
of the raw microphones is measured over a bounded window, the difference is
taken off every file, and the trim goes into the **target**, never into the
gain: the chain normalises to the target as its last act, so a trim added to
the gain is removed again exactly.  (Measured, with the trim in the gain: stems
landed on -14.1 instead of -15.8 and the reading looked correct.)

Applying -14 to a mono speech stem directly leaves about 14 dB of crest and
sounds crushed; the same figure as a programme target leaves 17.5.
"""

from dataclasses import dataclass
from typing import Mapping

import numpy as np
import pyloudnorm as pyln

from . import dsp

#: The sum is measured over a bounded window: a whole 77-minute episode does
#: not need to be metered twice to learn what two microphones do to each other.
DEFAULT_WINDOW_SEC = 600.0


@dataclass
class ProgrammeTarget:
    """The per-stem target, and where it came from."""

    target_lufs: float
    stem_target_lufs: float
    measured_sum_lufs: float
    trim_db: float

    def __str__(self):
        return (
            f"programme target {self.target_lufs:.1f} LUFS: the raw sum reads "
            f"{self.measured_sum_lufs:.2f}, so the trim is {self.trim_db:.2f} dB and "
            f"each stem is normalised to {self.stem_target_lufs:.2f} LUFS"
        )


def integrated_lufs(audio, rate):
    """Integrated loudness (ITU-R BS.1770), or NaN for material too short to meter."""
    arr = np.asarray(audio, dtype=np.float64)
    meter = pyln.Meter(rate)
    if arr.shape[0] < int(0.4 * rate):
        return float("nan")
    try:
        return float(meter.integrated_loudness(arr))
    except Exception:
        return float("nan")


def programme_target(
    stems: Mapping[str, np.ndarray],
    rate,
    target_lufs,
    window_sec=DEFAULT_WINDOW_SEC,
):
    """Work out the per-stem target so that the *sum* lands on ``target_lufs``.

    The stems are the **raw** microphones.  Each is notionally normalised to the
    target, their sum is measured over a bounded window, and the excess becomes
    a trim on the target -- not on the gain, which the final normalisation would
    remove again.
    """
    window = int(window_sec * rate)
    scaled = []
    for name, audio in stems.items():
        arr = dsp.as_mono(audio, name)[:window]
        stem_lufs = integrated_lufs(arr, rate)
        if np.isnan(stem_lufs):
            continue
        scaled.append(arr * dsp.db_to_lin(target_lufs - stem_lufs))
    if not scaled:
        return ProgrammeTarget(target_lufs, target_lufs, float("nan"), 0.0)

    length = max(s.size for s in scaled)
    summed = np.zeros(length)
    for s in scaled:
        summed[: s.size] += s

    measured = integrated_lufs(summed, rate)
    trim = 0.0 if np.isnan(measured) else target_lufs - measured
    return ProgrammeTarget(
        target_lufs=target_lufs,
        stem_target_lufs=target_lufs + trim,
        measured_sum_lufs=measured,
        trim_db=trim,
    )


def normalise(audio, rate, target_lufs, tolerance_lu=0.1, passes=3):
    """Normalise to ``target_lufs``.  This is the chain's last act.

    Returns ``(out, gain_db)``.  A stage that wants a level change of its own
    must put it in the target, not here: a gain applied before this is removed
    by it exactly.

    One pass does not land on the target.  Integrated loudness is **gated** --
    blocks below the relative and absolute thresholds are excluded -- so
    scaling the signal changes which blocks count, and the reading moves by
    less than the gain applied.  Measured here, one pass lands 0.15-0.3 dB
    short; measured on a real episode through the whole chain, where a limiter
    is also eating loudness, the first round was 1-2 dB short and the third was
    inside 0.3. So it settles rather than assuming, and stops as soon as it is
    inside ``tolerance_lu``.
    """
    arr = np.asarray(audio, dtype=np.float64)
    total_db = 0.0
    for _ in range(max(1, passes)):
        current = integrated_lufs(arr, rate)
        if np.isnan(current):
            return arr.copy() if total_db == 0.0 else arr, total_db
        step = target_lufs - current
        if abs(step) <= tolerance_lu:
            break
        arr = arr * dsp.db_to_lin(step)
        total_db += step
    return arr, total_db


def crest_db(audio, rate):
    """Peak minus loudness: how much room the transients still have.

    -14 LUFS on a mono speech stem leaves about 14 dB here and sounds crushed;
    the same figure as a programme target leaves 17.5.
    """
    loudness = integrated_lufs(audio, rate)
    return float(dsp.peak_dbfs(audio) - loudness)
