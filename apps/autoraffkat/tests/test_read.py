"""Lukijan sovitin: se mikä autoraffkat lisää `fcpxml`-paketin lukijaan.

Itse lukija ja sen testit ovat paketissa (`packages/fcpxml/tests`): aikajanat,
laneilla olevat kamerat ja mikit, monikamera, vaiennetut roolit, raitojen
ryhmittely. Täällä on vain se mikä on sovelluksen: käännetty virhe,
ruutunopeus ffprobesta, uudelleenlinkitys ja oletusnimi.
"""

from fractions import Fraction

import pytest

from autoraffkat.finalcut.read import ReadError, read_fcpxml


def test_bad_root_is_a_translated_error(tmp_path):
    path = tmp_path / "x.fcpxml"
    path.write_text("<notfcpxml/>")
    with pytest.raises(ReadError) as caught:
        read_fcpxml(str(path))
    assert caught.value.code == "bad_root"
    assert str(caught.value) == "Juurielementti on <notfcpxml>, odotettiin <fcpxml>."


def test_no_timeline_is_a_translated_error(tmp_path):
    path = tmp_path / "x.fcpxml"
    path.write_text('<?xml version="1.0"?><fcpxml version="1.10"><resources/></fcpxml>')
    with pytest.raises(ReadError) as caught:
        read_fcpxml(str(path))
    assert caught.value.code == "no_project"
    assert str(caught.value).startswith("XML:stä ei löytynyt projektia")


@pytest.mark.parametrize("code", ["unreadable", "bundle_without_info", "bad_time",
                                  "bad_xml", "bad_root", "no_project", "no_media"])
def test_every_code_the_package_can_raise_has_a_translation(code):
    """Tuntematon avain palautuu sellaisenaan, ja käyttäjä näkisi «read.…»."""
    from autoraffkat import i18n

    for language in ("fi", "en"):
        assert i18n.CATALOG[f"read.{code}"][language]


def test_a_bundle_without_info_names_the_bundle(tmp_path):
    bundle = tmp_path / "jakso.fcpxmld"
    bundle.mkdir()
    with pytest.raises(ReadError) as caught:
        read_fcpxml(str(bundle))
    assert str(bundle) in str(caught.value)


def test_an_unnamed_project_gets_the_finnish_default_name(tmp_path):
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<fcpxml version="1.10">
  <resources>
    <format id="r1" name="FFVideoFormat1080p25" frameDuration="1/25s" width="1920" height="1080"/>
    <asset id="r2" name="cam" hasVideo="1" format="r1" duration="10s" start="0s"/>
  </resources>
  <library><event name="E"><project>
    <sequence format="r1" duration="10s"><spine>
      <asset-clip ref="r2" offset="0s" name="cam" duration="10s" start="0s"/>
    </spine></sequence>
  </project></event></library>
</fcpxml>"""
    path = tmp_path / "unnamed.fcpxml"
    path.write_text(xml, encoding="utf-8")
    assert read_fcpxml(str(path)).name == "Projekti"


def test_missing_files_are_sent_to_relink(tmp_path, monkeypatch):
    """Puuttuvat tiedostot yritetään löytää uudelleen, kuten ennenkin."""
    from autoraffkat import relink

    seen = []
    monkeypatch.setattr(
        relink, "relink_timeline", lambda tl, xml_path: seen.append((tl, xml_path))
    )
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<fcpxml version="1.10">
  <resources>
    <format id="r1" name="FFVideoFormat1080p25" frameDuration="1/25s" width="1920" height="1080"/>
    <asset id="r2" name="cam" src="file:///net/missing/cam.mp4" hasVideo="1" format="r1" duration="10s" start="0s"/>
  </resources>
  <library><event name="E"><project name="P">
    <sequence format="r1" duration="10s"><spine>
      <asset-clip ref="r2" offset="0s" name="cam" duration="10s" start="0s"/>
    </spine></sequence>
  </project></event></library>
</fcpxml>"""
    path = tmp_path / "missing.fcpxml"
    path.write_text(xml, encoding="utf-8")
    tl = read_fcpxml(str(path))
    assert [(t is tl, p) for t, p in seen] == [(True, str(path))]


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
