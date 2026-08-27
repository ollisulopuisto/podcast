"""The per-track chain: samples in, samples out.

This is the seam.  ``process_track`` takes an audio array, a sample rate,
settings, a gain, a speech flag, a target level, a plug-in and a speech mask,
and returns an array.  It has never heard of FCPXML, timelines, session files
or paths -- everything a host knows lives on the host's side of this call.

Order, and why:

1. **The plug-in**, first, in its one slot (see :mod:`speechmix.plugin`).
   De-bleeding happens before this, on the raw audio, and is a *cross-track*
   operation the host performs before calling here: a generative restoration
   plug-in does not preserve the linear relation between tracks, and after it
   no filter can remove the bleed.
2. **The working gain**, so that the absolute thresholds below mean something.
3. **De-click**, budgeted by rate rather than by a multiplier.
4. **High-pass**, for desk rumble and plosive sub-bass.
5. **The level rider**, which needs the speech mask and does nothing without
   one.
6. **De-essing**, before the compressors, because a restoration plug-in adds
   several dB above 3 kHz and one sibilant otherwise drives the gain of a whole
   sentence.
7. **Three bounded compression stages**, each capped at 5 dB.
8. **Normalisation to the target**, as the last act -- which is why any trim
   belongs in the target and never in the gain.

The sample count is checked at every stage, not once at the end.
"""

from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np

from . import dsp
from .declick import DeclickReport, declick
from .dynamics import DynamicsReport, StageReport, deess, speech_dynamics
from .loudness import normalise
from .plugin import process_in_pieces
from .rider import RiderReport, ride
from .settings import ChainSettings
from .verify import assert_same_length


@dataclass
class ChainReport:
    """Everything the chain did, in the order it did it.

    Every stage that can do nothing says so, because a stage that produced
    nothing and said nothing is the failure mode this pipeline keeps paying
    for.  ``log`` is the running order; the typed fields are there for anything
    that wants to assert on a number rather than read a line.
    """

    log: List[str] = field(default_factory=list)
    declick: Optional[DeclickReport] = None
    rider: Optional[RiderReport] = None
    deess: Optional[StageReport] = None
    dynamics: Optional[DynamicsReport] = None
    normalisation_db: float = 0.0

    def note(self, line):
        self.log.append(str(line))

    def __str__(self):
        return "\n".join(self.log + [f"normalisation: {self.normalisation_db:+.2f} dB"])

    @property
    def silent_stages(self):
        """Stages that were switched on and moved nothing."""
        silent = []
        if self.declick is not None and not self.declick.applied:
            silent.append(f"de-click ({self.declick.reason})")
        if self.rider is not None and not self.rider.applied:
            silent.append(f"level rider ({self.rider.reason})")
        if self.deess is not None and not self.deess.fired:
            silent.append("de-esser never fired")
        if self.dynamics is not None:
            silent.extend(f"{s.name} never fired" for s in self.dynamics.silent_stages)
        return silent


def process_track(
    audio,
    rate,
    settings=None,
    gain_db=0.0,
    speech_flag=True,
    target_lufs=None,
    plugin=None,
    speech_mask=None,
):
    """Run one track through the chain.

    Args:
        audio: Mono samples.  De-bleeding, which is cross-track, has already
            happened on the raw audio if it is going to happen at all.
        rate: Sample rate.
        settings: :class:`~speechmix.settings.ChainSettings`.
        gain_db: The gain that brings this track to the chain's working level.
            A trim that belongs to the *programme* goes in ``target_lufs``, not
            here: normalisation is the last act and would remove it exactly.
        speech_flag: False for anything that is not a voice; the speech stages
            are skipped and the track is only gained and normalised.
        target_lufs: Normalise to this as the last act.  ``None`` leaves the
            level where the chain put it.
        plugin: ``callable(chunk) -> chunk``, one full ``reset=True`` pass.
        speech_mask: Per-sample mask of *this speaker's own* speech, from the
            speech grid measured on raw audio.  Without it the rider does
            nothing, deliberately.

    Returns:
        ``(out, ChainReport)``.  The sample count equals the input's.
    """
    settings = settings or ChainSettings()
    x = dsp.as_mono(audio, "chain input")
    original_length = x.size
    report = ChainReport()

    if plugin is not None:
        x = process_in_pieces(plugin, x, rate, pieces=settings.plugin_pieces)
        assert_same_length(audio, x, "plug-in")
        report.note(
            f"plug-in: {settings.plugin_path or 'callable'} "
            f"({settings.plugin_pieces} piece(s))"
        )

    if gain_db:
        x = x * dsp.db_to_lin(gain_db)
        report.note(f"working gain: {gain_db:+.2f} dB")

    if speech_flag and settings.declick_enabled:
        x, report.declick = declick(x, rate, max_per_minute=settings.declick_max_per_minute)
        report.note(report.declick)
        assert_same_length(audio, x, "de-click")

    if speech_flag and settings.highpass_hz:
        x = dsp.highpass(x, rate, settings.highpass_hz)
        report.note(f"high-pass: {settings.highpass_hz:.0f} Hz")

    if speech_flag and settings.rider_enabled:
        x, report.rider = ride(
            x,
            rate,
            speech_mask=speech_mask,
            window_sec=settings.rider_window_sec,
            max_boost_db=settings.rider_max_boost_db,
            max_cut_db=settings.rider_max_cut_db,
        )
        report.note(report.rider)
        assert_same_length(audio, x, "level rider")

    if speech_flag and settings.deess_enabled:
        x, report.deess = deess(x, rate, threshold_db=settings.deess_threshold_db)
        report.note(report.deess)
        assert_same_length(audio, x, "de-esser")

    if speech_flag:
        x, report.dynamics = speech_dynamics(
            x,
            rate,
            peak_threshold_db=settings.peak_threshold_db,
            leveler_threshold_db=settings.leveler_threshold_db,
            peak_ratio=settings.peak_ratio,
            leveler_ratio=settings.leveler_ratio,
            glue_ratio=settings.glue_ratio,
            max_gr_db=settings.max_gr_db,
        )
        report.note(report.dynamics)
        assert_same_length(audio, x, "dynamics")

    if target_lufs is not None:
        x, report.normalisation_db = normalise(x, rate, target_lufs)

    assert_same_length(np.empty(original_length), x, "chain")
    return x, report
