"""The speech grid: who is talking, measured on the raw microphones.

Everything that needs to know "is this frame this speaker's own voice?" -- the
level rider, the de-bleed estimate, the ducking envelopes -- reads it from
here, and this is measured on the **raw** files.

A compressor raises the noise floor between words and flattens the difference
between microphones, which are exactly the two things the decision depends on.
Measure it on processed audio and the masks fire in the wrong places -- and it
still looks fine until someone listens.

The decision is a *comparison across microphones*, not a threshold on one.  On
a two-microphone recording half of what is loud on a track is the other person:
the level heuristic called 74 % of one track's blocks speech when 53 % were its
owner's, agreeing only 38 % of the time.
"""

from dataclasses import dataclass
from typing import Dict, Mapping

import numpy as np

from . import dsp
from .errors import EmptyResult

#: Frame geometry.  20 ms hop is fine enough for turn-taking and coarse enough
#: that a single glottal pulse cannot flip the decision.
FRAME_SEC = 0.040
HOP_SEC = 0.020

#: How far above its own noise floor a microphone must be to count as active.
FLOOR_MARGIN_DB = 8.0

#: How close to the loudest microphone this one must be to count as its
#: speaker's own voice rather than leakage.  Bleed measured on real material
#: sits well over 6 dB below the source.
DOMINANCE_DB = 6.0


@dataclass
class SpeechGrid:
    """Per-frame speech decisions for every microphone in a session."""

    rate: int
    hop_samples: int
    n_samples: int
    speaking: Dict[str, np.ndarray]

    @property
    def speakers(self):
        return tuple(self.speaking)

    @property
    def n_frames(self) -> int:
        return len(next(iter(self.speaking.values()))) if self.speaking else 0

    def frames_to_samples(self, frames) -> np.ndarray:
        """Expand a per-frame boolean curve to a per-sample mask."""
        expanded = np.repeat(np.asarray(frames, dtype=bool), self.hop_samples)
        if expanded.size < self.n_samples:
            expanded = np.concatenate(
                [expanded, np.zeros(self.n_samples - expanded.size, dtype=bool)]
            )
        return expanded[: self.n_samples]

    def mask(self, speaker) -> np.ndarray:
        """Per-sample mask of this speaker's own speech."""
        return self.frames_to_samples(self.speaking[speaker])

    def only_frames(self, speaker) -> np.ndarray:
        """Frames where this speaker speaks and nobody else does."""
        mine = self.speaking[speaker]
        others = np.zeros_like(mine)
        for name, flags in self.speaking.items():
            if name != speaker:
                others |= flags
        return mine & ~others

    def only(self, speaker) -> np.ndarray:
        """Per-sample mask of the passages where only this speaker speaks."""
        return self.frames_to_samples(self.only_frames(speaker))

    def silence(self) -> np.ndarray:
        """Per-sample mask of the passages where nobody speaks."""
        anyone = np.zeros(self.n_frames, dtype=bool)
        for flags in self.speaking.values():
            anyone |= flags
        return self.frames_to_samples(~anyone)

    def coverage(self, speaker) -> float:
        """Fraction of frames this speaker is speaking in."""
        flags = self.speaking[speaker]
        return float(flags.mean()) if flags.size else 0.0


def speech_grid(
    stems: Mapping[str, np.ndarray],
    rate,
    hop_sec=HOP_SEC,
    frame_sec=FRAME_SEC,
    floor_margin_db=FLOOR_MARGIN_DB,
    dominance_db=DOMINANCE_DB,
):
    """Build the speech grid from the **raw** microphone stems.

    Args:
        stems: ``{speaker: mono raw audio}``.  The stems must line up on the
            timeline; they are compared frame against frame.
        rate: Sample rate.

    Returns:
        A :class:`SpeechGrid`.

    Raises:
        EmptyResult: If no microphone is ever active.  A grid with nothing in
            it is what leaves ducking silently doing nothing later, so it is an
            error here rather than an empty mask three stages downstream.
    """
    if not stems:
        raise EmptyResult("a speech grid was asked for with no microphones")

    names = list(stems)
    arrays = {name: dsp.as_mono(stems[name], name) for name in names}
    n_samples = max(a.size for a in arrays.values())
    hop = max(1, int(hop_sec * rate))
    frame = max(hop, int(frame_sec * rate))
    n_frames = max(1, n_samples // hop)

    levels = {}
    for name, arr in arrays.items():
        padded = np.zeros(n_samples)
        padded[: arr.size] = arr
        env = dsp.moving_rms(padded, frame)
        idx = np.minimum(np.arange(n_frames) * hop + hop // 2, n_samples - 1)
        levels[name] = dsp.lin_to_db(env[idx])

    stacked = np.stack([levels[name] for name in names])
    loudest = stacked.max(axis=0)

    speaking = {}
    for name in names:
        floor = float(np.percentile(levels[name], 10))
        active = levels[name] > floor + floor_margin_db
        dominant = levels[name] >= loudest - dominance_db
        speaking[name] = active & dominant

    if not any(flags.any() for flags in speaking.values()):
        raise EmptyResult(
            "no microphone is ever active: the speech grid is empty, so every "
            "mask downstream would be empty too and every stage that depends on "
            "one would quietly do nothing"
        )

    return SpeechGrid(rate=rate, hop_samples=hop, n_samples=n_samples, speaking=speaking)
