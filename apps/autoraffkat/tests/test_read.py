from fractions import Fraction

import pytest

from autoraffkat.fcpxml.read import ReadError, read_fcpxml


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
    """Liitetyn klipin offset on isännän paikallisessa ajassa, ei aikajanan."""
    tl = read_fcpxml(str(fixture_dir / "project.fcpxml"))
    assert tl.kind == "project"
    for item in tl.media:
        placement = item.placements[0]
        assert placement.offset == 0, item.key
        assert placement.start == 1  # spinellä start=25/25s
        assert placement.duration == 35


def test_file_time_mapping(fixture_dir):
    tl = read_fcpxml(str(fixture_dir / "project.fcpxml"))
    mic = next(m for m in tl.media if m.key == "MIC_A.wav")
    # Aikajanan hetki 0 vastaa tiedoston sekuntia 1, koska spine alkaa start=1s.
    assert mic.file_time_at(Fraction(0)) == 1
    assert mic.file_time_at(Fraction(10)) == 11
    assert mic.file_time_at(Fraction(100)) is None


def test_bad_root(tmp_path):
    path = tmp_path / "x.fcpxml"
    path.write_text("<notfcpxml/>")
    with pytest.raises(ReadError):
        read_fcpxml(str(path))


def test_no_timeline(tmp_path):
    path = tmp_path / "x.fcpxml"
    path.write_text('<?xml version="1.0"?><fcpxml version="1.10"><resources/></fcpxml>')
    with pytest.raises(ReadError):
        read_fcpxml(str(path))


def test_multicam_groups_angles_across_parts(fixture_dir):
    """Kaksi osaa, viisi kulmaa: kymmenen assettia mutta viisi raitaa."""
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
        # Raidan väli kattaa molemmat osat, ei vain jälkimmäistä.
        assert tl.track_span(track.key) == (0, 36)


def test_multicam_content_is_clipped_to_its_part(fixture_dir):
    """Kulman sisältö on koko multicamin pituinen, mc-clip rajaa sen."""
    tl = read_fcpxml(str(fixture_dir / "multicam.fcpxml"))
    by_key = tl.media_by_key()
    first, second = by_key["WIDE 01.mp4"], by_key["WIDE 02.mp4"]
    assert [(p.offset, p.duration) for p in first.placements] == [(0, 18)]
    assert [(p.offset, p.duration) for p in second.placements] == [(18, 18)]
    # Osat eivät saa mennä päällekkäin, muuten verhokäyrä kohdistuisi väärin.
    assert first.timeline_end == second.timeline_start


def test_multicam_angle_gap_shifts_source_time(fixture_dir):
    """Kulman alussa oleva aukko siirtää lähdeaikaa, ei aikajanaa."""
    tl = read_fcpxml(str(fixture_dir / "multicam.fcpxml"))
    wide = tl.media_by_key()["WIDE 02.mp4"]  # osassa B sekunnin aukko
    assert wide.file_time_at(Fraction(18)) == 18
    assert wide.file_time_at(Fraction(30)) == 30


def test_multicam_records_its_parts(fixture_dir):
    tl = read_fcpxml(str(fixture_dir / "multicam.fcpxml"))
    assert [(mc.offset, mc.duration, mc.start) for mc in tl.multicams] == [
        (0, 18, 0),
        (18, 18, 18),
    ]
    assert all(len(mc.angle_ids) == 5 for mc in tl.multicams)


def test_windows_path_survives_the_url_round_trip(monkeypatch):
    """Windowsin polku ei kelpaa file-URLiin sellaisenaan.

    ``"file://" + r"C:\\..."`` luki koko polun URLin netlociksi ja jätti polun
    tyhjäksi: yhtään mediatiedostoa ei löytynyt, ja vienti kaatui vasta
    puuttuviin tiedostoihin. Muunnos on alustakohtainen, joten Windowsin
    toteutus ajetaan tässä myös macOSissa — muuten regressio näkyisi vasta
    CI:n Windows-ajossa.
    """
    import nturl2path

    from autoraffkat.fcpxml import read as reader
    from autoraffkat.fcpxml import write as writer

    monkeypatch.setattr(writer, "pathname2url", nturl2path.pathname2url)
    monkeypatch.setattr(reader, "url2pathname", nturl2path.url2pathname)

    path = r"C:\Users\ohjaaja\jakso 2\host [mix].wav"
    url = writer.file_url(path)
    assert url == "file:///C:/Users/ohjaaja/jakso%202/host%20%5Bmix%5D.wav"
    assert reader._src_to_path(url) == path

    # Verkkolevy on ``file://palvelin/jako``: palvelin kuuluu polkuun, ei
    # URLin isäntäkenttään jätettäväksi.
    unc = r"\\arkisto\kuvat\host.mov"
    assert reader._src_to_path(writer.file_url(unc)) == unc


def test_probed_media_rate_overrides_declared_frame_duration(tmp_path, monkeypatch):
    """Media voittaa aina XML-formaatin ilmoittaman ruutunopeuden.

    60 fps -materiaalin voi viedä 25 fps -projektin XML:na: formaatti
    väittää 1/25s, mutta tiedosto ei voi. Lukija probean ensimmäisen
    löytyvän videotiedoston, ja probedoitu nopeus korvaa sekä sekvenssin
    että asset-formaattien ilmoituksen — muuten vienti kirjoittaa
    25 fps -aikajanan 60 fps -materiaalista.
    """
    import autoraffkat.probe as probe

    monkeypatch.setattr(probe, "info", lambda p: {"video": {"fps": 60.0}})

    dummy = tmp_path / "cam_a.mp4"
    dummy.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    dummy_b = tmp_path / "cam_b.mp4"
    dummy_b.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<fcpxml version="1.10">
  <resources>
    <format id="r1" name="FFVideoFormat1080p25" frameDuration="1/25s" width="1920" height="1080"/>
    <asset id="r2" name="cam_a" src="file://{dummy}" hasVideo="1" format="r1" duration="10s" start="0s"/>
    <asset id="r3" name="cam_b" src="file://{dummy_b}" hasVideo="1" format="r1" duration="10s" start="0s"/>
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
    tl = read_fcpxml(str(path))
    assert tl.frame_duration == Fraction(1, 60)
    # Formaatin valehdellut 1/25 ei saa jäädä toisen assetin tietoihin:
    # vienti kirjoittaa asset-formaatin sen perusteella, ja Final Cut
    # konformoisi tiedoston väärään tahtiin.
    by_name = {m.name: m for m in tl.media}
    assert by_name["cam_b"].frame_duration == Fraction(1, 60)


def test_missing_media_leaves_declared_frame_duration_alone(tmp_path, monkeypatch):
    """Puuttuva media ei saa arvata nopeutta: formaatin ilmoitus pysyy."""
    import autoraffkat.probe as probe

    monkeypatch.setattr(probe, "info", lambda p: {})

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
    tl = read_fcpxml(str(path))
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
    """Sync-clip deactivates the storyline's embedded camera audio.

    When the user detaches audio in FCP and removes the camera audio, a
    ``<sync-source><audio-role-source active="0"/></sync-source>`` marks
    the camera's embedded audio as inactive. The reader must skip it and
    only pick up the separate mic wav.

    Reproduces the pp54 bug: project → ref-clip → media → sequence →
    spine → clip with sync-clip whose inner camera audio is deactivated.
    """
    xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<fcpxml version="1.14">
  <resources>
    <format id="r1" name="FFVideoFormat1080p25" frameDuration="100/2500s"
            width="1920" height="1080"/>
    <media id="r2" name="Clip" uid="clip01">
      <sequence format="r1" duration="100s" tcStart="0s" tcFormat="NDF"
                audioLayout="stereo" audioRate="48k">
        <spine>
          <clip offset="0s" name="CAM 2" start="0s" duration="100s">
            <video ref="r3" offset="0s" start="0s" duration="100s"/>
            <sync-clip lane="-1" offset="0s" name="CAM 3 - Sync"
                       start="0s" duration="100s">
              <clip offset="0s" name="CAM 3" start="0s" duration="100s">
                <gap name="Gap" offset="0s" start="0s" duration="100s">
                  <audio ref="r4" lane="-1" offset="0s" start="0s"
                         duration="100s" role="dialogue.dialogue-1"
                         srcCh="1, 2"/>
                </gap>
                <asset-clip ref="r5" lane="-1" offset="0s"
                            name="mic guest" duration="100s"
                            format="r6" audioRole="dialogue"/>
              </clip>
              <sync-source sourceID="storyline">
                <audio-role-source role="dialogue.dialogue-1" active="0"/>
              </sync-source>
            </sync-clip>
          </clip>
        </spine>
      </sequence>
    </media>
    <asset id="r3" name="CAM 2" start="0s" duration="100s"
           hasVideo="1" format="r1" hasAudio="1"
           videoSources="1" audioSources="1" audioChannels="2"
           audioRate="48000"/>
    <asset id="r4" name="CAM 3" start="0s" duration="100s"
           hasVideo="1" format="r1" hasAudio="1"
           videoSources="1" audioSources="1" audioChannels="2"
           audioRate="48000"/>
    <asset id="r5" name="mic guest" start="0s" duration="100s"
           hasAudio="1" audioSources="1" audioChannels="1"
           audioRate="48000"/>
    <format id="r6" name="FFVideoFormatRateUndefined"/>
  </resources>
  <library>
    <event name="Episode" uid="EVT-1">
      <project name="Episode" uid="PRJ-1">
        <sequence format="r1" duration="100s" tcStart="0s">
          <spine>
            <ref-clip ref="r2" offset="0s" name="Clip" duration="100s"/>
          </spine>
        </sequence>
      </project>
    </event>
  </library>
</fcpxml>"""
    path = tmp_path / "sync_muted.fcpxml"
    path.write_text(xml, encoding="utf-8")
    tl = read_fcpxml(str(path))
    names = [m.name for m in tl.media]
    # CAM 3's embedded audio (r4) should NOT appear — it is muted.
    assert "CAM 3" not in names, f"Muted camera audio should be skipped, got {names}"
    # The mic wav (r5) and the video (r3) should appear.
    assert "CAM 2" in names
    assert "mic guest" in names


def test_sync_source_muted_role_hierarchy(tmp_path):
    """Muted role matches hierarchically: ``dialogue`` mutes ``dialogue.dialogue-1``."""
    from xml.etree.ElementTree import Element

    from autoraffkat.fcpxml.read import _is_muted

    # Exact match
    e = Element("audio", role="dialogue.dialogue-1")
    assert _is_muted(e, frozenset({"dialogue.dialogue-1"}))

    # Parent mutes sub-role
    e2 = Element("audio", role="dialogue.dialogue-1")
    assert _is_muted(e2, frozenset({"dialogue"}))

    # Sub-role does NOT mute parent
    e3 = Element("asset-clip", audioRole="dialogue")
    assert not _is_muted(e3, frozenset({"dialogue.dialogue-1"}))

    # No match
    e4 = Element("audio", role="music.music-1")
    assert not _is_muted(e4, frozenset({"dialogue.dialogue-1"}))

    # Empty muted set
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

    When user detaches and deletes audio in FCP, FCP writes <video ref="...">.
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
    """Kulma joka on synkkaklippi (kamera + mikki) on kaksi raitaa, ei yksi.

    Final Cutin tavallinen työnkulku: kamera ja mikki tahdistetaan
    pareittain ja pareista tehdään monikamera. Kulmittain ryhmiteltynä
    kamera ja mikki olivat yksi kortti, jolle ei voinut antaa kahta
    roolia; kulma 2 oli osassa 1 vieraan mikki ja osassa 2 Mikon; ja
    Mikon osan 2 tiedosto oli kahdella raidalla, eli viennissä kahdesti.
    """
    import make_fixture

    path = tmp_path / "synced.fcpxml"
    make_fixture.write_synced_multicam_xml(str(path), str(tmp_path))
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
    # Mikko on osassa 2 kahdessa kulmassa; vienti valitsee niistä yhden.
    assert sorted(tracks["Mikko"].angle_ids) == ["P1A3", "P2A2", "P2A3"]
    assert sorted(tracks["FOCUS CAM 2"].angle_ids) == ["P1A2", "P2A2"]
    assert tl.track_span("Vieras") == (0, 18)


def test_mics_are_grouped_across_parts_by_any_part_counter():
    """Osan numero ei ole aina ``_001``.

    Tallentimet ja ihmiset numeroivat eri tavoin. Ryhmittelemätön mikki
    toimii silti — kaksi korttia samalle puhujalle — mutta rooli ei periydy
    seuraavaan jaksoon eikä korttia tunnista omaksi.
    """
    from autoraffkat.fcpxml.read import _group_sounds

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
    """Kaksi mikkiä samassa osassa, sama kaava: ei tiedetä kumpi jatkuu.

    ``Mic 1`` ja ``Mic 2`` osassa 1, ``Mic 3`` osassa 2 — kumpi niistä on
    sama mikki kuin ``Mic 3``? Arvaus yhdistäisi kaksi ihmistä yhdeksi
    raidaksi, erillisinä raitoina ne ovat vain yksi kortti liikaa.
    """
    from autoraffkat.fcpxml.read import _group_sounds

    groups = _group_sounds(["Mic 1", "Mic 2", "Mic 3"], [{"a"}, {"a"}, {"b"}])
    assert sorted(members for _, members in groups) == [[0], [1], [2]]


def test_synced_mics_with_other_counters_become_one_track(tmp_path):
    import make_fixture

    names = {("Tomi", 1): "Tomi 1", ("Tomi", 2): "Tomi 2",
             ("Mikko", 1): "ZOOM0001_Tr2", ("Mikko", 2): "ZOOM0002_Tr2",
             ("Vieras", 1): "Vieras-A"}
    path = tmp_path / "names.fcpxml"
    make_fixture.write_synced_multicam_xml(str(path), str(tmp_path), names=names)
    tracks = {t.key: t.media_keys for t in read_fcpxml(str(path)).tracks
              if not t.has_video}
    assert tracks == {
        "Tomi": ["Tomi 1.wav", "Tomi 2.wav"],
        "Vieras A": ["Vieras-A.wav"],
        "ZOOM Tr2": ["ZOOM0001_Tr2.wav", "ZOOM0002_Tr2.wav"],
    }
