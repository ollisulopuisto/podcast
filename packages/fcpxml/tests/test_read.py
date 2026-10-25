"""The reader, carried over from autoraffkat's ``tests/test_read.py``.

The assertions are the same as there; what changed is that an error is a stable
``code`` rather than a translated text, and that the frame-rate probe is a hook
the caller passes instead of an import of ffprobe.
"""

from __future__ import annotations

from fractions import Fraction

import pytest
import xml_fixtures
from fcpxml import ReadError, read_fcpxml


def test_sync_clip(fixture_dir):
    tl = read_fcpxml(str(fixture_dir / "sync.fcpxml"))
    assert tl.kind == "sync-clip"
    assert tl.frame_duration == Fraction(1, 25)
    assert [m.key for m in tl.media] == [
        "WIDE.mp4",
        "CLOSE_A.mp4",
        "CLOSE_B.mp4",
        "MIC_A.wav",
        "MIC_B.wav",
    ]
    wide = tl.media[0]
    assert wide.has_video and not wide.has_audio
    assert wide.width == 1920 and wide.height == 1080
    assert wide.placements[0].offset == 0


def test_project_offsets_are_relative_to_parent_start(fixture_dir):
    """An attached clip's offset is in the host's local time, not the timeline's."""
    tl = read_fcpxml(str(fixture_dir / "project.fcpxml"))
    assert tl.kind == "project"
    for item in tl.media:
        placement = item.placements[0]
        assert placement.offset == 0, item.key
        assert placement.start == 1  # the spine clip has start=25/25s
        assert placement.duration == 35


def test_file_time_mapping(fixture_dir):
    tl = read_fcpxml(str(fixture_dir / "project.fcpxml"))
    mic = next(m for m in tl.media if m.key == "MIC_A.wav")
    # Timeline moment 0 is second 1 of the file, because the spine starts at start=1s.
    assert mic.file_time_at(Fraction(0)) == 1
    assert mic.file_time_at(Fraction(10)) == 11
    assert mic.file_time_at(Fraction(100)) is None


def test_bad_root(tmp_path):
    path = tmp_path / "x.fcpxml"
    path.write_text("<notfcpxml/>")
    with pytest.raises(ReadError) as caught:
        read_fcpxml(str(path))
    assert caught.value.code == "bad_root"
    assert caught.value.detail == "notfcpxml"


def test_no_timeline(tmp_path):
    path = tmp_path / "x.fcpxml"
    path.write_text('<?xml version="1.0"?><fcpxml version="1.10"><resources/></fcpxml>')
    with pytest.raises(ReadError) as caught:
        read_fcpxml(str(path))
    assert caught.value.code == "no_project"


def test_multicam_groups_angles_across_parts(fixture_dir):
    """Two parts, five angles: ten assets but five tracks."""
    tl = read_fcpxml(str(fixture_dir / "multicam.fcpxml"))
    assert tl.kind == "multicam"
    assert len(tl.media) == 10
    assert [t.key for t in tl.tracks] == [
        "WIDE",
        "CLOSE_A",
        "CLOSE_B",
        "host Track1",
        "guest Track2",
    ]
    for track in tl.tracks:
        assert len(track.media_keys) == 2, track.key
        # The track's span covers both parts, not only the second.
        assert tl.track_span(track.key) == (0, 36)


def test_multicam_content_is_clipped_to_its_part(fixture_dir):
    """An angle's content is the whole multicam's length; the mc-clip cuts it."""
    tl = read_fcpxml(str(fixture_dir / "multicam.fcpxml"))
    by_key = tl.media_by_key()
    first, second = by_key["WIDE 01.mp4"], by_key["WIDE 02.mp4"]
    assert [(p.offset, p.duration) for p in first.placements] == [(0, 18)]
    assert [(p.offset, p.duration) for p in second.placements] == [(18, 18)]
    # The parts must not overlap, or an envelope would line up wrongly.
    assert first.timeline_end == second.timeline_start


def test_multicam_angle_gap_shifts_source_time(fixture_dir):
    """A gap at the start of an angle shifts the source time, not the timeline."""
    tl = read_fcpxml(str(fixture_dir / "multicam.fcpxml"))
    wide = tl.media_by_key()["WIDE 02.mp4"]  # part B has a one-second gap
    assert wide.file_time_at(Fraction(18)) == 18
    assert wide.file_time_at(Fraction(30)) == 30


def test_multicam_records_its_parts(fixture_dir):
    tl = read_fcpxml(str(fixture_dir / "multicam.fcpxml"))
    assert [(mc.offset, mc.duration, mc.start) for mc in tl.multicams] == [
        (0, 18, 0),
        (18, 18, 18),
    ]
    assert all(len(mc.angle_ids) == 5 for mc in tl.multicams)


@pytest.mark.parametrize(
    ("src", "expected"),
    [
        ("file:///Users/jakso%202/host%20%5Bmix%5D.wav", "/Users/jakso 2/host [mix].wav"),
        ("file:///Users/%C3%A4%C3%A4ni/host.wav", "/Users/ääni/host.wav"),
        ("file://localhost/Users/jakso/host.wav", "/Users/jakso/host.wav"),
        ("/Volumes/plain/path.wav", "/Volumes/plain/path.wav"),
        ("", ""),
    ],
)
def test_a_file_url_becomes_a_decoded_path(src, expected):
    from fcpxml import read as reader

    assert reader._src_to_path(src) == expected


def test_windows_path_survives_the_url_round_trip(monkeypatch):
    """A Windows path does not go into a file URL as it is.

    ``"file://" + r"C:\\..."`` read the whole path as the URL's netloc and left
    the path empty: no media file was found. The conversion is per platform, so
    the Windows one is run here on every platform -- else a regression would
    show only in a Windows CI run.
    """
    import nturl2path

    from fcpxml import read as reader

    monkeypatch.setattr(xml_fixtures, "pathname2url", nturl2path.pathname2url)
    monkeypatch.setattr(reader, "url2pathname", nturl2path.url2pathname)

    path = r"C:\Users\ohjaaja\jakso 2\host [mix].wav"
    url = xml_fixtures.file_url(path)
    assert url == "file:///C:/Users/ohjaaja/jakso%202/host%20%5Bmix%5D.wav"
    assert reader._src_to_path(url) == path

    # A network share is ``file://server/share``: the server belongs to the path,
    # it is not left in the URL's host field.
    unc = r"\\arkisto\kuvat\host.mov"
    assert reader._src_to_path(xml_fixtures.file_url(unc)) == unc


def _two_cameras_declared_25(tmp_path):
    cam_a = tmp_path / "cam_a.mp4"
    cam_b = tmp_path / "cam_b.mp4"
    for dummy in (cam_a, cam_b):
        dummy.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<fcpxml version="1.10">
  <resources>
    <format id="r1" name="FFVideoFormat1080p25" frameDuration="1/25s" width="1920" height="1080"/>
    <asset id="r2" name="cam_a" src="file://{cam_a}" hasVideo="1" format="r1" duration="10s" start="0s"/>
    <asset id="r3" name="cam_b" src="file://{cam_b}" hasVideo="1" format="r1" duration="10s" start="0s"/>
  </resources>
  <library>
    <event name="Event">
      <project name="Project">
        <sequence format="r1" duration="10s">
          <spine>
            <asset-clip ref="r2" offset="0s" name="cam_a" duration="10s" start="0s"/>
            <asset-clip ref="r3" offset="0s" name="cam_b" duration="10s" start="0s"/>
          </spine>
        </sequence>
      </project>
    </event>
  </library>
</fcpxml>"""
    path = tmp_path / "project_declared_25.fcpxml"
    path.write_text(xml, encoding="utf-8")
    return path


def test_probed_media_rate_overrides_declared_frame_duration(tmp_path):
    """The media always beats the rate the XML's format declares.

    60 fps material can be exported as the XML of a 25 fps project: the format
    claims 1/25s, but a file cannot. The reader asks the caller's probe for the
    first video file that exists, and the probed rate replaces the declaration
    of both the sequence and the asset formats -- else an export writes a 25 fps
    timeline of 60 fps material.
    """
    path = _two_cameras_declared_25(tmp_path)
    probed = []

    def probe(item):
        probed.append(item.name)
        return Fraction(1, 60)

    tl = read_fcpxml(str(path), probe_frame_duration=probe)
    assert tl.frame_duration == Fraction(1, 60)
    assert probed == ["cam_a"]  # the first file that answers is enough
    # The format's false 1/25 must not stay in the other asset's data: an export
    # writes the asset format from it, and Final Cut would conform the file to
    # the wrong rate.
    by_name = {m.name: m for m in tl.media}
    assert by_name["cam_a"].frame_duration == Fraction(1, 60)
    assert by_name["cam_b"].frame_duration == Fraction(1, 60)


def test_without_a_probe_the_declared_frame_duration_stands(tmp_path):
    path = _two_cameras_declared_25(tmp_path)
    assert read_fcpxml(str(path)).frame_duration == Fraction(1, 25)


def test_a_probe_that_knows_nothing_leaves_the_declared_frame_duration_alone(tmp_path):
    """Missing media must not guess a rate: the format's declaration stays."""
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<fcpxml version="1.10">
  <resources>
    <format id="r1" name="FFVideoFormat1080p25" frameDuration="1/25s" width="1920" height="1080"/>
    <asset id="r2" name="cam" src="file:///net/missing/cam.mp4" hasVideo="1" format="r1" duration="10s" start="0s"/>
  </resources>
  <library>
    <event name="Event">
      <project name="Project">
        <sequence format="r1" duration="10s">
          <spine>
            <asset-clip ref="r2" offset="0s" name="cam" duration="10s" start="0s"/>
          </spine>
        </sequence>
      </project>
    </event>
  </library>
</fcpxml>"""
    path = tmp_path / "project_missing_media.fcpxml"
    path.write_text(xml, encoding="utf-8")

    def probe(item):
        raise AssertionError(f"asked about {item.name}, whose file is not there")

    tl = read_fcpxml(str(path), probe_frame_duration=probe)
    assert tl.frame_duration == Fraction(1, 25)


def test_rate_undefined_sequence_format_falls_back_to_video_asset_frame_duration(tmp_path):
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<fcpxml version="1.10">
  <resources>
    <format id="r1" name="FFVideoFormatRateUndefined"/>
    <format id="r2" name="FFVideoFormat1080p60" frameDuration="1/60s" width="1920" height="1080"/>
    <asset id="r3" name="cam" hasVideo="1" format="r2" duration="10s" start="0s"/>
  </resources>
  <library>
    <event name="Event">
      <project name="Project">
        <sequence format="r1" duration="10s">
          <spine>
            <asset-clip ref="r3" offset="0s" name="cam" duration="10s" start="0s"/>
          </spine>
        </sequence>
      </project>
    </event>
  </library>
</fcpxml>"""
    path = tmp_path / "project_60.fcpxml"
    path.write_text(xml, encoding="utf-8")
    tl = read_fcpxml(str(path))
    assert tl.frame_duration == Fraction(1, 60)


def test_sync_source_active_0_skips_muted_camera_audio(tmp_path):
    """A sync clip deactivates the storyline's embedded camera audio.

    When the user detaches audio in FCP and removes the camera audio, a
    ``<sync-source><audio-role-source active="0"/></sync-source>`` marks the
    camera's embedded audio as inactive. The reader must skip it and only pick
    up the separate mic wav.

    Reproduces the pp54 bug: project -> ref-clip -> media -> sequence ->
    spine -> clip with a sync clip whose inner camera audio is deactivated.
    """
    path = tmp_path / "sync_muted.fcpxml"
    path.write_text(xml_fixtures.SYNC_MUTED, encoding="utf-8")
    tl = read_fcpxml(str(path))
    names = [m.name for m in tl.media]
    # CAM 3's embedded audio (r4) should NOT appear: it is muted.
    assert "CAM 3" not in names, f"Muted camera audio should be skipped, got {names}"
    # The mic wav (r5) and the video (r3) should appear.
    assert "CAM 2" in names
    assert "mic guest" in names



def test_sync_source_muted_role_hierarchy():
    """A muted role matches downward: ``dialogue`` mutes ``dialogue.dialogue-1``."""
    from xml.etree.ElementTree import Element

    from fcpxml.read import _is_muted

    # Exact match
    e = Element("audio", role="dialogue.dialogue-1")
    assert _is_muted(e, frozenset({"dialogue.dialogue-1"}))

    # A parent mutes its sub-role
    e2 = Element("audio", role="dialogue.dialogue-1")
    assert _is_muted(e2, frozenset({"dialogue"}))

    # A sub-role does NOT mute the parent
    e3 = Element("asset-clip", audioRole="dialogue")
    assert not _is_muted(e3, frozenset({"dialogue.dialogue-1"}))

    # No match
    e4 = Element("audio", role="music.music-1")
    assert not _is_muted(e4, frozenset({"dialogue.dialogue-1"}))

    # An empty muted set
    assert not _is_muted(e, frozenset())


def test_sync_source_unmuted_audio_passes_through(tmp_path):
    """Audio asset-clips NOT covered by active='0' are kept normally."""
    xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<fcpxml version="1.14">
  <resources>
    <format id="r1" name="FFVideoFormat1080p25" frameDuration="100/2500s"
            width="1920" height="1080"/>
    <asset id="r2" name="CAM" start="0s" duration="50s"
           hasVideo="1" format="r1" hasAudio="1"
           videoSources="1" audioSources="1" audioChannels="2"
           audioRate="48000"/>
    <asset id="r3" name="MIC" start="0s" duration="50s"
           hasAudio="1" audioSources="1" audioChannels="1"
           audioRate="48000"/>
  </resources>
  <library>
    <event name="E">
      <project name="P">
        <sequence format="r1" duration="50s" tcStart="0s">
          <spine>
            <sync-clip offset="0s" name="Sync" start="0s" duration="50s">
              <clip offset="0s" name="CAM" start="0s" duration="50s">
                <video ref="r2" offset="0s" start="0s" duration="50s"/>
              </clip>
              <asset-clip ref="r3" lane="-1" offset="0s" name="MIC"
                          duration="50s" audioRole="dialogue"/>
              <!-- No sync-source with active="0": both should appear -->
            </sync-clip>
          </spine>
        </sequence>
      </project>
    </event>
  </library>
</fcpxml>"""
    path = tmp_path / "sync_unmuted.fcpxml"
    path.write_text(xml, encoding="utf-8")
    tl = read_fcpxml(str(path))
    names = [m.name for m in tl.media]
    assert "CAM" in names
    assert "MIC" in names


def test_video_only_timeline_element_strips_has_audio(tmp_path):
    """When an asset on the timeline only appears as <video>, has_audio is False.

    When the user detaches and deletes audio in FCP, FCP writes <video ref="...">.
    The asset container may still declare hasAudio="1" because the MP4 has an
    audio track, but on this timeline it is purely picture.
    """
    xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<fcpxml version="1.14">
  <resources>
    <format id="r1" name="FFVideoFormat1080p25" frameDuration="100/2500s"
            width="1920" height="1080"/>
    <asset id="r2" name="CAM" start="0s" duration="50s"
           hasVideo="1" format="r1" hasAudio="1"
           videoSources="1" audioSources="1" audioChannels="2"
           audioRate="48000"/>
    <asset id="r3" name="MIC" start="0s" duration="50s"
           hasAudio="1" audioSources="1" audioChannels="1"
           audioRate="48000"/>
  </resources>
  <library>
    <event name="E">
      <project name="P">
        <sequence format="r1" duration="50s" tcStart="0s">
          <spine>
            <clip offset="0s" name="CAM" start="0s" duration="50s">
              <video ref="r2" offset="0s" start="0s" duration="50s"/>
              <asset-clip ref="r3" lane="-1" offset="0s" name="MIC"
                          duration="50s" audioRole="dialogue"/>
            </clip>
          </spine>
        </sequence>
      </project>
    </event>
  </library>
</fcpxml>"""
    path = tmp_path / "detached.fcpxml"
    path.write_text(xml, encoding="utf-8")
    tl = read_fcpxml(str(path))
    by_name = {m.name: m for m in tl.media}
    assert by_name["CAM"].has_video is True
    assert by_name["CAM"].has_audio is False
    assert by_name["MIC"].has_video is False
    assert by_name["MIC"].has_audio is True


def test_synced_angles_split_into_a_camera_and_a_mic(tmp_path):
    """An angle that is a sync clip (camera + mic) is two tracks, not one.

    Final Cut's usual workflow: a camera and a mic are synced in pairs and the
    pairs make the multicam. Grouped by angle, the camera and the mic were one
    card that could not take two roles; angle 2 was the guest's mic in part 1
    and Mikko's in part 2; and Mikko's part 2 file was on two tracks, which is
    twice in the export.
    """
    path = tmp_path / "synced.fcpxml"
    xml_fixtures.write_synced_multicam_xml(str(path), str(tmp_path))
    tl = read_fcpxml(str(path))

    tracks = {t.key: t for t in tl.tracks}
    assert {k: t.media_keys for k, t in tracks.items()} == {
        "FOCUS CAM 1": ["FOCUS CAM 1 01.mp4", "FOCUS CAM 1 02.mp4"],
        "FOCUS CAM 2": ["FOCUS CAM 2 01.mp4", "FOCUS CAM 2 02.mp4"],
        "FOCUS CAM 3": ["FOCUS CAM 3 01.mp4", "FOCUS CAM 3 02.mp4"],
        "Tomi": ["Tomi_001.wav", "Tomi_002.wav"],
        "Vieras": ["Vieras_001.wav"],
        "Mikko": ["Mikko_001.wav", "Mikko_002.wav"],
    }
    assert all(t.has_video for k, t in tracks.items() if k.startswith("FOCUS"))
    assert not any(t.has_video for k, t in tracks.items() if not k.startswith("FOCUS"))
    # In part 2 Mikko is in two angles; an export picks one of them.
    assert sorted(tracks["Mikko"].angle_ids) == ["P1A3", "P2A2", "P2A3"]
    assert sorted(tracks["FOCUS CAM 2"].angle_ids) == ["P1A2", "P2A2"]
    assert tl.track_span("Vieras") == (0, 18)


def test_mics_are_grouped_across_parts_by_any_part_counter():
    """The part number is not always ``_001``.

    Recorders and people number differently. An ungrouped mic still works --
    two cards for one speaker -- but its role is not inherited by the next
    episode and the card is not recognised as the same.
    """
    from fcpxml.read import _group_sounds

    files = [
        ("Tomi 1", "osa1"), ("ZOOM0001_Tr2", "osa1"), ("Vieras-A", "osa1"),
        ("Tomi 2", "osa2"), ("ZOOM0002_Tr2", "osa2"), ("Vieras-B", "osa2"),
        ("Tomi_001", "osa3"), ("Solo", "osa3"),
    ]
    stems = [name for name, _ in files]
    groups = _group_sounds(stems, [{o} for _, o in files])
    assert sorted((name, sorted(stems[i] for i in members))
                  for name, members in groups) == [
        ("Solo", ["Solo"]),
        ("Tomi", ["Tomi 1", "Tomi 2", "Tomi_001"]),
        ("Vieras", ["Vieras-A", "Vieras-B"]),
        ("ZOOM Tr2", ["ZOOM0001_Tr2", "ZOOM0002_Tr2"]),
    ]


def test_an_ambiguous_counter_is_not_guessed():
    """Two mics in one part with the same pattern: no telling which carries on.

    ``Mic 1`` and ``Mic 2`` in part 1, ``Mic 3`` in part 2 -- which of them is
    the same mic as ``Mic 3``? A guess would merge two people into one track;
    as separate tracks they are only one card too many.
    """
    from fcpxml.read import _group_sounds

    groups = _group_sounds(["Mic 1", "Mic 2", "Mic 3"], [{"a"}, {"a"}, {"b"}])
    assert sorted(members for _, members in groups) == [[0], [1], [2]]


def test_synced_mics_with_other_counters_become_one_track(tmp_path):
    names = {("Tomi", 1): "Tomi 1", ("Tomi", 2): "Tomi 2",
             ("Mikko", 1): "ZOOM0001_Tr2", ("Mikko", 2): "ZOOM0002_Tr2",
             ("Vieras", 1): "Vieras-A"}
    path = tmp_path / "names.fcpxml"
    xml_fixtures.write_synced_multicam_xml(str(path), str(tmp_path), names=names)
    tracks = {t.key: t.media_keys for t in read_fcpxml(str(path)).tracks
              if not t.has_video}
    assert tracks == {
        "Tomi": ["Tomi 1.wav", "Tomi 2.wav"],
        "Vieras A": ["Vieras-A.wav"],
        "ZOOM Tr2": ["ZOOM0001_Tr2.wav", "ZOOM0002_Tr2.wav"],
    }
