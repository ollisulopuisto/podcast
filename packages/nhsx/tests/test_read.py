"""Testit NHSX-parserille."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from nhsx import NhsxError, Session, read, tracks


def test_read_simple_nhsx():
    """Perus-NHSX-tiedoston luku."""
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<Session>
  <AudioPool Path="">
    <File Id="1" Name="test.wav" Path="test.wav"/>
  </AudioPool>
  <Tracks>
    <Track Name="Speaker1">
      <Region Ref="1" Start="0.000" Length="10.000" Offset="0.000"/>
    </Track>
  </Tracks>
</Session>"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".nhsx", delete=False) as f:
        f.write(xml)
        f.flush()
        session = read(f.name)

    assert isinstance(session, Session)
    assert len(session.files) == 1
    assert session.files[0].id == "1"
    assert session.files[0].name == "test.wav"
    assert len(session.tracks) == 1
    assert session.tracks[0].name == "Speaker1"
    assert len(session.tracks[0].regions) == 1
    region = session.tracks[0].regions[0]
    assert region.ref == "1"
    assert region.start == 0.0
    assert region.length == 10.0
    assert region.offset == 0.0


def test_read_multiple_regions():
    """Useampi alue samalla raidalla."""
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<Session>
  <AudioPool Path="">
    <File Id="1" Name="test.wav" Path="test.wav"/>
  </AudioPool>
  <Tracks>
    <Track Name="Speaker1">
      <Region Ref="1" Start="0.000" Length="5.000" Offset="0.000"/>
      <Region Ref="1" Start="10.000" Length="5.000" Offset="5.000"/>
    </Track>
  </Tracks>
</Session>"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".nhsx", delete=False) as f:
        f.write(xml)
        f.flush()
        session = read(f.name)

    track = session.tracks[0]
    assert len(track.regions) == 2
    assert track.regions[0].start == 0.0
    assert track.regions[1].start == 10.0
    assert track.regions[0].offset == 0.0
    assert track.regions[1].offset == 5.0


def test_read_multiple_tracks():
    """Useampi raita."""
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<Session>
  <AudioPool Path="">
    <File Id="1" Name="mic1.wav" Path="mic1.wav"/>
    <File Id="2" Name="mic2.wav" Path="mic2.wav"/>
  </AudioPool>
  <Tracks>
    <Track Name="Speaker1">
      <Region Ref="1" Start="0.000" Length="10.000" Offset="0.000"/>
    </Track>
    <Track Name="Speaker2">
      <Region Ref="2" Start="0.000" Length="10.000" Offset="0.000"/>
    </Track>
  </Tracks>
</Session>"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".nhsx", delete=False) as f:
        f.write(xml)
        f.flush()
        session = read(f.name)

    assert len(session.tracks) == 2
    assert session.tracks[0].name == "Speaker1"
    assert session.tracks[1].name == "Speaker2"


def test_time_to_seconds():
    from nhsx import time_to_seconds
    assert time_to_seconds("0") == 0.0
    assert time_to_seconds("1.5") == 1.5
    assert time_to_seconds("1:30") == 90.0
    assert time_to_seconds("1:23:45") == 5025.0


def test_time_to_seconds_invalid():
    from nhsx import time_to_seconds
    with pytest.raises(ValueError):
        time_to_seconds("")
    with pytest.raises(ValueError):
        time_to_seconds("invalid")
    with pytest.raises(ValueError):
        time_to_seconds("1:2:3:4")


def test_time_to_seconds_omitted_is_zero():
    from nhsx import time_to_seconds
    assert time_to_seconds(None) == 0.0


def test_tracks_conversion():
    """Testaa Session -> Track-muunnos."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Luo dummy-tiedosto jotta locate löytää sen
        dummy_wav = Path(tmpdir) / "test.wav"
        dummy_wav.write_bytes(b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80\xBB\x00\x00\x00\xEE\x02\x00\x04\x00\x10\x00data\x00\x00\x00\x00")

        xml = """<?xml version="1.0" encoding="UTF-8"?>
    <Session>
      <AudioPool Path="">
        <File Id="1" Name="test.wav" Path="test.wav"/>
      </AudioPool>
      <Tracks>
        <Track Name="Speaker1">
          <Region Ref="1" Start="0.000" Length="10.000" Offset="0.000"/>
          <Region Ref="1" Start="20.000" Length="5.000" Offset="0.000"/>
        </Track>
      </Tracks>
    </Session>"""
        nhsx_path = Path(tmpdir) / "test.nhsx"
        nhsx_path.write_text(xml)
        session = read(str(nhsx_path))

        # tracks() vaatii tiedoston olemassaolon, joten skip probe
        result = tracks(session, extra_dir=tmpdir, with_probe=False)
        assert len(result) == 1
        track = result[0]
        assert track.speaker == "Speaker1"
        assert track.mono is True
        assert len(track.spans) == 2
        assert track.spans[0].programme_start == 0.0
        assert track.spans[0].programme_end == 10.0
        assert track.spans[0].file_offset == 0.0
        assert track.spans[1].programme_start == 20.0
        assert track.spans[1].programme_end == 25.0
        assert track.spans[1].file_offset == 0.0


def test_tracks_to_speechmix():
    """Testaa Track -> speechmix.Track muunnos."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Luo dummy-tiedosto jotta locate löytää sen
        dummy_wav = Path(tmpdir) / "test.wav"
        dummy_wav.write_bytes(b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80\xBB\x00\x00\x00\xEE\x02\x00\x04\x00\x10\x00data\x00\x00\x00\x00")

        xml = """<?xml version="1.0" encoding="UTF-8"?>
    <Session>
      <AudioPool Path="">
        <File Id="1" Name="test.wav" Path="test.wav"/>
      </AudioPool>
      <Tracks>
        <Track Name="Speaker1">
          <Region Ref="1" Start="0.000" Length="10.000" Offset="0.000"/>
        </Track>
      </Tracks>
    </Session>"""
        nhsx_path = Path(tmpdir) / "test.nhsx"
        nhsx_path.write_text(xml)
        session = read(str(nhsx_path))

        result = tracks(session, extra_dir=tmpdir, with_probe=False)
        assert len(result) == 1
        sm_track = result[0].to_speechmix()

        from speechmix.timeline import Span as SmSpan
        from speechmix.timeline import Track as SmTrack
        assert isinstance(sm_track, SmTrack)
        assert sm_track.speaker == "Speaker1"
        assert sm_track.mono is True
        assert len(sm_track.spans) == 1
        assert isinstance(sm_track.spans[0], SmSpan)
        assert sm_track.spans[0].programme_start == 0.0
        assert sm_track.spans[0].programme_end == 10.0
        assert sm_track.spans[0].file_offset == 0.0


def test_read_missing_file():
    """Ei-olemassa oleva tiedosto nostaa NhsxError."""
    with pytest.raises(NhsxError):
        read("/does/not/exist.nhsx")


def test_read_invalid_xml():
    """Virheellinen XML nostaa NhsxError."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".nhsx", delete=False) as f:
        f.write("not xml")
        f.flush()
        with pytest.raises(NhsxError):
            read(f.name)


def test_read_no_audio_pool_no_tracks():
    """Ilman AudioPoolia eikä raitoja nostaa virheen."""
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<Session></Session>"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".nhsx", delete=False) as f:
        f.write(xml)
        f.flush()
        with pytest.raises(NhsxError):
            read(f.name)


def test_probe_honours_ffprobe_path(tmp_path, monkeypatch):
    """``from ..binaries`` on podcast-magicin polku; tässä paketissa binaries
    on sisarus, ja ImportError nieltiin niin että probe oli aina (0, 0)."""
    fake = tmp_path / "ffprobe"
    fake.write_text(
        "#!/bin/sh\n"
        'echo \'{"streams":[{"bits_per_sample":"24","channels":2}]}\'\n',
        encoding="utf-8",
    )
    fake.chmod(0o755)
    monkeypatch.setenv("FFPROBE_PATH", str(fake))
    wav = tmp_path / "x.wav"
    wav.write_bytes(b"x")
    from nhsx.pipeline import probe

    assert probe(str(wav)) == (24, 2)


def test_read_does_not_resolve_external_entities(tmp_path):
    """Istunto on käyttäjän tiedosto. Entiteetti ei saa lukea levyä."""
    secret = tmp_path / "secret.txt"
    secret.write_text("LEAKME", encoding="utf-8")
    nhsx_path = tmp_path / "evil.nhsx"
    nhsx_path.write_text(
        f"""<?xml version="1.0"?>
<!DOCTYPE Session [
  <!ENTITY xxe SYSTEM "{secret.as_uri()}">
]>
<Session>
  <AudioPool Path="">
    <File Id="1" Name="a.wav" Path="a.wav">&xxe;</File>
  </AudioPool>
  <Tracks>
    <Track Name="t"><Region Ref="1" Start="0" Length="1"/></Track>
  </Tracks>
</Session>
""",
        encoding="utf-8",
    )
    try:
        session = read(nhsx_path)
    except NhsxError:
        return
    leaked = "LEAKME" in "".join(
        [(f.name or "") + (f.path or "") + ((f.elem.text or "") if f.elem is not None else "")
         for f in session.files]
    )
    assert not leaked


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
