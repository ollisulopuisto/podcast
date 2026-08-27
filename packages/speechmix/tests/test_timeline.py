"""A track with a placement on a programme timeline.

Not "an FCPXML asset". An FCPXML asset is that; an automixer session track is
that. The conversion between programme time and file time is linear inside a
span, and that one formula is all the timeline knowledge the pipeline needs.
"""

import pytest

from speechmix.errors import NotMono
from speechmix.timeline import Span, Track


def test_programme_time_maps_to_file_time():
    span = Span(programme_start=10.0, programme_end=20.0, file_offset=3.0)
    assert span.to_file_time(10.0) == 3.0
    assert span.to_file_time(12.5) == 5.5
    assert span.duration == 10.0


def test_a_track_knows_where_it_is_not():
    track = Track("mic.wav", "olli", [Span(10.0, 20.0, 3.0), Span(40.0, 50.0, 25.0)])
    assert track.to_file_time(12.0) == 5.0
    assert track.to_file_time(41.0) == 26.0
    assert track.to_file_time(30.0) is None, "a gap must be None, not an extrapolation"
    assert track.span_at(30.0) is None


def test_a_backwards_span_is_refused():
    with pytest.raises(ValueError):
        Span(programme_start=20.0, programme_end=10.0)


def test_a_microphone_is_always_mono():
    """Two channels break the arithmetic in three places silently: de-bleeding
    reads only the first channel, the programme ceiling broadcasts stems of
    differing channel counts, and panning is a mono-source idea.
    """
    with pytest.raises(NotMono):
        Track("mic.wav", "olli", [], mono=False)
