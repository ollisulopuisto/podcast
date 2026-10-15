"""Lähde-XML:n omat leikkaukset (``<mc-clip>``-osien saumat) ruudukon ``edits``iksi."""

from fractions import Fraction

import numpy as np

from autoraffkat.analysis import Analysis, build_grid
from autoraffkat.fcpxml.read import MulticamRef, Timeline, Track
from autoraffkat.model import (
    HOP,
    ROLE_CLOSE,
    ROLE_MIC,
    ROLE_WIDE,
    MediaItem,
    Placement,
    TrackConfig,
)


def _item(key, seconds, audio=False):
    return MediaItem(
        key=key, name=key, path=f"/x/{key}.mp4", src="", asset_start=Fraction(0),
        asset_duration=Fraction(seconds), has_video=not audio, has_audio=audio,
        placements=[Placement(offset=Fraction(0), start=Fraction(0), duration=Fraction(seconds))],
    )


def _timeline(starts):
    """Kaksi osaa: ``starts`` on kunkin mc-clipin lähdeaika-alku, kesto 30 s ja 30 s."""
    media = [_item("W", 60), _item("CA", 60), _item("MA", 60, audio=True)]
    refs, at = [], Fraction(0)
    for start in starts:
        refs.append(MulticamRef(media_id="r2", name="pp", offset=at, duration=Fraction(30),
                                start=Fraction(start)))
        at += 30
    return Timeline(
        media=media, frame_duration=Fraction(1, 25), kind="multicam", name="t",
        tracks=[Track(key=m.key, name=m.key, media_keys=[m.key]) for m in media],
        multicams=refs,
    ), {
        "W": TrackConfig(role=ROLE_WIDE),
        "CA": TrackConfig(role=ROLE_CLOSE, speaker="A"),
        "MA": TrackConfig(role=ROLE_MIC, speaker="A"),
    }


def _grid(starts):
    timeline, tracks = _timeline(starts)
    env = np.full(int(60 / HOP) + 1, -80.0, dtype=np.float32)
    env[int(5 / HOP):int(55 / HOP)] = -20.0
    grid, _, _ = build_grid(Analysis(timeline=timeline, envelopes={"MA": env}), tracks)
    return grid


def test_a_jump_in_the_source_is_an_edit():
    """Toinen osa alkaa lähteessä kohdasta 200, vaikka ensimmäinen päättyi 130:een."""
    assert _grid([100, 200]).edits == (30.0,)


def test_parts_that_continue_each_other_are_not_edits():
    assert _grid([100, 130]).edits == ()


def test_one_part_has_no_edits():
    assert _grid([100]).edits == ()
