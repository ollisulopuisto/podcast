"""Gain *decisions*, not gain changes.

This is the second seam, and the more valuable of the two.

``duck_envelopes`` returns ``{speaker: [(time, dB), ...]}``.  One host writes
those into an FCPXML as Final Cut ``<adjust-volume>`` keyframes, so the editor
can still change them.  Another has nothing downstream to write automation
into, so it bakes the same curve into samples.  Same computation, different
emission.

The general rule that fell out of it:

    Level decisions that come **after** the chain can be automation.
    Level decisions that come **before** it must be baked in.

Ducking is after, so it can be automation.  A level rider is before, so it
cannot.

Ducking must never fail quietly.  It depends on the analysis, and pressing the
button before the analysis finished left the masks empty with nothing said: the
setting read -9 dB and the output had none.  ``duck_envelopes`` raises
``EmptyResult`` in that case.

Two more things worth carrying, both measured:

* Ducking is decided on the **raw** files.  A compressor raises the noise floor
  between words and flattens the difference between microphones -- the two
  things the decision depends on.
* What ducking buys, on real material (gap between own speech and own
  non-speech): a clean-ish microphone 17.8 dB raw, 24.2 dB after the chain,
  25.5 dB with ducking; a leaky one 13.4 / 13.3 / 15.0.  What limits the leaky
  track is bleed, not compression -- its non-speech sits 13 dB down because it
  contains the other person's voice.  De-bleeding is the answer to that, not
  more ducking.
"""

from dataclasses import dataclass
from typing import Dict, List, Tuple

import numpy as np

from . import dsp
from .errors import EmptyResult

#: How far a microphone is pulled down while its owner is not speaking.
DEFAULT_DEPTH_DB = -9.0

#: The envelope is a decision about turn-taking, so it moves at the speed of
#: turn-taking, not of syllables.
DEFAULT_ATTACK_SEC = 0.15
DEFAULT_RELEASE_SEC = 0.40

#: Breakpoints closer in level than this are dropped: a host writing keyframes
#: wants the shape, not one point per analysis frame.
POINT_TOLERANCE_DB = 0.25


@dataclass
class DuckSettings:
    depth_db: float = DEFAULT_DEPTH_DB
    attack_sec: float = DEFAULT_ATTACK_SEC
    release_sec: float = DEFAULT_RELEASE_SEC


Envelope = List[Tuple[float, float]]


def _thin(times, values, tolerance_db=POINT_TOLERANCE_DB) -> Envelope:
    """Reduce a per-frame curve to breakpoints, keeping the corners."""
    if times.size == 0:
        return []
    points = [(float(times[0]), float(values[0]))]
    for t, v in zip(times[1:-1], values[1:-1], strict=True):
        last_v = points[-1][1]
        # Keep this point if a straight line from the last kept point to the
        # next frame would miss it by more than the tolerance.
        if abs(v - last_v) >= tolerance_db:
            points.append((float(t), float(v)))
    points.append((float(times[-1]), float(values[-1])))
    return points


def duck_envelopes(grid, settings=None, program_start=0.0):
    """Compute the ducking decision for every microphone in the grid.

    Args:
        grid: A :class:`~speechmix.grid.SpeechGrid`, built on raw audio.
        settings: :class:`DuckSettings`.  ``depth_db = 0`` means no ducking.
        program_start: Added to every time, so the envelopes can be handed
            straight to a host that thinks in programme time.

    Returns:
        ``{speaker: [(time_seconds, gain_db), ...]}``.

    Raises:
        EmptyResult: If ducking is enabled and no microphone matched a mask.
            "The setting is on and no microphone matched a mask" is an error,
            not a silence.
    """
    settings = settings or DuckSettings()
    if settings.depth_db == 0.0:
        return {speaker: [] for speaker in grid.speakers}

    hop_sec = grid.hop_samples / grid.rate
    n_frames = grid.n_frames
    times = program_start + np.arange(n_frames) * hop_sec

    anyone = np.zeros(n_frames, dtype=bool)
    for flags in grid.speaking.values():
        anyone |= flags

    envelopes: Dict[str, Envelope] = {}
    moved = False
    for speaker in grid.speakers:
        mine = grid.speaking[speaker]
        # Down while somebody else has the floor, unity while this speaker
        # does, and unity in the silences: ducking a microphone in a pause
        # where nobody is talking only pumps the room tone.
        target = np.where(mine | ~anyone, 0.0, settings.depth_db)
        attack_frames = max(1.0, settings.attack_sec / hop_sec)
        release_frames = max(1.0, settings.release_sec / hop_sec)
        # The fall follows the attack constant; the return to unity follows the
        # slower release, so a microphone does not flap open between words.
        falling = dsp.one_pole(target, attack_frames)
        rising = dsp.one_pole(falling, release_frames)
        curve = np.minimum(falling, rising)
        if np.any(curve < -POINT_TOLERANCE_DB):
            moved = True
        envelopes[speaker] = _thin(times, curve)

    if not moved:
        raise EmptyResult(
            f"ducking is set to {settings.depth_db:.1f} dB and no microphone "
            "matched a mask, so the output would have none; the setting is on "
            "and the result is empty, which is an error, not a silence"
        )
    return envelopes


def envelope_to_samples(points, rate, n_samples, program_start=0.0):
    """Render a breakpoint envelope into a per-sample linear gain curve.

    For a host with nothing downstream to write automation into: the decision
    is identical, only the emission differs.
    """
    if not points:
        return np.ones(n_samples)
    times = np.array([t - program_start for t, _ in points]) * rate
    values = np.array([v for _, v in points])
    curve_db = np.interp(np.arange(n_samples), times, values)
    return dsp.db_to_lin(curve_db)


def apply_envelope(audio, rate, points, program_start=0.0):
    """Bake a breakpoint envelope into samples.  Sample count is preserved."""
    x = dsp.as_mono(audio, "envelope target")
    return x * envelope_to_samples(points, rate, x.size, program_start)
