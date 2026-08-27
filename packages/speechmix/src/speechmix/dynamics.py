"""Dynamics: small amounts, several times, and every stage checked.

Three bounded stages, each capped at 5 dB of gain reduction.  The first is
multiband so a plosive cannot pull the sibilance down with it, with one ratio
and one limit across all bands -- differing amounts per band move the tone with
the programme.

Two findings live here.

**One of the three stages never fired.**  Its threshold was written
``leveler_threshold + 4.0`` -- four decibels *above* the second stage -- and it
runs after the second, which has already pulled everything below its own
threshold.  Measured on three minutes of real speech, that stage's gain moved
**0.00 dB at every target from -14 to -18 LUFS**.  The chain promised three
stages and ran two.  ``speech_dynamics`` returns a report per stage so that a
stage which does nothing is visible instead of merely absent.

**The peak attack must be longer than a pitch period.**  Two milliseconds
modulates the waveform of a 110 Hz voice instead of its level, which is
harmonic distortion by definition.  Measured on a sine at 110 Hz / -6 dBFS:
2 ms -> THD -30.9 dB, 10 ms -> -32.9 dB, 40 ms -> -36.1 dB.  15 ms is longer
than a pitch period for every speaking voice.

De-essing goes **before** the compressors, because a restoration plug-in adds
several dB above 3 kHz (measured +4...+5.7 dB, 3-20 kHz with dxRevive) and one
sibilant otherwise drives the gain of a whole sentence.
"""

from dataclasses import dataclass, field
from typing import List

import numpy as np

from . import dsp

#: Longer than a pitch period for every speaking voice.  See the THD numbers above.
PEAK_ATTACK_MS = 15.0

#: Each stage is bounded.  Three small amounts, not one large one.
MAX_GR_DB = 5.0

#: Sibilance band.  The de-esser works here and nowhere else.
SIBILANCE_LOW_HZ = 5000.0
SIBILANCE_HIGH_HZ = 9000.0

#: A sibilant is noise, not a pitched sound, so its attack has no pitch period
#: to be longer than.  It still must not be instantaneous.
DEESS_ATTACK_MS = 5.0
DEESS_MAX_GR_DB = 6.0

#: The crossover for the multiband stage.
CROSSOVER_HZ = (250.0, 4000.0)

#: The level the chain works at internally.  Thresholds below are absolute and
#: are only meaningful against a track that has been normalised to this first;
#: the chain normalises to the *programme* target as its last act instead.
WORKING_LEVEL_LUFS = -23.0

#: Measured against a track at the working level: the 15 ms RMS of real speech
#: peaks around -13 dB there, and the loud syllables are what should clear the
#: first threshold.
PEAK_THRESHOLD_DB = -20.0
LEVELER_THRESHOLD_DB = -24.0

#: Stage 3 sits *below* stage 2, not above it.  See ``speech_dynamics``.
GLUE_OFFSET_DB = -4.0


@dataclass
class StageReport:
    """What one dynamics stage did.  ``fired`` is the question the chain got wrong."""

    name: str
    threshold_db: float
    ratio: float
    attack_ms: float
    max_gr_db: float
    mean_gr_db: float

    @property
    def fired(self) -> bool:
        """True if this stage moved the gain at all.

        A stage that promises compression and moves 0.00 dB is a stage the
        chain is not running.  It cost hours to find that out by measurement;
        this makes it a property anyone can assert on.
        """
        return self.max_gr_db > 0.01

    def __str__(self):
        state = f"{self.max_gr_db:.2f} dB peak, {self.mean_gr_db:.2f} dB mean"
        if not self.fired:
            state += "  <-- NEVER FIRED"
        return (
            f"{self.name}: threshold {self.threshold_db:.1f} dB, ratio {self.ratio:.2f}:1, "
            f"attack {self.attack_ms:.0f} ms -> {state}"
        )


@dataclass
class DynamicsReport:
    stages: List[StageReport] = field(default_factory=list)

    @property
    def silent_stages(self) -> List[StageReport]:
        return [s for s in self.stages if not s.fired]

    def __str__(self):
        return "\n".join(str(s) for s in self.stages)


def _gain_reduction_db(audio, rate, threshold_db, ratio, attack_ms, release_ms, max_gr_db):
    """The gain-reduction curve for one stage, in dB (<= 0), downward only.

    The level detector's window *is* the attack: it must be longer than a pitch
    period or the gain follows the waveform rather than the level.
    """
    attack_samples = max(1, int(attack_ms * rate / 1000.0))
    release_samples = max(1, int(release_ms * rate / 1000.0))
    level_db = dsp.lin_to_db(dsp.moving_rms(audio, attack_samples))
    over = np.maximum(level_db - threshold_db, 0.0)
    gr = -over * (1.0 - 1.0 / ratio)
    gr = np.maximum(gr, -abs(max_gr_db))
    return dsp.release_smooth(gr, release_samples)


def compress(
    audio,
    rate,
    threshold_db,
    ratio,
    attack_ms=PEAK_ATTACK_MS,
    release_ms=200.0,
    max_gr_db=MAX_GR_DB,
    name="compressor",
):
    """One bounded, downward-only compression stage.  No makeup gain.

    No makeup gain is deliberate: the chain normalises once, at the end.  A
    stage with makeup gain raises the noise floor between words, and that is
    one of the two things the ducking and sensitivity decisions depend on.
    """
    x = dsp.as_mono(audio, name)
    gr_db = _gain_reduction_db(x, rate, threshold_db, ratio, attack_ms, release_ms, max_gr_db)
    out = x * dsp.db_to_lin(gr_db)
    report = StageReport(
        name=name,
        threshold_db=threshold_db,
        ratio=ratio,
        attack_ms=attack_ms,
        max_gr_db=float(max(0.0, -gr_db.min())) if gr_db.size else 0.0,
        mean_gr_db=float(max(0.0, -gr_db.mean())) if gr_db.size else 0.0,
    )
    return out, report


def multiband_compress(
    audio,
    rate,
    threshold_db,
    ratio,
    attack_ms=PEAK_ATTACK_MS,
    release_ms=200.0,
    max_gr_db=MAX_GR_DB,
    crossover_hz=CROSSOVER_HZ,
    name="multiband peak",
):
    """Multiband compression with **one** ratio and **one** limit across the bands.

    Each band gets its own gain reduction -- that is the point, so a plosive in
    the low band cannot pull the sibilance down with it -- but they share the
    ratio and the 5 dB limit.  Differing amounts per band move the tone with
    the programme, which is a colouration that follows whoever is talking.

    The crossover is a zero-phase subtraction crossover, so the bands sum back
    to the input exactly and the stage is a true no-op when nothing fires.
    """
    x = dsp.as_mono(audio, name)
    bands = dsp.split_bands(x, rate, crossover_hz[0], crossover_hz[1])
    out = np.zeros_like(x)
    worst_max, worst_mean = 0.0, 0.0
    for band in bands:
        gr_db = _gain_reduction_db(
            band, rate, threshold_db, ratio, attack_ms, release_ms, max_gr_db
        )
        out += band * dsp.db_to_lin(gr_db)
        worst_max = max(worst_max, float(-gr_db.min()))
        worst_mean = max(worst_mean, float(-gr_db.mean()))
    report = StageReport(
        name=name,
        threshold_db=threshold_db,
        ratio=ratio,
        attack_ms=attack_ms,
        max_gr_db=worst_max,
        mean_gr_db=worst_mean,
    )
    return out, report


def deess(
    audio,
    rate,
    threshold_db,
    ratio=3.0,
    attack_ms=DEESS_ATTACK_MS,
    release_ms=80.0,
    max_gr_db=DEESS_MAX_GR_DB,
    band_hz=(SIBILANCE_LOW_HZ, SIBILANCE_HIGH_HZ),
    name="de-esser",
):
    """Reduce sibilance, and only sibilance, before the compressors.

    A restoration plug-in adds several dB above 3 kHz (measured +4...+5.7 dB,
    3-20 kHz with dxRevive).  Downstream of this, one sibilant would otherwise
    drive the gain of a whole sentence.
    """
    x = dsp.as_mono(audio, name)
    band = dsp.bandpass(x, rate, band_hz[0], band_hz[1])
    gr_db = _gain_reduction_db(band, rate, threshold_db, ratio, attack_ms, release_ms, max_gr_db)
    out = x - band + band * dsp.db_to_lin(gr_db)
    report = StageReport(
        name=name,
        threshold_db=threshold_db,
        ratio=ratio,
        attack_ms=attack_ms,
        max_gr_db=float(max(0.0, -gr_db.min())) if gr_db.size else 0.0,
        mean_gr_db=float(max(0.0, -gr_db.mean())) if gr_db.size else 0.0,
    )
    return out, report


def speech_dynamics(
    audio,
    rate,
    peak_threshold_db=PEAK_THRESHOLD_DB,
    leveler_threshold_db=LEVELER_THRESHOLD_DB,
    peak_ratio=2.5,
    leveler_ratio=1.5,
    glue_ratio=1.25,
    max_gr_db=MAX_GR_DB,
):
    """The three bounded stages, in order, each reporting what it did.

    Stage 3's threshold is ``leveler_threshold - 4``.  It was written
    ``+ 4`` -- above the stage before it, which had already pulled everything
    below its own threshold -- and measured 0.00 dB of movement at every target
    from -14 to -18 LUFS.  The sign of that constant is the whole finding.

    Thresholds here are **absolute** and are applied *after* the track has been
    normalised to the chain's working level.  A signal whose every burst is
    equally loud sits entirely below all of them; in speech it is the loud
    passages that clear the threshold.
    """
    report = DynamicsReport()

    out, r1 = multiband_compress(
        audio,
        rate,
        threshold_db=peak_threshold_db,
        ratio=peak_ratio,
        attack_ms=PEAK_ATTACK_MS,
        release_ms=120.0,
        max_gr_db=max_gr_db,
        name="1 multiband peak",
    )
    report.stages.append(r1)

    out, r2 = compress(
        out,
        rate,
        threshold_db=leveler_threshold_db,
        ratio=leveler_ratio,
        attack_ms=60.0,
        release_ms=400.0,
        max_gr_db=max_gr_db,
        name="2 leveler",
    )
    report.stages.append(r2)

    out, r3 = compress(
        out,
        rate,
        threshold_db=leveler_threshold_db + GLUE_OFFSET_DB,
        ratio=glue_ratio,
        attack_ms=120.0,
        release_ms=800.0,
        max_gr_db=max_gr_db,
        name="3 glue",
    )
    report.stages.append(r3)

    return out, report
