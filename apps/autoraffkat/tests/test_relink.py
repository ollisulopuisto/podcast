from fractions import Fraction
from pathlib import Path

from autoraffkat.fcpxml.read import Timeline
from autoraffkat.model import MediaItem
from autoraffkat.relink import find_search_roots, relink_file, relink_timeline


def test_relink_exact_basename(tmp_path):
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    real_file = media_dir / "wancke a Track1-Combo 1.wav"
    real_file.write_bytes(b"RIFF dummy wav data")

    missing_path = "/Old/Path/To/wancke a Track1-Combo 1.wav"
    found = relink_file(missing_path, search_roots=[tmp_path])
    assert found == str(real_file.resolve())


def test_relink_relative_path_in_subfolder(tmp_path):
    sub = tmp_path / "vertailu" / "B-lufs20"
    sub.mkdir(parents=True)
    real_file = sub / "nyman a Track2-Combo 2 [mix].wav"
    real_file.write_bytes(b"RIFF dummy wav data")

    missing_path = "/Users/dst/Dropbox/podcastit/peter peter/peter peter 53/vertailu/B-lufs20/nyman a Track2-Combo 2 [mix].wav"
    found = relink_file(missing_path, search_roots=[tmp_path])
    assert found == str(real_file.resolve())


def test_relink_variant_mix_tag(tmp_path):
    real_file = tmp_path / "nyman a Track2-Combo 2 [mix].wav"
    real_file.write_bytes(b"RIFF dummy wav data")

    missing_path = "/Old/nyman a Track2-Combo 2.wav"
    found = relink_file(missing_path, search_roots=[tmp_path])
    assert found == str(real_file.resolve())


def test_relink_discriminates_parts_and_speakers(tmp_path):
    file_nyman_a = tmp_path / "nyman a Track2-Combo 2.wav"
    file_nyman_b = tmp_path / "nyman b Track2-Combo 2.wav"
    file_wancke_a = tmp_path / "wancke a Track1-Combo 1.wav"
    file_wancke_b = tmp_path / "wancke b Track1-Combo 1.wav"
    for f in (file_nyman_a, file_nyman_b, file_wancke_a, file_wancke_b):
        f.write_bytes(b"RIFF")

    assert relink_file("/missing/nyman a Track2-Combo 2 [mix].wav", [tmp_path]) == str(file_nyman_a.resolve())
    assert relink_file("/missing/nyman b Track2-Combo 2 [mix].wav", [tmp_path]) == str(file_nyman_b.resolve())
    assert relink_file("/missing/wancke a Track1-Combo 1 [mix].wav", [tmp_path]) == str(file_wancke_a.resolve())
    assert relink_file("/missing/wancke b Track1-Combo 1 [mix].wav", [tmp_path]) == str(file_wancke_b.resolve())


def test_relink_fuzzy_naming(tmp_path):
    real_file = tmp_path / "nyman_a_Track2_Combo_2.wav"
    real_file.write_bytes(b"RIFF")

    missing_path = "/Users/dst/podcast/nyman a Track2-Combo 2.wav"
    found = relink_file(missing_path, search_roots=[tmp_path])
    assert found == str(real_file.resolve())


def test_relink_timeline(tmp_path):
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    real_nyman = audio_dir / "nyman a Track2-Combo 2.wav"
    real_nyman.write_bytes(b"RIFF")
    real_wancke = audio_dir / "wancke a Track1-Combo 1.wav"
    real_wancke.write_bytes(b"RIFF")

    xml_file = tmp_path / "episode.fcpxml"
    xml_file.write_text("<fcpxml/>")

    item1 = MediaItem(
        key="nyman a Track2-Combo 2.wav",
        name="nyman a Track2-Combo 2.wav",
        path="/old/path/nyman a Track2-Combo 2.wav",
        src="file:///old/path/nyman%20a%20Track2-Combo%202.wav",
        has_audio=True,
    )
    item2 = MediaItem(
        key="wancke a Track1-Combo 1.wav",
        name="wancke a Track1-Combo 1.wav",
        path="/old/path/wancke a Track1-Combo 1.wav",
        src="file:///old/path/wancke%20a%20Track1-Combo%201.wav",
        has_audio=True,
    )

    tl = Timeline(
        media=[item1, item2],
        frame_duration=Fraction(1, 25),
        kind="project",
        name="Test",
        source_path=str(xml_file),
    )

    relinked = relink_timeline(tl, xml_path=str(xml_file))
    assert len(relinked) == 2
    assert item1.path == str(real_nyman.resolve())
    assert item2.path == str(real_wancke.resolve())


def test_find_search_roots(tmp_path):
    sub = tmp_path / "bundle.fcpxmld"
    sub.mkdir()
    xml_file = sub / "Info.fcpxml"
    xml_file.write_text("<fcpxml/>")

    roots = find_search_roots(str(xml_file))
    resolved_roots = [str(r.resolve()) for r in roots]
    assert str(sub.resolve()) in resolved_roots
    assert str(tmp_path.resolve()) in resolved_roots


def test_relink_user_prompt_scenario(tmp_path):
    """Test the exact 8 missing files from user prompt in various moved subfolders."""
    # Suppose files are moved into a new episode structure
    ep_dir = tmp_path / "peter peter 53 usa sota"
    vertailu_dir = ep_dir / "vertailu" / "B-lufs20"
    vertailu_dir.mkdir(parents=True)

    f1 = vertailu_dir / "nyman a Track2-Combo 2 [mix].wav"
    f2 = vertailu_dir / "nyman b Track2-Combo 2 [mix].wav"
    f3 = vertailu_dir / "wancke a Track1-Combo 1 [mix].wav"
    f4 = vertailu_dir / "wancke b Track1-Combo 1 [mix].wav"
    f5 = ep_dir / "nyman a Track2-Combo 2.wav"
    f6 = ep_dir / "nyman b Track2-Combo 2.wav"
    f7 = ep_dir / "wancke a Track1-Combo 1.wav"
    f8 = ep_dir / "wancke b Track1-Combo 1.wav"

    for f in (f1, f2, f3, f4, f5, f6, f7, f8):
        f.write_bytes(b"RIFF dummy wav")

    # Old missing paths pointing to an old Dropbox path
    old_base = "/Users/dst/Dropbox/podcastit/peter peter/peter peter 53 usa sota - 2026-08-18"
    old_paths = [
        f"{old_base}/vertailu/B-lufs20/nyman a Track2-Combo 2 [mix].wav",
        f"{old_base}/vertailu/B-lufs20/nyman b Track2-Combo 2 [mix].wav",
        f"{old_base}/vertailu/B-lufs20/wancke a Track1-Combo 1 [mix].wav",
        f"{old_base}/vertailu/B-lufs20/wancke b Track1-Combo 1 [mix].wav",
        f"{old_base}/nyman a Track2-Combo 2.wav",
        f"{old_base}/nyman b Track2-Combo 2.wav",
        f"{old_base}/wancke a Track1-Combo 1.wav",
        f"{old_base}/wancke b Track1-Combo 1.wav",
    ]

    for old_p, expected_f in zip(old_paths, (f1, f2, f3, f4, f5, f6, f7, f8), strict=True):
        found = relink_file(old_p, search_roots=[ep_dir])
        assert found == str(expected_f.resolve()), f"Failed to match {old_p}"


def test_api_relink_endpoint(tmp_path):
    import tempfile

    from fastapi.testclient import TestClient

    from autoraffkat.server.app import AppState, create_app

    with tempfile.TemporaryDirectory() as outside_tmp:
        outside_dir = Path(outside_tmp)
        real_file = outside_dir / "wancke a Track1-Combo 1.wav"
        real_file.write_bytes(b"RIFF")

        xml_file = tmp_path / "test.fcpxml"
        xml_file.write_text("""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE fcpxml>
<fcpxml version="1.10">
  <resources>
    <format id="r1" frameDuration="1/25s" width="1920" height="1080"/>
    <asset id="r2" name="wancke a Track1-Combo 1.wav" src="file:///some/distant/missing/wancke%20a%20Track1-Combo%201.wav" hasAudio="1" format="r1"/>
  </resources>
  <library>
    <event name="Event">
      <project name="Project">
        <sequence format="r1" duration="10s">
          <spine>
            <asset-clip ref="r2" offset="0s" duration="10s" format="r1"/>
          </spine>
        </sequence>
      </project>
    </event>
  </library>
</fcpxml>
""")

        state = AppState(xml_path=str(xml_file))
        state.load()
        app = create_app(state)
        client = TestClient(app)

        # First verify track is reported as missing
        state_res = client.get("/api/state").json()
        assert state_res["tracks"][0]["missing"] is True

        # Relink with explicit search dir
        res = client.post("/api/relink", json={"search_dir": str(outside_dir)})
        assert res.status_code == 200
        data = res.json()
        assert data["ok"] is True
        assert data["relinked"] >= 1

        # After relink, path points to real_file
        assert state.timeline.media[0].path == str(real_file.resolve())
