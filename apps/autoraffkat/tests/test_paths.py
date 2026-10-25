"""Polkumääritysten testit kehitysympäristössä ja PyInstaller-paketissa."""

import sys

import pytest

from autoraffkat import i18n, paths


def test_get_resource_path_dev_mode():
    """Kehitystilassa staattiset tiedostot löytyvät paketin sisältä."""
    static_dir = paths.get_resource_path("server/static")
    assert static_dir.exists()
    assert (static_dir / "index.html").exists()
    assert (static_dir / "app.js").exists()


def test_get_resource_path_frozen_mode(monkeypatch, tmp_path):
    """PyInstaller-paketissa (_MEIPASS määritelty) polku ratkaistaan väliaikaishakemistosta."""
    fake_meipass = tmp_path / "meipass_test"
    fake_meipass.mkdir()
    fake_static = fake_meipass / "server" / "static"
    fake_static.mkdir(parents=True)
    (fake_static / "index.html").write_text("<html></html>", encoding="utf-8")

    monkeypatch.setattr(sys, "_MEIPASS", str(fake_meipass), raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    resolved = paths.get_resource_path("server/static")
    assert resolved == fake_static
    assert (resolved / "index.html").exists()


def test_get_app_dir_dev_vs_frozen(monkeypatch, tmp_path):
    """App-hakemiston haku palauttaa oikean juuren."""
    app_dir = paths.get_app_dir()
    assert app_dir.exists()

    fake_exec = tmp_path / "bin" / "autoraffkat"
    fake_exec.parent.mkdir(parents=True)
    fake_exec.touch()

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_exec))

    frozen_app_dir = paths.get_app_dir()
    assert frozen_app_dir == fake_exec.parent


def test_get_app_icon_path_mac(monkeypatch):
    """macOS-alustalla palautetaan .icns tai .png-kuvakepolku."""
    monkeypatch.setattr(sys, "platform", "darwin")
    icon = paths.get_app_icon_path()
    assert icon is not None
    assert icon.exists()
    assert icon.suffix in (".icns", ".png")


def test_get_app_icon_path_windows(monkeypatch):
    """Windows-alustalla palautetaan .ico-kuvakepolku."""
    monkeypatch.setattr(sys, "platform", "win32")
    icon = paths.get_app_icon_path()
    assert icon is not None
    assert icon.exists()
    assert icon.suffix == ".ico"


def test_get_app_icon_path_frozen(monkeypatch, tmp_path):
    """Pakattuna haetaan kuvake _MEIPASS-hakemistosta."""
    fake_meipass = tmp_path / "meipass_icon_test"
    fake_assets = fake_meipass / "assets"
    fake_assets.mkdir(parents=True)
    (fake_assets / "autoraffkat.icns").touch()
    (fake_assets / "autoraffkat.ico").touch()

    monkeypatch.setattr(sys, "_MEIPASS", str(fake_meipass), raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "darwin")

    icon = paths.get_app_icon_path()
    assert icon == fake_assets / "autoraffkat.icns"


def test_the_export_can_be_opened_in_final_cut(tmp_path, monkeypatch):
    """Viennin ainoa jatko on tuonti, joten se on nappi eikä käsin kopiointi.

    Nappi ei saa olla hiljainen: jos ``open`` epäonnistuu — Final Cutia ei
    ole — käyttäjä saa syyn eikä onnistuneen näköistä painallusta.
    """
    import sys

    from fastapi.testclient import TestClient

    from autoraffkat.server import app as server_app
    from autoraffkat.server.app import AppState, create_app

    source = tmp_path / "a.fcpxml"
    source.write_text("<x/>", encoding="utf-8")
    out = tmp_path / "a-cut.fcpxml"
    out.write_text("<x/>", encoding="utf-8")
    state = AppState(xml_path=str(source))
    state.remember(str(out))  # sovelluksen oma vienti: vain sellainen avataan
    client = TestClient(create_app(state))

    calls = []

    class Done:
        returncode = 0
        stderr = ""

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(server_app.subprocess, "run",
                        lambda cmd, **kw: calls.append(cmd) or Done())
    assert client.post("/api/final-cut", json={"path": str(out)}).json() == {"ok": True}
    assert calls == [["open", "-a", "Final Cut Pro", str(out)]]

    # Puuttuva tiedosto ei ole onnistuminen.
    gone = tmp_path / "ei.xml"
    state.remember(str(gone))
    missing = client.post("/api/final-cut", json={"path": str(gone)})
    assert missing.status_code == 404

    class Failed:
        returncode = 1
        stderr = "Unable to find application"

    monkeypatch.setattr(server_app.subprocess, "run", lambda cmd, **kw: Failed())
    broken = client.post("/api/final-cut", json={"path": str(out)})
    assert broken.status_code == 400
    assert "Unable to find" in broken.json()["detail"]


@pytest.mark.parametrize("url", ["/api/final-cut", "/api/reveal"])
def test_only_files_the_app_wrote_can_be_opened_or_revealed(url, tmp_path, monkeypatch):
    """Nappi avaa viennin, ei mitä tahansa levyn tiedostoa.

    Palvelin kuuntelee paikallista porttia, ja mikä tahansa sille kirjoittava
    sivu voisi pyytää ``open``ia millä polulla tahansa. Luotettu joukko on
    «polut jotka palvelin itse kirjoitti», ei hakemisto: lähde-XML ja sen
    media voivat olla missä tahansa, mutta ne eivät ole viennin tulos.
    """
    import sys

    from fastapi.testclient import TestClient

    from autoraffkat.server import app as server_app
    from autoraffkat.server.app import AppState, create_app

    source = tmp_path / "a.fcpxml"
    source.write_text("<x/>", encoding="utf-8")
    state = AppState(xml_path=str(source))
    client = TestClient(create_app(state))

    calls = []

    class Done:
        returncode = 0
        stderr = ""

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(server_app.subprocess, "run",
                        lambda cmd, **kw: calls.append(cmd) or Done())

    # Olemassa oleva mutta kirjoittamaton tiedosto, myös se jonka sovellus on lukenut.
    stranger = tmp_path / "vieras.txt"
    stranger.write_text("x", encoding="utf-8")
    for path in (str(stranger), str(source)):
        refused = client.post(url, json={"path": path})
        assert refused.status_code == 403, path
        assert refused.json()["detail"] == i18n.t("export.not_written")
    assert calls == []

    # Polku joka kiertää rekisterin symbolisella linkillä ei ole sama kuin kirjattu.
    out = tmp_path / "a-cut.fcpxml"
    out.write_text("<x/>", encoding="utf-8")
    state.remember(str(out))
    link = tmp_path / "linkki.fcpxml"
    link.symlink_to(stranger)
    assert client.post(url, json={"path": str(link)}).status_code == 403
    assert client.post(url, json={"path": str(out)}).status_code == 200
    assert len(calls) == 1


@pytest.mark.parametrize("url", ["/api/final-cut", "/api/reveal"])
def test_an_empty_or_nul_path_is_a_missing_file(url, tmp_path):
    from fastapi.testclient import TestClient

    from autoraffkat.server.app import AppState, create_app

    client = TestClient(create_app(AppState(xml_path=str(tmp_path / "a.fcpxml"))))
    for bad in ("", "  ", "a\0b.fcpxml"):
        response = client.post(url, json={"path": bad})
        assert response.status_code == 404, repr(bad)
        assert response.json()["detail"] == i18n.t("export.file_missing")


def test_open_takes_a_nul_path_as_a_translated_error(tmp_path):
    """Virheteksti on käännetty: ``read.file_missing`` puuttui katalogista.

    Käyttäjä luki avaimen sellaisenaan, eikä mikään testi huomannut sitä.
    """
    from fastapi.testclient import TestClient

    from autoraffkat.server.app import AppState, create_app

    client = TestClient(create_app(AppState(xml_path=str(tmp_path / "a.fcpxml"))))
    for bad in ("", "a\0b.fcpxml", str(tmp_path / "ei-ole.fcpxml")):
        response = client.post("/api/open", json={"path": bad})
        assert response.status_code == 400, repr(bad)
        assert "read.file_missing" not in response.json()["detail"], repr(bad)


def test_open_is_not_limited_to_the_working_directory(tmp_path, monkeypatch):
    """Lähde-XML voi olla missä tahansa: Finderin valinta ei ole nykyisessä hakemistossa.

    Hakemistorajaus rikkoisi juuri tavallisen käytön eikä suojaisi mitään,
    koska avaus lukee vain XML:ää eikä aja polkua.
    """
    from fastapi.testclient import TestClient

    from autoraffkat.server.app import AppState, create_app

    elsewhere = tmp_path / "toinen"
    elsewhere.mkdir()
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    xml = elsewhere / "jakso.fcpxml"
    xml.write_text("<x/>", encoding="utf-8")
    state = AppState(xml_path=str(tmp_path / "a.fcpxml"))
    client = TestClient(create_app(state))
    assert client.post("/api/open", json={"path": str(xml)}).status_code == 200
    assert state.xml_path == str(xml)


def test_the_lookup_is_exact_and_answers_with_the_servers_own_string(tmp_path):
    """Pyynnön polkua ei käytetä polkuna: vain täsmälleen kirjattu merkkijono kelpaa.

    Käyttöliittymä lähettää takaisin sen merkkijonon jonka palvelin antoi, joten
    normalisointi (``realpath``) ei ole tarpeen. Se oli juuri se kohta jossa
    pyynnön arvo kosketti tiedostojärjestelmää, ja vastauksena on kirjattu
    merkkijono eikä pyynnön oma.
    """
    from autoraffkat.server.app import AppState

    real = tmp_path / "oikea"
    real.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    (real / "a-cut.fcpxml").write_text("<x/>", encoding="utf-8")
    given = str(real / "a-cut.fcpxml")

    state = AppState(xml_path=str(tmp_path / "a.fcpxml"))
    state.remember(given)
    assert state.written_path(given) == given
    assert state.written_path(str(alias / "a-cut.fcpxml")) == ""
    assert state.written_path(str(real / ".." / "oikea" / "a-cut.fcpxml")) == ""
    assert state.written_path(str(real / "toinen.fcpxml")) == ""
    assert state.written_path("") == ""
    assert state.written_path("a\0b") == ""
    state.remember("a\0b")
    state.remember("")
    assert state.written == {given}


def test_the_pan_amount_is_not_a_setting():
    """Panorointi on päällä tai pois, ei liukusäädin.

    «Kuinka paljon panorointia» on kysymys johon käyttäjällä ei ole
    vastausta: se on juuri se numero jonka tämä työkalu on olemassa
    päättämään, ja säätimenä se olisi vastuun siirto. Leveys on siis
    ``staging.PAN_WIDTH``, ei asetus — tämä testi kaatuu jos sellainen
    ilmestyy takaisin.
    """
    from autoraffkat import staging
    from autoraffkat.model import Globals, TrackConfig

    assert not [f for f in Globals.__dataclass_fields__ if "pan" in f
                and f != "panning"]
    assert not [f for f in TrackConfig.__dataclass_fields__ if "pan" in f]
    assert isinstance(Globals().panning, bool)
    # Leveys on koodissa ja mitattavissa, ei tiedostossa.
    assert staging.PAN_WIDTH[2] > 0


def test_panning_inherited_from_settings_still_measures():
    """Kytkin käynnistää otoksen vain päälle vaihtaessa.

    Asetuksista peritty «panorointi päällä» ei siis mittaisi koskaan
    mitään, ja vienti kirjoittaisi nolla panorointia kertomatta siitä —
    tämän projektin tyypillisin vika. Lataus käynnistää otoksen itse.
    """
    import inspect

    from autoraffkat.server import app as server_app

    source = inspect.getsource(server_app.AppState._analyze)
    assert "start_seating" in source, "lataus ei käynnistä otosta"
    assert "panning" in source


def test_wants_video_measurement_covers_reactions_and_vertical():
    """Reaktiot ja pystyvienti lukevat samaa ``video_tables``-taulukkoa.

    ``_analyze`` ja ``measure_seating`` tarkistivat ennen kumpikin pelkkää
    ``reactions``-lippua päättäessään tarvitaanko video_tables perinnän
    jälkeen. Pystyvienti jäi tarkistamatta kummastakin paikasta erikseen:
    asetuksista peritty «pystyvienti päällä» ei siis mitannut mitään
    latauksessa, ja vienti pyysi painamaan «Mittaa kuva» käsin vaikka
    kytkin oli jo päällä — sama vikaluokka kuin panoroinnilla yllä.
    """
    from autoraffkat.model import Globals
    from autoraffkat.project import ProjectSettings
    from autoraffkat.server.app import AppState

    state = AppState(xml_path="")
    for reactions, vertical, expected in (
        (False, False, False),
        (True, False, True),
        (False, True, True),
        (True, True, True),
    ):
        state.settings = ProjectSettings(
            globals=Globals(reactions=reactions, vertical=vertical)
        )
        assert state._wants_video_measurement() is expected, (reactions, vertical)


def test_analyze_and_seating_check_video_need_through_one_place():
    """Kolmas video_tables-kuluttaja ei saa unohtua taas kahdesta paikasta
    erikseen: molempien on kutsuttava samaa ``video_missing``ia, joka kysyy
    ``_wants_video_measurement``ilta mitä tarvitaan ja lisäksi pystyviennin
    joukkotaulukot — ne jäivät muuten mittaamatta kun lähikuvat oli jo
    mitattu."""
    import inspect

    from autoraffkat.server import app as server_app

    for name in ("_analyze", "measure_seating"):
        source = inspect.getsource(getattr(server_app.AppState, name))
        assert "video_missing" in source, name
    helper = inspect.getsource(server_app.AppState.video_missing)
    assert "_wants_video_measurement" in helper
