import json
import os

from autoraffkat import project
from autoraffkat.model import Globals, TrackConfig
from autoraffkat.project import ProjectSettings


def test_round_trip(tmp_path):
    xml = tmp_path / "jakso.fcpxml"
    xml.write_text("<fcpxml/>")
    settings = project.ProjectSettings(
        tracks={
            "MIC_A.wav": TrackConfig(
                role="mic", speaker="Host", sensitivity_db=9.5, gain_db=-3.0
            )
        },
        globals=Globals(min_shot=4.0, overlap_rule="louder"),
    )
    project.save(str(xml), settings)
    again = project.load(str(xml))
    assert again.tracks["MIC_A.wav"].speaker == "Host"
    assert again.tracks["MIC_A.wav"].sensitivity_db == 9.5
    assert again.globals.min_shot == 4.0
    assert again.globals.overlap_rule == "louder"


def test_settings_live_next_to_xml(tmp_path):
    xml = tmp_path / "jakso.fcpxml"
    assert project.settings_path(str(xml)) == str(tmp_path / "jakso.autoraffkat.json")
    assert project.default_output_path(str(xml)) == str(tmp_path / "jakso-cut.fcpxml")


def test_export_never_overwrites_an_earlier_cut(tmp_path):
    """Edellinen vienti on jo Final Cutissa; sen päälle ei kirjoiteta."""
    xml = tmp_path / "jakso.fcpxml"
    assert project.next_output_path(str(xml)) == str(tmp_path / "jakso-cut.fcpxml")

    (tmp_path / "jakso-cut.fcpxml").write_text("<fcpxml/>")
    assert project.next_output_path(str(xml)) == str(tmp_path / "jakso-cut v2.fcpxml")

    (tmp_path / "jakso-cut v2.fcpxml").write_text("<fcpxml/>")
    assert project.next_output_path(str(xml)) == str(tmp_path / "jakso-cut v3.fcpxml")


def test_broken_file_does_not_block(tmp_path):
    xml = tmp_path / "jakso.fcpxml"
    xml.write_text("<fcpxml/>")
    (tmp_path / "jakso.autoraffkat.json").write_text("{ rikki")
    assert project.load(str(xml)).globals.min_shot == Globals().min_shot


def test_unknown_keys_are_ignored(tmp_path):
    xml = tmp_path / "jakso.fcpxml"
    xml.write_text("<fcpxml/>")
    (tmp_path / "jakso.autoraffkat.json").write_text(
        '{"version": 99, "globals": {"min_shot": 3, "tuntematon": 1}, '
        '"tracks": {"a": {"role": "mic", "outo": true}}}'
    )
    settings = project.load(str(xml))
    assert settings.globals.min_shot == 3
    assert settings.tracks["a"].role == "mic"


def _write_settings(path, tracks, min_shot=2.5):
    """Asetustiedosto suoraan levylle, ilman lähde-XML:ää."""
    settings = ProjectSettings(
        tracks={k: TrackConfig(**v) for k, v in tracks.items()},
        globals=Globals(min_shot=min_shot),
    )
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(settings.to_json(), fh)
    return path


def test_previous_is_found_beside_and_above(tmp_path):
    """Sarjan edellinen jakso on joko naapurissa tai naapuripaketissa."""
    bundle = tmp_path / "jakso54.fcpxmld"
    bundle.mkdir()
    xml = bundle / "Info.fcpxml"
    older = tmp_path / "jakso53.fcpxmld"
    older.mkdir()
    previous = _write_settings(
        older / "Info.autoraffkat.json", {"CAM 1": {"role": "close", "speaker": "Host"}}
    )
    assert project.find_previous(str(xml)) == str(previous)


def test_previous_ignores_our_own_settings(tmp_path):
    xml = tmp_path / "jakso.fcpxml"
    _write_settings(tmp_path / "jakso.autoraffkat.json", {"CAM 1": {"role": "wide"}})
    assert project.find_previous(str(xml)) is None


def test_previous_takes_the_newest(tmp_path):
    xml = tmp_path / "uusi.fcpxml"
    old = _write_settings(tmp_path / "a.autoraffkat.json", {"CAM 1": {"role": "wide"}})
    new = _write_settings(tmp_path / "b.autoraffkat.json", {"CAM 1": {"role": "close"}})
    os.utime(old, (1_000_000, 1_000_000))
    assert project.find_previous(str(xml)) == str(new)


def test_broken_settings_read_as_none(tmp_path):
    path = tmp_path / "rikki.autoraffkat.json"
    path.write_text("{ ei tätä voi lukea", encoding="utf-8")
    assert project.read(str(path)) is None
    assert project.read(str(tmp_path / "ei-ole.json")) is None


def test_bundle_keeps_its_derived_files_outside(tmp_path):
    """Final Cutin paketin sisään ei kirjoiteta mitään."""
    bundle = tmp_path / "episode 12.fcpxmld"
    bundle.mkdir()
    xml = str(bundle / "Info.fcpxml")
    # Nimi tulee paketista, ei sen sisällön Info-tiedostosta.
    assert project.settings_path(xml) == str(tmp_path / "episode 12.autoraffkat.json")
    assert project.default_output_path(xml) == str(tmp_path / "episode 12-cut.fcpxml")
    for path in (project.settings_path(xml), project.default_output_path(xml)):
        assert not os.path.dirname(path).endswith(".fcpxmld")


def test_plain_xml_is_unchanged(tmp_path):
    xml = str(tmp_path / "jakso.fcpxml")
    assert project.settings_path(xml) == str(tmp_path / "jakso.autoraffkat.json")
    assert project.default_output_path(xml) == str(tmp_path / "jakso-cut.fcpxml")


def test_settings_left_inside_a_bundle_are_still_read(tmp_path):
    """Vanhat asetukset paketin sisällä eivät katoa, mutta uudet menevät ulos."""
    bundle = tmp_path / "episode 12.fcpxmld"
    bundle.mkdir()
    xml = str(bundle / "Info.fcpxml")
    _write_settings(
        bundle / "Info.autoraffkat.json", {"CAM 1": {"role": "wide"}}, min_shot=7.0
    )
    loaded = project.load(xml)
    assert loaded.tracks["CAM 1"].role == "wide"
    assert loaded.globals.min_shot == 7.0

    written = project.save(xml, loaded)
    assert written == str(tmp_path / "episode 12.autoraffkat.json")


# ------------------------------------------------- viennin nimi kertoo tyylin


def test_export_name_carries_the_edit_style(tmp_path):
    """Final Cutin selaimessa on monta leikkausta samasta jaksosta.

    Nimi on ainoa mikä niistä erottaa: «jakso-cut» ja «jakso-cut v2» eivät
    kerro kumpi oli se nopea.
    """
    xml = tmp_path / "jakso.fcpxml"
    settings = ProjectSettings(globals=Globals(rhythm="hectic"))
    assert project.name_tag(settings) == "hectic"
    assert project.next_output_path(str(xml), "hectic") == str(
        tmp_path / "jakso-cut hectic.fcpxml"
    )


def test_name_tag_mentions_the_defaults_only_once(tmp_path):
    """Oletukset eivät ansaitse sanaa; poikkeamat ansaitsevat."""
    assert project.name_tag(ProjectSettings()) == "broadcast"

    settings = ProjectSettings(
        globals=Globals(
            rhythm="custom",
            min_shot=3.0,
            overlap_rule="louder",
            long_take_rule="stay",
        )
    )
    settings.audio.enabled = True
    assert project.name_tag(settings) == "custom 3s louder stay audio"


def test_name_tags_can_be_turned_off(tmp_path):
    xml = tmp_path / "jakso.fcpxml"
    settings = ProjectSettings(globals=Globals(name_tags=False, rhythm="hectic"))
    assert project.name_tag(settings) == ""
    assert project.next_output_path(str(xml), "") == str(tmp_path / "jakso-cut.fcpxml")


def test_each_style_is_numbered_on_its_own(tmp_path):
    """Numero erottaa saman tyylin viennit, ei eri tyylejä toisistaan."""
    xml = tmp_path / "jakso.fcpxml"
    (tmp_path / "jakso-cut hectic.fcpxml").write_text("<fcpxml/>")
    assert project.next_output_path(str(xml), "hectic") == str(
        tmp_path / "jakso-cut hectic v2.fcpxml"
    )
    assert project.next_output_path(str(xml), "mellow") == str(
        tmp_path / "jakso-cut mellow.fcpxml"
    )


def test_the_shown_name_distinguishes_exports():
    """Final Cut näyttää projektin nimen, ei tiedostonimeä.

    Tiedostonimi numeroidaan jotta valmiin leikkauksen päälle ei kirjoiteta,
    mutta selaimessa se ei näy — ja ilman erottelua kaikki tuonnit ovat
    samannimisiä eikä niistä näe kumpi on uudempi tai mistä tiedostosta
    kumpikin tuli.
    """
    from autoraffkat.project import fcp_project_name

    # Ensimmäinen vienti ilman tagia: nimi sellaisenaan, ei turhaa koristetta.
    assert fcp_project_name("Rough cut", "/x/jakso-cut.fcpxml") == "Rough cut"
    # Tagi ja numero erottavat.
    assert (
        fcp_project_name("Rough cut", "/x/jakso-cut broadcast audio v8.fcpxml")
        == "Rough cut · broadcast audio v8"
    )
    assert fcp_project_name("Rough cut", "/x/jakso-cut v3.fcpxml") == "Rough cut · v3"
    # Peräkkäiset viennit eroavat toisistaan, mikä on koko pointti.
    names = {
        fcp_project_name("Rough cut", f"/x/jakso-cut broadcast v{n}.fcpxml")
        for n in range(2, 6)
    }
    assert len(names) == 4


def test_two_exports_to_the_same_path_are_still_told_apart():
    """Nimen erottelu ei saa nojata siihen mitä levylle jäi.

    `next_output_path` numeroi vasta silloin kun edellinen vienti on yhä
    paikallaan. Tuotu vienti siirretään arkistoon tai poistetaan — se on
    tavallista eikä väärin — ja seuraava vienti saa silloin saman
    tiedostonimen, saman tunnuksen ja saman projektin nimen. Final Cutissa
    on kaksi samannimistä projektia eikä kumpikaan kerro kummasta on kyse.

    Vika on hiljainen: tiedosto on kelvollinen, tuonti onnistuu, ja nimi
    näyttää oikealta yksinään katsottuna.
    """
    from autoraffkat.project import fcp_project_name

    path = "/x/jakso-cut broadcast audio.fcpxml"
    first = fcp_project_name("Rough cut", path, stamp="28.8. 9:09")
    second = fcp_project_name("Rough cut", path, stamp="28.8. 11:41")
    assert first != second, (first, second)
    assert "28.8. 9:09" in first


def test_the_export_stamps_the_name_it_writes():
    """Sovellus antaa leiman, ei vain voisi antaa.

    Valinnainen parametri jota kutsuja ei anna on sama kuin parametria ei
    olisi, ja juuri tässä funktiossa se tarkoittaa taas kahta samannimistä
    projektia.
    """
    import inspect

    from autoraffkat.server import app as server_app

    source = inspect.getsource(server_app)
    at = source.index("fcp_project_name(")
    assert "stamp=" in source[at : at + 200], "vienti ei anna leimaa"


def test_the_stamp_does_not_mangle_the_clock():
    """Nollien riisuminen merkkijonosta osuu myös kellonaikaan.

    `strftime("%d.%m. %H:%M")` antaa «01.09. 10:05», ja siitä nollat pois
    siivoava `replace(".0", ".")` teki «1.9. 10:5» — väärä kellonaika kerran
    kymmenessä minuutissa, eikä mikään kaadu.
    """
    import time as _time

    from autoraffkat.project import stamp_now

    when = _time.struct_time((2026, 9, 1, 10, 5, 0, 1, 244, -1))
    assert stamp_now(when) == "1.9. 10:05"
    noon = _time.struct_time((2026, 12, 28, 9, 9, 0, 0, 363, -1))
    assert stamp_now(noon) == "28.12. 9:09"


def test_name_tag_mentions_micro_movement(tmp_path):
    """Liike on tyylivalinta joka vaihtaa koko leikkauksen luonteen.

    Samasta jaksosta syntyy nyt kaksi tiedostoa, ja pelkkä numerointi ei
    kerro kumpi niistä liikkuu: «jakso-cut v2» ja «jakso-cut move v2»
    eroavat vasta nimessä, joka on se mikä Final Cutin selaimessa näkyy.
    """
    xml = tmp_path / "jakso.fcpxml"
    plain = ProjectSettings()
    moved = ProjectSettings(globals=Globals(movement=True))
    assert project.name_tag(plain) == "broadcast"
    assert project.name_tag(moved) == "broadcast move"
    assert project.next_output_path(str(xml), "broadcast move") == str(
        tmp_path / "jakso-cut broadcast move.fcpxml"
    )
