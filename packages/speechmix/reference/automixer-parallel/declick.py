"""De-clicker: removes lip smacks, keyed on how often the artefact occurs.

The finding this module exists for (measured on real two-microphone podcast
material):

    A de-clicker calibrated by "local reference x N" corrected **2 % of all
    samples, 550-640 corrections per second**, and altered the signal -10 dB
    relative to itself.  It passed every test, because the tests asked whether
    a planted click was removed and never how many were found.

So the threshold here is not a multiplier -- it is a **rate**.  Lip smacks are
a few a minute; the detector is given a budget in clicks per minute and the
threshold is raised until the findings fit that budget.  There is a ceiling on
how far it may be raised, and if the findings still do not fit, nothing is
corrected: whatever the detector is seeing at that level is not a lip smack.
"""

from dataclasses import dataclass

import numpy as np

from . import dsp

#: Lip smacks are a few a minute.  This is the budget, not a hint.
DEFAULT_MAX_PER_MINUTE = 6.0

#: A click sits at least this far above the local high-frequency level.  Below
#: this the detector is looking at ordinary sibilance.
MIN_RATIO_DB = 18.0

#: The ceiling.  If the budget is still not met with the threshold this high,
#: the detector is not finding lip smacks and nothing is corrected.
MAX_RATIO_DB = 40.0

#: The other way the budget can fail to fit.  A population this far over the
#: budget is a different phenomenon -- vinyl crackle, a bad transfer, a noisy
#: preamp -- and thinning it down to a handful would correct an arbitrary few
#: of it.  Correct nothing instead, and say so.
REFUSE_FACTOR = 10.0

#: Clicks live above 4 kHz; plosives live below 1 kHz and must not be touched.
CLICK_BAND_HZ = 4000.0
PLOSIVE_BAND_HZ = 1000.0

#: A lip smack is short.  Anything longer is speech.
MAX_CLICK_MS = 10.0

#: How much louder the low band has to be than the high band, at the same
#: instant, for a transient to be a plosive rather than a smack.
PLOSIVE_DOMINANCE = 1.0


@dataclass
class DeclickReport:
    """What the de-clicker actually did -- every number measurable after the fact."""

    corrections: int
    per_minute: float
    threshold_db: float
    sample_fraction: float
    alteration_db: float
    applied: bool
    reason: str = ""

    def __str__(self):
        if not self.applied:
            return f"de-click: nothing corrected ({self.reason})"
        return (
            f"de-click: {self.corrections} corrections "
            f"({self.per_minute:.1f}/min, {self.sample_fraction * 100:.4f} % of samples, "
            f"threshold {self.threshold_db:.1f} dB, signal altered {self.alteration_db:.1f} dB)"
        )


def _clusters(mask, min_gap_samples):
    """Contiguous runs of True in ``mask``, merged across gaps below ``min_gap_samples``."""
    if not mask.any():
        return np.empty((0, 2), dtype=np.int64)
    padded = np.concatenate(([False], mask, [False]))
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    starts, ends = edges[0::2], edges[1::2]
    if starts.size > 1:
        keep = np.concatenate(([True], (starts[1:] - ends[:-1]) > min_gap_samples))
        merged_starts = starts[keep]
        merged_ends = np.concatenate((ends[np.flatnonzero(keep[1:])], ends[-1:]))
        starts, ends = merged_starts, merged_ends
    return np.stack([starts, ends], axis=1)


def declick(
    audio,
    rate,
    max_per_minute=DEFAULT_MAX_PER_MINUTE,
    min_ratio_db=MIN_RATIO_DB,
    max_ratio_db=MAX_RATIO_DB,
):
    """Remove lip smacks, correcting no more often than ``max_per_minute``.

    Args:
        audio: Mono float array.  Never modified in place.
        rate: Sample rate in Hz.
        max_per_minute: The budget.  The threshold is raised until the number
            of findings fits it.
        min_ratio_db: Floor for the detection threshold.
        max_ratio_db: Ceiling.  If the budget is not met here, nothing is corrected.

    Returns:
        ``(out, DeclickReport)``.  The sample count is always preserved.
    """
    x = dsp.as_mono(audio, "de-click input")
    n = x.size
    if n < rate // 10:
        return x.copy(), DeclickReport(0, 0.0, min_ratio_db, 0.0, -np.inf, False, "too short to analyse")

    minutes = max(n / rate / 60.0, 1e-9)
    budget = int(np.floor(max_per_minute * minutes))

    hf = dsp.highpass(x, rate, CLICK_BAND_HZ, zero_phase=True)
    lf = dsp.lowpass(x, rate, PLOSIVE_BAND_HZ, zero_phase=True)

    # A click is a spike in the high band against the local high-band level.
    # The baseline is deliberately long (200 ms) so a single spike cannot raise
    # its own reference -- the mistake that made the old detector fire on 2 %
    # of samples.
    spike = dsp.moving_peak(hf, max(1, int(0.001 * rate)))
    baseline = dsp.moving_rms(hf, max(1, int(0.200 * rate)))
    ratio_db = dsp.lin_to_db(spike) - dsp.lin_to_db(baseline)

    # A 'p' or a 't' puts most of its energy down low; a lip smack puts it up
    # high.  The comparison is between the two bands at the same instant, not
    # against a level taken from the whole file: a threshold on the low band
    # alone reads as "everything is a plosive" on quiet material and as
    # "nothing is" on loud material, and both are wrong in silence.
    short = max(1, int(0.005 * rate))
    hf_short = dsp.moving_rms(hf, short)
    lf_short = dsp.moving_rms(lf, short)
    is_plosive = lf_short > hf_short * PLOSIVE_DOMINANCE

    candidates = (ratio_db >= min_ratio_db) & ~is_plosive
    min_gap = max(1, int(0.020 * rate))
    spans = _clusters(candidates, min_gap)

    if spans.shape[0] == 0:
        return x.copy(), DeclickReport(0, 0.0, min_ratio_db, 0.0, -np.inf, True, "nothing found")

    strengths = np.array([ratio_db[a:b].max() for a, b in spans])

    # Calibrate on the rate: keep the strongest findings that fit the budget.
    threshold_db = min_ratio_db
    rate_found = spans.shape[0] / minutes
    if spans.shape[0] > budget:
        too_many = budget <= 0 or spans.shape[0] > budget * REFUSE_FACTOR
        if not too_many:
            # The threshold that lets exactly `budget` findings through.
            threshold_db = float(np.sort(strengths)[-budget])
        if too_many or threshold_db > max_ratio_db:
            return x.copy(), DeclickReport(
                0,
                0.0,
                max_ratio_db,
                0.0,
                -np.inf,
                False,
                f"{spans.shape[0]} findings ({rate_found:.0f}/min) against a "
                f"{max_per_minute:.0f}/min budget, and no threshold up to the "
                f"{max_ratio_db:.0f} dB ceiling makes them fit; whatever this is, "
                "it is not a lip smack",
            )

    keep = strengths >= threshold_db
    spans = spans[keep]

    max_click = int(MAX_CLICK_MS * rate / 1000.0)
    out = x.copy()
    corrected_samples = 0
    corrections = 0
    # A finding marks where the spike cleared the threshold, not where the click
    # begins and ends.  Correcting only the marked samples leaves most of the
    # smack in place (measured: 3 dB off the high band instead of 20), so each
    # finding is grown out to where the high band has fallen back towards its
    # local level -- and no further than a lip smack can last.
    skirt_db = min_ratio_db - 12.0
    for a, b in spans:
        a, b = int(a), int(b)
        lo, hi = max(0, a - max_click), min(n, b + max_click)
        left_below = np.flatnonzero(ratio_db[lo:a] <= skirt_db)
        a = lo + (left_below[-1] + 1 if left_below.size else 0)
        right_below = np.flatnonzero(ratio_db[b:hi] <= skirt_db)
        b = b + (right_below[0] if right_below.size else hi - b)
        width = b - a
        if width <= 0 or width > max_click:
            continue
        # Remove the high band across the click and leave the voiced low band
        # alone: a click is high-frequency, and interpolating the whole
        # waveform would gouge the vowel underneath it.
        taper = np.hanning(width + 2)[1:-1] if width > 2 else np.ones(width)
        out[a:b] = x[a:b] - hf[a:b] * taper
        corrected_samples += width
        corrections += 1

    residual = out - x
    alteration_db = (
        float(dsp.lin_to_db(np.sqrt(np.mean(residual**2))) - dsp.lin_to_db(np.sqrt(np.mean(x**2))))
        if corrections
        else -np.inf
    )
    return out, DeclickReport(
        corrections=corrections,
        per_minute=corrections / minutes,
        threshold_db=float(threshold_db),
        sample_fraction=corrected_samples / n,
        alteration_db=alteration_db,
        applied=True,
    )
