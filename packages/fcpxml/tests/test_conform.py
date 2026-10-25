"""``conform``: a new project spine made of pieces of the original's.

Kuulas gives an ordered list of ``(source_start, source_end)`` ranges of the
source timeline, in Fraction seconds, and the writer lays them back to back.
What must hold above everything else: **sync**. A moment of the new timeline
must play the same moment of every media that the same moment of the source
played, so the property tests below compare file times, not XML text.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from fractions import Fraction

import pytest
import xml_builders as xb
from fcpxml import ConformError, conform, read_fcpxml, snap_pieces

F = Fraction

# Two spine clips of ten seconds: A with a mic attached and a marker, then C.
TWO_CLIPS = """
  <asset-clip ref="a1" name="A" offset="0s" start="0s" duration="10s">
    <asset-clip ref="a2" lane="-1" name="B-mic" offset="0s" start="0s"
                duration="10s" audioRole="dialogue.B"/>
    <marker start="4s" duration="1/25s" value="m4"/>
  </asset-clip>
  <asset-clip ref="v1" name="C" offset="10s" start="100s" duration="10s"/>
"""


def _source(tmp_path, spine=TWO_CLIPS, **kwargs):
    return xb.write(tmp_path, xb.project(spine, **kwargs), "source.fcpxml")


def _out(tmp_path, data: bytes):
    return read_fcpxml(xb.write_bytes(tmp_path, data, "out.fcpxml"))


def _placements(tl):
    return {
        m.name: [(p.offset, p.start, p.duration, p.lane, p.role) for p in m.placements]
        for m in tl.media
    }


def _shape(elem):
    """An element as data, so that indentation does not count."""
    return (elem.tag, dict(elem.attrib), (elem.text or "").strip(), [_shape(c) for c in elem])


def _code(call) -> str:
    with pytest.raises(ConformError) as caught:
        call()
    return caught.value.code


# ------------------------------------------------------------ snapping


def test_a_boundary_snaps_to_the_nearest_frame_not_a_duration():
    fd = F(1, 25)
    # 2.01 s is 50.25 frames, 5.03 s is 125.75: the boundaries move, the pieces follow.
    assert snap_pieces([(F(201, 100), F(503, 100))], fd) == [(F(2), F(126, 25))]


def test_a_half_frame_rounds_up_like_the_rest_of_the_package():
    assert snap_pieces([(F(1, 50), F(1))], F(1, 25)) == [(F(1, 25), F(1))]


def test_adjacent_pieces_keep_one_shared_boundary():
    fd = F(1001, 30000)
    left, right = snap_pieces([(F(0), F(10_013, 1000)), (F(10_013, 1000), F(20))], fd)
    assert left[1] == right[0]
    assert all((t / fd).denominator == 1 for piece in (left, right) for t in piece)


def test_a_piece_that_collapses_to_nothing_is_dropped():
    fd = F(1, 25)
    assert snap_pieces([(F(1), F(1) + F(1, 100)), (F(2), F(3))], fd) == [(F(2), F(3))]


def test_the_grid_is_the_sequences_declared_rate_not_a_probed_one(tmp_path):
    """60 fps material in a 25 fps project: the sequence is still 25 fps."""
    media = tmp_path / "cam.mp4"
    media.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    resources = xb.RESOURCES.replace(
        '<asset id="v1" name="CAM" start="0s" duration="7200s" hasVideo="1"\n'
        '           videoSources="1" format="r1"/>',
        f'<asset id="v1" name="CAM" start="0s" duration="7200s" hasVideo="1" '
        f'videoSources="1" format="r1" src="file://{media}"/>',
    )
    spine = '<asset-clip ref="v1" name="C" offset="0s" start="0s" duration="10s"/>'
    path = xb.write(tmp_path, xb.project(spine, resources=resources), "probed.fcpxml")
    timeline = read_fcpxml(path, probe_frame_duration=lambda item: F(1, 60))
    assert timeline.frame_duration == F(1, 60)  # the reader trusts the probe...
    out = _out(tmp_path, conform(timeline, [(F(2) + F(1, 120), F(5))]))
    # ...the writer does not: 2.00833 s is 50.2 frames of 1/25, which is 2 s.
    assert out.media[0].placements[0].start == 2


# ---------------------------------------------------------- the pieces


def test_the_whole_timeline_as_one_piece_changes_nothing(tmp_path):
    source = _source(tmp_path)
    out = _out(tmp_path, conform(source, [(F(0), F(20))]))
    assert _placements(out) == _placements(read_fcpxml(source))
    assert [m.name for m in out.media[0].placements[0].markers] == ["m4"]


def test_a_ripple_cut_puts_the_pieces_back_to_back(tmp_path):
    out = _out(tmp_path, conform(_source(tmp_path), [(F(2), F(5)), (F(12), F(15))]))
    assert _placements(out) == {
        # A is cut to [2, 5); the mic attached to it goes with it, in sync.
        "MIC A": [(0, 2, 3, 0, "")],
        "MIC B": [(0, 2, 3, -1, "dialogue.B")],
        # C is cut to [12, 15) of the source and moves up to 3 s.
        "CAM": [(3, 102, 3, 0, "")],
    }
    assert out.end == 6
    # The marker at 4 s of A is inside the first piece, so it is on the timeline at 2.
    assert [(m.name, m.time) for m in out.media[0].placements[0].markers] == [("m4", 2)]


def test_a_marker_outside_the_kept_range_is_dropped(tmp_path):
    # The XML itself, not the reader's view of it: the reader hides a marker
    # outside its clip anyway, and Final Cut would keep a stale one in the file.
    data = conform(_source(tmp_path), [(F(5), F(8))])
    assert "<marker" not in data.decode()
    assert "<marker" in conform(_source(tmp_path), [(F(2), F(5))]).decode()


def test_a_piece_may_span_several_spine_items(tmp_path):
    out = _out(tmp_path, conform(_source(tmp_path), [(F(8), F(13))]))
    assert _placements(out) == {
        "MIC A": [(0, 8, 2, 0, "")],
        "MIC B": [(0, 8, 2, -1, "dialogue.B")],
        "CAM": [(2, 100, 3, 0, "")],
    }


def test_pieces_are_snapped_before_they_are_laid_out(tmp_path):
    out = _out(tmp_path, conform(_source(tmp_path), [(F(201, 100), F(503, 100))]))
    cam = _placements(out)["MIC A"]
    assert cam == [(0, 2, F(126, 25) - 2, 0, "")]
    assert out.end == F(126, 25) - 2


def test_the_start_timecode_is_kept(tmp_path):
    spine = TWO_CLIPS.replace('offset="0s"', 'offset="3600s"', 1).replace(
        'offset="10s"', 'offset="3610s"'
    )
    data = conform(_source(tmp_path, spine, tc_start="3600s"), [(F(2), F(5))])
    assert 'tcStart="3600s"' in data.decode()
    assert re.search(r'<asset-clip[^>]*offset="3600s"', data.decode())
    assert _out(tmp_path, data).media[0].placements[0].offset == 0  # zero-based again


def test_a_time_stays_exact_on_a_29_97_timeline(tmp_path):
    unit = F(1001, 30000)
    start, end = unit * 150, unit * 300
    spine = (
        f'<asset-clip ref="a1" name="A" offset="0s" start="0s" '
        f'duration="{(unit * 600).numerator}/{(unit * 600).denominator}s"/>'
    )
    resources = xb.RESOURCES.replace(
        'name="FFVideoFormat1080p25" frameDuration="1/25s"',
        'name="FFVideoFormat1080p2997" frameDuration="1001/30000s"',
    )
    source = _source(tmp_path, spine, resources=resources)
    out = _out(tmp_path, conform(source, [(start, end)]))
    (placement,) = out.media[0].placements
    assert (placement.offset, placement.start, placement.duration) == (0, start, end - start)


# ---------------------------------------------------------------- sync


def _assert_sync(source, out, pieces):
    """The same moment must play the same moment of every media, before and after."""
    src, new = read_fcpxml(source), out
    by_src, by_new = src.media_by_key(), new.media_by_key()
    program = F(0)
    checked = 0
    for lo, hi in snap_pieces(pieces, src.frame_duration):
        for step in range(9):
            t_src = lo + (hi - lo) * F(step, 9)
            t_new = program + (t_src - lo)
            for key, item in by_src.items():
                want = item.file_time_at(t_src)
                got = by_new[key].file_time_at(t_new) if key in by_new else None
                assert got == want, (key, t_src, want, got)
                checked += want is not None
        program += hi - lo
    assert checked > 0


@pytest.mark.parametrize(
    "pieces",
    [
        [(F(3), F(10)), (F(12), F(20)), (F(25), F(30))],
        [(F(0), F(18)), (F(20), F(36))],
        [(F(1), F(2)), (F(17), F(19)), (F(35), F(36))],
    ],
)
def test_sync_is_kept_through_a_multicam(fixture_dir, tmp_path, pieces):
    source = str(fixture_dir / "multicam.fcpxml")
    out = _out(tmp_path, conform(source, pieces))
    _assert_sync(source, out, pieces)


def test_the_angle_roles_of_a_multicam_clip_survive(fixture_dir, tmp_path):
    source = str(fixture_dir / "multicam.fcpxml")
    out = _out(tmp_path, conform(source, [(F(3), F(10)), (F(20), F(30))]))
    src_roles = {mc.angle_ids[0]: mc.angle_roles for mc in read_fcpxml(source).multicams}
    assert [mc.angle_roles for mc in out.multicams] == [
        src_roles[mc.angle_ids[0]] for mc in out.multicams
    ]
    assert len(out.multicams) == 2


@pytest.mark.parametrize(
    "pieces", [[(F(1), F(10)), (F(20), F(35))], [(F(0), F(35))], [(F(34), F(35))]]
)
def test_sync_is_kept_through_a_project_with_attached_clips(fixture_dir, tmp_path, pieces):
    source = str(fixture_dir / "project.fcpxml")
    out = _out(tmp_path, conform(source, pieces))
    _assert_sync(source, out, pieces)


# ----------------------------------------------------------- the document


def test_the_resources_are_copied_verbatim_and_the_version_is_kept(tmp_path):
    source = _source(tmp_path, version="1.9")
    data = conform(source, [(F(0), F(5))])
    assert data.startswith(b'<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n')
    got, want = ET.fromstring(data), ET.parse(source).getroot()
    assert got.get("version") == "1.9"
    assert _shape(got.find("resources")) == _shape(want.find("resources"))


def test_a_new_event_and_a_new_project_with_a_fresh_uid(tmp_path):
    source = _source(tmp_path, name="Episode 7")
    one = ET.fromstring(conform(source, [(F(0), F(5))]))
    two = ET.fromstring(conform(source, [(F(0), F(5))]))
    event, project = one.find(".//event"), one.find(".//project")
    assert event.get("name") == "Episode 7 (kuulas)"
    assert project.get("name") == "Episode 7"
    assert re.fullmatch(r"[0-9A-F-]{36}", project.get("uid"))
    assert project.get("uid") != two.find(".//project").get("uid")
    assert len(one.findall(".//project")) == 1 and len(one.findall(".//event")) == 1


def test_the_project_can_be_named_and_given_a_uid(tmp_path):
    source = _source(tmp_path)
    data = conform(source, [(F(0), F(5))], name="Cut one", uid="ABC")
    root = ET.fromstring(data)
    assert root.find(".//project").get("name") == "Cut one"
    assert root.find(".//project").get("uid") == "ABC"
    assert root.find(".//event").get("name") == "Cut one (kuulas)"
    assert data == conform(source, [(F(0), F(5))], name="Cut one", uid="ABC")


def test_the_sequence_duration_is_the_sum_of_the_pieces(tmp_path):
    root = ET.fromstring(conform(_source(tmp_path), [(F(2), F(5)), (F(12), F(15))]))
    sequence = root.find(".//sequence")
    assert sequence.get("duration") == "6s"
    assert sequence.get("format") == "r1"  # everything else about it is as it was


def test_a_timeline_read_by_the_reader_can_be_the_source(tmp_path):
    source = _source(tmp_path)
    assert conform(read_fcpxml(source), [(F(0), F(5))], uid="U") == conform(
        source, [(F(0), F(5))], uid="U"
    )


# --------------------------------------------------------- transitions


TRANSITION = """
  <asset-clip ref="a1" name="A" offset="0s" start="0s" duration="10s"/>
  <transition name="Cross Dissolve" offset="9s" duration="2s">
    <filter-audio ref="fx1" name="Audio Crossfade"/>
  </transition>
  <asset-clip ref="v1" name="C" offset="10s" start="100s" duration="10s"/>
"""


def test_a_transition_inside_a_piece_is_kept_where_it_was(tmp_path):
    out = _out(tmp_path, conform(_source(tmp_path, TRANSITION), [(F(5), F(20))]))
    assert [(t.offset, t.duration) for t in out.transitions] == [(4, 2)]


def test_a_transition_at_a_cut_is_dropped(tmp_path):
    out = _out(tmp_path, conform(_source(tmp_path, TRANSITION), [(F(0), F(10)), (F(10), F(20))]))
    assert out.transitions == []
    assert out.end == 20  # nothing else moved


# ------------------------------------------------------------- keyframes


FADE = """
  <asset-clip ref="a1" name="A" offset="0s" start="0s" duration="10s">
    <adjust-volume>
      <param name="amount">
        <keyframeAnimation>
          <keyframe time="0s" value="0dB"/>
          <keyframe time="4s" value="-6dB"/>
          <keyframe time="10s" value="-12dB"/>
        </keyframeAnimation>
      </param>
    </adjust-volume>
  </asset-clip>
"""


def test_keyframes_that_cross_a_cut_are_refused_by_default(tmp_path):
    assert _code(lambda: conform(_source(tmp_path, FADE), [(F(2), F(5))])) == "keyframes_cross_cut"


def test_keyframes_that_a_cut_does_not_cross_are_untouched(tmp_path):
    data = conform(_source(tmp_path, FADE), [(F(0), F(10))])
    assert data.decode().count("<keyframe ") == 3


def test_keyframes_can_be_clipped_when_the_caller_accepts_the_cost(tmp_path):
    data = conform(_source(tmp_path, FADE), [(F(2), F(5))], keyframes="clip")
    text = data.decode()
    assert text.count("<keyframe ") == 1 and 'time="4s"' in text


def test_a_parameter_left_with_no_keyframes_is_removed(tmp_path):
    data = conform(_source(tmp_path, FADE), [(F(5), F(8))], keyframes="clip")
    assert "<keyframe" not in data.decode() and "adjust-volume" in data.decode()
    assert "<param" not in data.decode()


# --------------------------------------------------- what is refused


def test_a_retimed_clip_in_the_kept_range_is_refused_not_cut(tmp_path):
    spine = TWO_CLIPS.replace(
        '<marker start="4s"',
        '<timeMap><timept time="0s" value="0s" interp="linear"/></timeMap><marker start="4s"',
    )
    assert _code(lambda: conform(_source(tmp_path, spine), [(F(2), F(5))])) == "unsupported"
    # The same clip is no trouble when none of it is kept.
    assert conform(_source(tmp_path, spine), [(F(12), F(15))])


def test_a_conform_rate_clip_is_refused_too(tmp_path):
    spine = TWO_CLIPS.replace(
        '<marker start="4s"', '<conform-rate srcFrameRate="29.97"/><marker start="4s"'
    )
    assert _code(lambda: conform(_source(tmp_path, spine), [(F(2), F(5))])) == "unsupported"


def test_a_secondary_storyline_is_refused(tmp_path):
    spine = TWO_CLIPS.replace(
        '<marker start="4s"',
        '<spine lane="1" offset="2s"><asset-clip ref="a2" offset="0s" duration="3s"/></spine>'
        '<marker start="4s"',
    )
    assert _code(lambda: conform(_source(tmp_path, spine), [(F(2), F(5))])) == "nested_spine"


def test_a_sync_clip_source_is_not_a_project(fixture_dir):
    assert _code(lambda: conform(str(fixture_dir / "sync.fcpxml"), [(F(0), F(5))])) == "not_a_project"


@pytest.mark.parametrize(
    ("pieces", "code"),
    [
        ([], "no_pieces"),
        ([(F(5), F(5))], "empty_piece"),
        ([(F(6), F(5))], "empty_piece"),
        ([(F(1), F(3)), (F(5), F(5))], "empty_piece"),
        ([(F(5), F(8)), (F(1), F(3))], "unordered"),
        ([(F(1), F(6)), (F(5), F(8))], "overlap"),
        ([(F(-1), F(3))], "outside_timeline"),
        ([(F(15), F(21))], "outside_timeline"),
    ],
)
def test_pieces_that_cannot_be_honoured_are_refused_with_a_code(tmp_path, pieces, code):
    assert _code(lambda: conform(_source(tmp_path), pieces)) == code


def test_a_refusal_names_what_it_found():
    error = ConformError("unsupported", "timeMap on 'A'")
    assert error.code == "unsupported" and error.detail == "timeMap on 'A'"
    assert "unsupported" in str(error) and "timeMap" in str(error)


# --------------------------------------------------- what hangs on a clip


def test_a_keyword_and_a_connected_title_are_narrowed_with_their_host(tmp_path):
    spine = """
      <asset-clip ref="a1" name="A" offset="0s" start="0s" duration="10s">
        <keyword start="0s" duration="10s" value="interview"/>
        <keyword start="8s" duration="2s" value="outro"/>
        <title ref="fx1" name="Lower third" lane="1" offset="1s" start="0s" duration="6s"/>
      </asset-clip>
    """
    data = conform(_source(tmp_path, spine), [(F(2), F(5))]).decode()
    keywords = re.findall(r'<keyword start="([^"]+)" duration="([^"]+)" value="([^"]+)"', data)
    assert keywords == [("2s", "3s", "interview")]  # the outro is past the piece
    title = re.search(r'<title [^>]*name="Lower third"[^>]*>', data).group(0)
    assert 'offset="2s"' in title and 'start="1s"' in title and 'duration="3s"' in title


def test_an_audition_is_narrowed_alternative_by_alternative(tmp_path):
    spine = """
      <asset-clip ref="a1" name="A" offset="0s" start="0s" duration="10s">
        <audition lane="-1" offset="0s">
          <asset-clip ref="a2" name="take 1" offset="0s" start="0s" duration="10s"/>
          <asset-clip ref="a2" name="take 2" offset="0s" start="20s" duration="10s"/>
        </audition>
      </asset-clip>
    """
    data = conform(_source(tmp_path, spine), [(F(2), F(5))])
    out = _out(tmp_path, data)
    assert _placements(out)["MIC B"] == [(0, 2, 3, 0, "")]
    # Both alternatives are kept and narrowed alike, and the audition stands where they do.
    assert data.decode().count("<asset-clip ref=\"a2\"") == 2
    assert re.search(r'<audition lane="-1" offset="2s">', data.decode())
