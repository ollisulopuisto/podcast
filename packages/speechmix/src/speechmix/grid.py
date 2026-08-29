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

from dataclasses import dataclass, field
from typing import Dict, Mapping

import numpy as np

from . import dsp
from .dsp import FLOOR_DB
from .errors import EmptyResult

#: Frame geometry.  20 ms hop is fine enough for turn-taking and coarse enough
#: that a single glottal pulse cannot flip the decision.
FRAME_SEC = 0.040
HOP_SEC = 0.020

#: How far above its own noise floor a microphone must be to count as active.
#: Twelve decibels, measured on 77 minutes of real two-microphone material --
#: this is autoraffkat's ``TrackConfig.sensitivity_db`` default, and it is the
#: same number because it is the same question. It used to be 8.0 here, which
#: made "who is speaking" a question this package answered twice.
FLOOR_MARGIN_DB = 12.0

#: Where in the distribution the noise floor is read. A fifth is low enough to
#: be a pause even in busy speech, and high enough not to land on a single
#: digital zero.
NOISE_PERCENTILE = 20.0

#: Moving average over the level curve before the threshold. Without it the
#: decision flickers across the gaps between syllables, which is not a pause.
SMOOTH_SECONDS = 0.10


def smooth(db, seconds=SMOOTH_SECONDS, hop_sec=HOP_SEC):
    """Moving average over a level curve, in dB.

    Speech is not continuous at this resolution: the gaps between syllables
    drop below any threshold, and an unsmoothed decision flickers over them.
    A tenth of a second bridges a syllable and not a pause.
    """
    db = np.asarray(db)
    k = max(1, int(round(seconds / hop_sec)))
    if k <= 1 or db.size < k:
        return db
    # Replicate the edges rather than let ``convolve`` zero-pad. Zero is
    # silence in the linear domain and **full scale** in dB: measured, the
    # first cell of a constant -240 dB curve came back at -144, i.e. 96 dB of
    # level that is not in the material, at the programme's first and last
    # 40 ms. It read as a microphone being active there.
    pad = k // 2
    padded = np.pad(db, (pad, k - 1 - pad), mode="edge")
    kernel = np.ones(k, dtype=np.float64) / k
    return np.convolve(padded, kernel, mode="valid").astype(np.float32)


def noise_floor(db, valid=None, percentile=NOISE_PERCENTILE):
    """This microphone's own noise floor, in dB.

    Measured from the material rather than assumed, because the margin above
    it is what a sensitivity control means -- and a fixed floor would make the
    same setting mean different things on different microphones.

    Depends only on the level curve, never on the settings, so a host with a
    settings loop can cache it and keep it across a slider move.
    """
    db = np.asarray(db)
    if valid is None:
        valid = np.ones(db.shape, dtype=bool)
    valid = np.asarray(valid, dtype=bool)
    if not valid.any():
        return FLOOR_DB
    return float(np.percentile(db[valid], percentile))


def lane(name, parts):
    """One speaker's row of the grid. **This is the decision.**

    ``parts`` are ``(db, valid, floor, margin_db, gain_db)``, one per file.
    There is more than one when the same microphone is a different file in
    each part of a multicam -- same person, same setting, a different stretch
    of the timeline.

    Everything around this function is a host getting hold of levels:
    autoraffkat aligns cached ffmpeg envelopes onto a programme grid,
    automixer measures raw stems that already share a time base. The rule
    itself must not differ between them, and this is where it does not.

    **The margin is over the floor, so gain cannot move the threshold.** Gain
    lifts the signal and its floor by the same amount; what it does change is
    how microphones compare against each other, which is why it is in
    ``level`` and not in ``on``. Mix those two up and the controls start
    interfering with each other.
    """
    n = 0
    for db, *_ in parts:
        n = max(n, np.asarray(db).shape[0])
    level = np.full(n, FLOOR_DB, dtype=np.float32)
    on = np.zeros(n, dtype=bool)
    for db, valid, floor, margin_db, gain_db in parts:
        # ``None`` means "this file covers the whole grid". It is not the same
        # as an empty mask, and ``np.asarray(None, dtype=bool)`` is ``False``,
        # which silently drops every source -- the grid came out empty.
        valid = np.ones(np.asarray(db).shape, dtype=bool) if valid is None \
            else np.asarray(valid, dtype=bool)
        if not valid.any():
            continue
        on |= valid & (np.asarray(db) > floor + margin_db)
        level = np.maximum(level, np.asarray(db) + gain_db)
    return Lane(name=name, on=on, level=level)


@dataclass
class Lane:
    """One microphone's row of the grid, in the shape the masks read.

    ``masks.duck_masks`` and ``envelopes.duck_envelopes`` ask for exactly
    three things — a name, whether the owner is speaking, and how loud the
    microphone is — and pick the loudest when two are active at once.
    """

    name: str
    on: np.ndarray
    level: np.ndarray


@dataclass
class SpeechGrid:
    """Per-frame speech decisions for every microphone in a session."""

    rate: int
    hop_samples: int
    n_samples: int
    speaking: Dict[str, np.ndarray]
    #: Per-frame level in dB, the measurement the decision was made from.
    #: Kept rather than discarded because the ducking rule needs it too: "the
    #: loudest microphone wins" is a comparison, and without the levels this
    #: grid could not feed it.
    levels: Dict[str, np.ndarray] = field(default_factory=dict)

    @property
    def speakers(self):
        """This grid in the shape ``masks`` and ``envelopes`` read.

        The package had two grids and nothing joined them: this module built
        one from raw stems, and the masks read lanes that only a host could
        assemble. Same information, two shapes, and so the ducking could not
        reach the grid this module makes. The view is the missing link, not a
        second computation.

        The name is ``speakers`` because that is what every other reader in
        the workspace already calls it — ``decide``, ``reactions``,
        ``preview`` and the masks all walk ``grid.speakers`` expecting lanes.
        This class alone returned bare names, which is one word meaning two
        things in one package; the names are ``names`` now.
        """
        return [
            Lane(
                name=name,
                on=flags,
                level=self.levels.get(name, np.zeros(flags.shape, dtype=float)),
            )
            for name, flags in self.speaking.items()
        ]

    @property
    def names(self):
        """Whose microphones these are, in order."""
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

    speaking = {}
    for name in names:
        db = smooth(levels[name], hop_sec=hop_sec)
        levels[name] = db
        floor = noise_floor(db)
        speaking[name] = lane(name, [(db, None, floor, floor_margin_db, 0.0)]).on

    if not any(flags.any() for flags in speaking.values()):
        raise EmptyResult(
            "no microphone is ever active: the speech grid is empty, so every "
            "mask downstream would be empty too and every stage that depends on "
            "one would quietly do nothing"
        )

    return SpeechGrid(
        rate=rate,
        hop_samples=hop,
        n_samples=n_samples,
        speaking=speaking,
        levels=levels,
    )
