"""What kuulas asked of the reader (docs/PODCAST-MAGIC.md, "A shared fcpxml package").

Neutral types, ``Fraction`` seconds, no user-interface strings: the bundle, the
version and format, the audio role and whether it is muted, markers, audio
transitions, the clips that are flagged ``unsupported`` instead of misread, and
what is counted and left out.
"""

from __future__ import annotations

import shutil
from fractions import Fraction
from itertools import pairwise

import xml_builders as xb
import xml_fixtures
from fcpxml import read_fcpxml


def _read(tmp_path, spine, **kwargs):
    read_args = {k: kwargs.pop(k) for k in ("include_muted",) if k in kwargs}
    return read_fcpxml(xb.write(tmp_path, xb.project(spine, **kwargs)), **read_args)


# ----------------------------------------------------------------- the file


def test_a_bundle_reads_as_its_info_fcpxml(fixture_dir, tmp_path):
    bundle = tmp_path / "episode.fcpxmld"
    bundle.mkdir()
    shutil.copy(fixture_dir / "project.fcpxml", bundle / "Info.fcpxml")
    from_bundle = read_fcpxml(str(bundle))
    from_file = read_fcpxml(str(fixture_dir / "project.fcpxml"))
    assert from_bundle.kind == from_file.kind == "project"
    assert [m.key for m in from_bundle.media] == [m.key for m in from_file.media]
    assert from_bundle.source_path == str(bundle)


def test_the_version_the_start_timecode_and_the_name_are_kept(tmp_path):
    spine = '<asset-clip ref="a1" offset="3600s" start="0s" duration="10s"/>'
    tl = _read(tmp_path, spine, version="1.9", tc_start="3600s", name="Episode 7")
    assert tl.fcpxml_version == "1.9"
    assert tl.tc_start == 3600
    assert tl.name == "Episode 7"
    # The timeline is zero-based: the start timecode is taken off while reading.
    assert tl.media[0].placements[0].offset == 0


def test_an_unnamed_project_has_an_empty_name_not_a_translated_one(tmp_path):
    spine = '<asset-clip ref="a1" offset="0s" start="0s" duration="10s"/>'
    assert _read(tmp_path, spine, name=None).name == ""


def test_the_format_is_the_sequences_picture_size_and_rate(tmp_path):
    spine = '<asset-clip ref="a1" offset="0s" start="0s" duration="10s"/>'
    fmt = _read(tmp_path, spine).format
    assert (fmt.width, fmt.height) == (1920, 1080)
    assert fmt.frame_duration == Fraction(1, 25)
    assert fmt.rate == 25


def test_a_format_with_no_rate_says_none_rather_than_guessing(tmp_path):
    resources = xb.RESOURCES + '<format id="r9" name="FFVideoFormatRateUndefined"/>'
    spine = '<asset-clip ref="a1" offset="0s" start="0s" duration="10s"/>'
    tl = _read(tmp_path, spine, resources=resources, sequence_format="r9")
    assert tl.format.rate is None and tl.format.frame_duration is None
    assert tl.frame_duration == Fraction(1, 25)  # the timeline still gets a rate


# ----------------------------------------------------------- role and mute


def test_the_audio_role_is_what_final_cut_names_it(tmp_path):
    spine = """
      <asset-clip ref="a1" offset="0s" start="0s" duration="10s" audioRole="dialogue.Tomi"/>
      <asset-clip ref="a2" offset="10s" start="0s" duration="10s">
        <audio-channel-source srcCh="1" role="dialogue.Vieras"/>
      </asset-clip>
      <clip offset="20s" start="0s" duration="10s">
        <video ref="v1" offset="0s" start="0s" duration="10s" role="video"/>
        <audio ref="a1" lane="-1" offset="0s" start="0s" duration="10s"
               role="dialogue.dialogue-1"/>
      </clip>
    """
    tl = _read(tmp_path, spine)
    roles = {m.name: [p.role for p in m.placements] for m in tl.media}
    assert roles == {
        "MIC A": ["dialogue.Tomi", "dialogue.dialogue-1"],
        "MIC B": ["dialogue.Vieras"],
        "CAM": [""],  # a picture role is not an audio role
    }


def test_muted_audio_is_left_out_unless_it_is_asked_for(tmp_path):
    path = xb.write(tmp_path, xml_fixtures.SYNC_MUTED)
    assert "CAM 3" not in [m.name for m in read_fcpxml(path).media]

    tl = read_fcpxml(path, include_muted=True)
    by_name = {m.name: m for m in tl.media}
    camera_audio = by_name["CAM 3"].placements[0]
    assert camera_audio.muted is True
    assert camera_audio.role == "dialogue.dialogue-1"
    # What was not switched off is not muted.
    assert by_name["mic guest"].placements[0].muted is False
    assert by_name["CAM 2"].placements[0].muted is False


def test_a_picture_and_its_muted_sound_are_one_occurrence(tmp_path):
    """``<video>`` and ``<audio>`` of one asset in one place are one occurrence.

    It is muted only if all of it is: the picture is playing, so the occurrence
    is not muted, and it still knows the role of its sound.
    """
    spine = """
      <sync-clip offset="0s" start="0s" duration="10s">
        <clip offset="0s" start="0s" duration="10s">
          <video ref="v1" offset="0s" start="0s" duration="10s"/>
          <audio ref="v1" lane="-1" offset="0s" start="0s" duration="10s"
                 role="dialogue.dialogue-1"/>
        </clip>
        <sync-source sourceID="storyline">
          <audio-role-source role="dialogue.dialogue-1" active="0"/>
        </sync-source>
      </sync-clip>
    """
    kept = _read(tmp_path, spine, include_muted=True).media[0].placements
    assert len(kept) == 1
    assert kept[0].muted is False
    assert kept[0].role == "dialogue.dialogue-1"
    # Left out by default: the sound is gone, and the picture alone is the occurrence.
    dropped = _read(tmp_path, spine).media[0].placements
    assert len(dropped) == 1 and dropped[0].role == ""


def test_a_clip_that_is_switched_off_is_kept_and_says_so(tmp_path):
    spine = """
      <asset-clip ref="a1" offset="0s" start="0s" duration="10s"/>
      <asset-clip ref="a2" offset="10s" start="0s" duration="10s" enabled="0"/>
      <sync-clip offset="20s" start="0s" duration="10s" enabled="0">
        <asset-clip ref="v1" offset="0s" start="0s" duration="10s"/>
      </sync-clip>
    """
    tl = _read(tmp_path, spine)
    enabled = {m.name: m.placements[0].enabled for m in tl.media}
    assert enabled == {"MIC A": True, "MIC B": False, "CAM": False}


# ------------------------------------------------------------------ markers


def test_a_clips_markers_are_on_the_timeline_not_in_the_clips_own_time(tmp_path):
    spine = """
      <asset-clip ref="a1" offset="10s" start="5s" duration="20s">
        <marker start="7s" duration="1/25s" value="Intro"/>
        <chapter-marker start="9s" value="Part one" posterOffset="11/24s"/>
        <marker start="6s" duration="1/25s" value="Todo" completed="0"/>
        <marker start="8s" duration="1/25s" value="Done" completed="1"/>
        <marker start="4s" duration="1/25s" value="Before the clip"/>
        <marker start="25s" duration="1/25s" value="At its end"/>
      </asset-clip>
    """
    markers = _read(tmp_path, spine).media[0].placements[0].markers
    # In time order, whatever the order in the XML.
    assert [(m.name, m.kind, m.time) for m in markers] == [
        ("Todo", "marker", 11),
        ("Intro", "marker", 12),
        ("Done", "marker", 13),
        ("Part one", "chapter", 14),
    ]
    assert [m.completed for m in markers] == [False, None, True, None]
    assert markers[1].duration == Fraction(1, 25)
    assert markers[3].duration == 0


def test_markers_follow_the_start_timecode(tmp_path):
    spine = """
      <asset-clip ref="a1" offset="3610s" start="0s" duration="20s">
        <marker start="2s" duration="1/25s" value="Here"/>
      </asset-clip>
    """
    tl = _read(tmp_path, spine, tc_start="3600s")
    assert tl.media[0].placements[0].markers[0].time == 12


def test_a_marker_on_a_gap_or_a_container_is_on_the_timeline(tmp_path):
    spine = """
      <gap name="Gap" offset="0s" start="0s" duration="30s">
        <marker start="4s" duration="1/25s" value="On the gap"/>
        <asset-clip ref="a1" lane="-1" offset="0s" start="0s" duration="30s">
          <marker start="1s" duration="1/25s" value="On the clip"/>
        </asset-clip>
      </gap>
    """
    tl = _read(tmp_path, spine)
    assert [(m.name, m.time) for m in tl.markers] == [("On the gap", 4)]
    # A clip's own marker is on the clip, once, and not also here.
    assert [m.name for m in tl.media[0].placements[0].markers] == ["On the clip"]


def test_marker_times_are_exact(tmp_path):
    spine = """
      <asset-clip ref="a1" offset="1001/30000s" start="0s" duration="10s">
        <marker start="2002/30000s" duration="1001/30000s" value="Frame two"/>
      </asset-clip>
    """
    marker = _read(tmp_path, spine).media[0].placements[0].markers[0]
    assert marker.time == Fraction(3003, 30000)
    assert marker.duration == Fraction(1001, 30000)


# -------------------------------------------------------------- transitions


def test_a_transition_says_whether_it_is_audio_picture_or_both(tmp_path):
    spine = """
      <asset-clip ref="v1" offset="0s" start="0s" duration="10s"/>
      <transition name="Cross Dissolve" offset="9s" duration="2s">
        <filter-video ref="fx1" name="Cross Dissolve"/>
        <filter-audio ref="fx1" name="Audio Crossfade"/>
      </transition>
      <asset-clip ref="v1" offset="10s" start="10s" duration="10s"/>
      <transition name="Audio Crossfade" offset="19s" duration="1/2s">
        <filter-audio ref="fx1" name="Audio Crossfade"/>
      </transition>
      <asset-clip ref="v1" offset="20s" start="20s" duration="10s"/>
      <transition name="Fade" offset="29s" duration="1s">
        <filter-video ref="fx1" name="Fade"/>
      </transition>
    """
    got = [
        (t.name, t.offset, t.duration, t.has_audio, t.has_video)
        for t in _read(tmp_path, spine).transitions
    ]
    assert got == [
        ("Cross Dissolve", 9, 2, True, True),
        ("Audio Crossfade", 19, Fraction(1, 2), True, False),
        ("Fade", 29, 1, False, True),
    ]


# -------------------------------------------------------------- unsupported


def test_a_retimed_clip_is_flagged_not_misread(tmp_path):
    spine = """
      <asset-clip ref="a1" offset="0s" start="0s" duration="10s">
        <timeMap>
          <timept time="0s" value="0s" interp="smooth2"/>
          <timept time="5s" value="10s" interp="smooth2"/>
        </timeMap>
      </asset-clip>
      <asset-clip ref="a2" offset="10s" start="0s" duration="10s"/>
    """
    by_name = {m.name: m for m in _read(tmp_path, spine).media}
    assert by_name["MIC A"].placements[0].unsupported == ("timeMap",)
    assert by_name["MIC B"].placements[0].unsupported == ()


def test_a_conform_rate_clip_is_flagged(tmp_path):
    spine = """
      <asset-clip ref="v1" offset="0s" start="0s" duration="10s">
        <conform-rate srcFrameRate="29.97" scaleEnabled="1"/>
      </asset-clip>
    """
    assert _read(tmp_path, spine).media[0].placements[0].unsupported == ("conform-rate",)


def test_what_is_attached_to_a_retimed_clip_is_in_its_retimed_time(tmp_path):
    spine = """
      <clip offset="0s" start="0s" duration="10s">
        <timeMap><timept time="0s" value="0s" interp="linear"/></timeMap>
        <asset-clip ref="v1" offset="0s" start="0s" duration="10s"/>
        <asset-clip ref="a1" lane="-1" offset="0s" start="0s" duration="10s"/>
      </clip>
    """
    tl = _read(tmp_path, spine)
    assert all(m.placements[0].unsupported == ("timeMap",) for m in tl.media)


# ------------------------------------------------------------------ skipped


def test_titles_captions_generators_and_video_effects_are_counted(tmp_path):
    spine = """
      <asset-clip ref="v1" offset="0s" start="0s" duration="10s">
        <filter-video ref="fx1" name="Blur"/>
        <filter-video ref="fx1" name="Colour"/>
      </asset-clip>
      <title ref="fx1" offset="10s" duration="3s" name="Lower third"/>
      <title ref="fx1" offset="13s" duration="3s" name="Credits"/>
      <caption offset="16s" duration="2s" name="Subtitle"/>
      <video ref="fx1" offset="18s" duration="2s"/>
    """
    tl = _read(tmp_path, spine)
    assert tl.skipped == {"caption": 1, "filter-video": 2, "generator": 1, "title": 2}
    assert [m.name for m in tl.media] == ["CAM"]  # none of them became media


def test_a_timeline_with_nothing_to_report_has_nothing_skipped(tmp_path):
    spine = '<asset-clip ref="a1" offset="0s" start="0s" duration="10s"/>'
    assert _read(tmp_path, spine).skipped == {}


# --------------------------------------------------------- exact rationals


def test_the_times_of_real_exports_are_kept_exactly(tmp_path):
    """``vertical2.fcpxmld``: 1001/30000, 100/2500 and an audio base of 5644800."""
    spine = """
      <asset-clip ref="a1" offset="1001/30000s" start="3/5644800s"
                  duration="100/2500s"/>
      <asset-clip ref="a2" offset="100/2500s" start="1001/30000s"
                  duration="5644800/5644800s"/>
    """
    placements = {m.name: m.placements[0] for m in _read(tmp_path, spine).media}
    first, second = placements["MIC A"], placements["MIC B"]
    assert first.offset == Fraction(1001, 30000)
    assert first.start == Fraction(3, 5644800)
    assert first.duration == Fraction(1, 25)
    assert second.offset == Fraction(1, 25)
    assert second.duration == 1
    # A time that is mapped keeps its exactness too.
    assert first.source_at(first.end) == Fraction(3, 5644800) + Fraction(1, 25)


def test_a_two_hour_timeline_is_exact_to_the_last_frame(tmp_path):
    """1440 clips of 5.005 s: 5005/1000 is 150150 units of 1/30000 s.

    The sum of a thousand fractions must not drift: the last clip starts at
    exactly 1439 clips and ends at exactly 1440.
    """
    unit = Fraction(1001, 30000) * 150  # 150 frames at 29.97
    count = 1440
    clips = "".join(
        f'<asset-clip ref="{"a1" if i % 2 == 0 else "a2"}" '
        f'offset="{(unit * i).numerator}/{(unit * i).denominator}s" start="0s" '
        f'duration="{unit.numerator}/{unit.denominator}s"/>'
        for i in range(count)
    )
    tl = _read(tmp_path, clips)
    placements = sorted(
        (p for m in tl.media for p in m.placements), key=lambda p: p.offset
    )
    assert len(placements) == count
    assert placements[-1].offset == unit * (count - 1)
    assert placements[-1].end == unit * count
    assert tl.end == unit * count
    assert tl.end > 7200  # two hours and a bit
    # Neighbours meet exactly: no gap and no overlap from rounding.
    assert all(a.end == b.offset for a, b in pairwise(placements))


# --------------------------------------------------------------- the spine


def test_the_spine_lists_the_top_level_items_and_placements_name_theirs(fixture_dir):
    """A cut container is a top-level spine item; a placement says which one it is in.

    ``Timeline.spine`` is what a writer cuts: the items on the spine itself, not
    the clips attached to them or the media inside them. Everything attached to
    or inside a spine item belongs to it.
    """
    tl = read_fcpxml(str(fixture_dir / "project.fcpxml"))
    assert [(i.id, i.kind, i.name, i.offset, i.start, i.duration) for i in tl.spine] == [
        (0, "asset-clip", "WIDE", 0, 1, 35),
    ]
    # The camera, both closes and both mics hang off that one spine clip.
    assert {p.container for m in tl.media for p in m.placements} == {0}


def test_a_multicam_project_has_one_spine_item_per_part(fixture_dir):
    tl = read_fcpxml(str(fixture_dir / "multicam.fcpxml"))
    assert [(i.id, i.kind, i.offset, i.duration) for i in tl.spine] == [
        (0, "mc-clip", 0, 18),
        (1, "mc-clip", 18, 18),
    ]
    by_part = {}
    for m in tl.media:
        for p in m.placements:
            by_part.setdefault(p.container, set()).add(p.offset)
    assert by_part == {0: {0}, 1: {18}}


def test_spine_items_are_zero_based_and_include_gaps_and_titles(tmp_path):
    spine = """
      <gap name="Black" offset="3600s" start="3600s" duration="2s"/>
      <asset-clip ref="a1" name="Voice" offset="3602s" start="10s" duration="5s"/>
      <title ref="fx1" name="Credits" offset="3607s" duration="3s"/>
    """
    tl = _read(tmp_path, spine, tc_start="3600s")
    assert [(i.id, i.kind, i.name, i.offset) for i in tl.spine] == [
        (0, "gap", "Black", 0),
        (1, "asset-clip", "Voice", 2),
        (2, "title", "Credits", 7),
    ]
    assert tl.media[0].placements[0].container == 1


def test_a_sync_clip_has_no_spine_and_no_container(fixture_dir):
    tl = read_fcpxml(str(fixture_dir / "sync.fcpxml"))
    assert tl.spine == []
    assert {p.container for m in tl.media for p in m.placements} == {None}
