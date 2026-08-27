"""Level rider: the slow ride that goes first, and only where there is a mask.

A slow level ride before the compressors is the stage every hand-made mix
starts with.  It removes the speaker's *own* variation so the compressor only
catches what is left, instead of doing the rider's job badly -- fast and
level-dependent instead of slow and even.

Two things went the wrong way before it worked, and both are load-bearing:

**Deciding "speech" from the level is worse than not riding at all.**  On a
two-microphone recording, half of what is loud on a track is the other person.
Measured: the level heuristic called 74 % of one track's blocks speech when
53 % were its owner's, agreeing only 38 % of the time.  The rider dutifully
lifted the leakage -- noise floor **up 3.5 dB**, level spread *worse* at
2.88 -> 3.37 dB.  So the mask comes from the speech grid, which is measured on
raw audio, and with no mask this function returns the audio untouched rather
than guessing.

**The gain must return to unity outside its own speaker's speech, not hold.**
Holding is what a one-microphone rider does and it is right there; here the
pause *is the other person talking*, so a held boost lands straight on their
leakage.  Measured, separation between own speech and leakage fell
19.1 -> 14.8 dB.  Returning to zero keeps it at 18.7.

What it is worth, measured on ten minutes of real speech: own-speech level
spread 6.72 -> 6.44 dB and 6.46 -> 5.67 dB, separation and noise floor
unchanged.  Modest, because real speech variation is mostly sentence-scale
emphasis, which the rider deliberately leaves alone.
"""

from dataclasses import dataclass

import numpy as np

from . import dsp

#: The ride is slow on purpose.  Anything faster is a compressor, and there are
#: three of those downstream.
DEFAULT_WINDOW_SEC = 3.0

#: How far it may move.  A rider that can move more than this is fixing
#: something a rider should not be fixing.
DEFAULT_MAX_BOOST_DB = 6.0
DEFAULT_MAX_CUT_DB = 6.0

#: Block size for the level measurement.
BLOCK_SEC = 0.4


@dataclass
class RiderReport:
    applied: bool
    spread_before_db: float
    spread_after_db: float
    max_boost_db: float
    max_cut_db: float
    reason: str = ""

    def __str__(self):
        if not self.applied:
            return f"level rider: not applied ({self.reason})"
        return (
            f"level rider: own-speech spread {self.spread_before_db:.2f} -> "
            f"{self.spread_after_db:.2f} dB, moved +{self.max_boost_db:.1f}/"
            f"-{self.max_cut_db:.1f} dB"
        )


def _block_levels(audio, rate, block_samples):
    n_blocks = max(1, audio.size // block_samples)
    usable = audio[: n_blocks * block_samples].reshape(n_blocks, block_samples)
    return dsp.lin_to_db(np.sqrt(np.mean(usable**2, axis=1))), n_blocks


def ride(
    audio,
    rate,
    speech_mask=None,
    window_sec=DEFAULT_WINDOW_SEC,
    max_boost_db=DEFAULT_MAX_BOOST_DB,
    max_cut_db=DEFAULT_MAX_CUT_DB,
):
    """Ride the level of one speaker's own speech, and nothing else.

    Args:
        audio: Mono track.
        rate: Sample rate.
        speech_mask: Per-sample boolean mask of *this speaker's own* speech,
            taken from the speech grid measured on raw audio.  ``None`` means
            the audio is returned untouched -- guessing from the level is
            measurably worse than not riding.
        window_sec: How slowly the gain is allowed to move.
        max_boost_db / max_cut_db: Bounds on the ride.

    Returns:
        ``(out, RiderReport)``.  The sample count is always preserved.
    """
    x = dsp.as_mono(audio, "level rider input")
    if speech_mask is None:
        return x.copy(), RiderReport(
            False, float("nan"), float("nan"), 0.0, 0.0,
            "no speech mask; deciding speech from the level lifts the other "
            "speaker's leakage and makes the spread worse, so nothing is done",
        )

    mask = np.asarray(speech_mask, dtype=bool)
    if mask.size != x.size:
        raise ValueError(
            f"speech mask is {mask.size} samples, audio is {x.size}: the mask must "
            "be measured on this track's own timeline"
        )
    if not mask.any():
        return x.copy(), RiderReport(
            False, float("nan"), float("nan"), 0.0, 0.0,
            "the speech mask is empty for this speaker",
        )

    block = max(1, int(BLOCK_SEC * rate))
    levels_db, n_blocks = _block_levels(x, rate, block)
    mask_blocks = mask[: n_blocks * block].reshape(n_blocks, block).mean(axis=1) > 0.5
    if not mask_blocks.any():
        return x.copy(), RiderReport(
            False, float("nan"), float("nan"), 0.0, 0.0,
            "no whole block of this speaker's own speech to measure",
        )

    own = levels_db[mask_blocks]
    target_db = float(np.median(own))
    spread_before = float(np.std(own))

    gain_db = np.zeros(n_blocks)
    # Outside this speaker's own speech the gain returns to unity.  It does not
    # hold: the pause *is* the other person talking, and a held boost lands on
    # their leakage.
    gain_db[mask_blocks] = np.clip(target_db - levels_db[mask_blocks], -max_cut_db, max_boost_db)

    # Slow the ride down.  The smoothing is symmetric, so the gain eases back to
    # unity across the boundary instead of stepping.
    smooth_blocks = max(1, int(round(window_sec / BLOCK_SEC)))
    kernel = np.hanning(2 * smooth_blocks + 1)
    kernel /= kernel.sum()
    gain_db = np.convolve(gain_db, kernel, mode="same")

    curve = dsp.interpolate_frames(gain_db, block, x.size)
    out = x * dsp.db_to_lin(curve)

    after_levels, _ = _block_levels(out, rate, block)
    spread_after = float(np.std(after_levels[mask_blocks]))

    return out, RiderReport(
        applied=True,
        spread_before_db=spread_before,
        spread_after_db=spread_after,
        max_boost_db=float(max(0.0, gain_db.max())),
        max_cut_db=float(max(0.0, -gain_db.min())),
    )
