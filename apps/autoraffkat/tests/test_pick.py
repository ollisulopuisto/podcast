"""Lähteen valinta. Ei palvelinta, ei mediaa — pelkkää hakemiston lukua."""

import os
import sys

import pytest

from autoraffkat import pick


def _touch(path, text="<fcpxml/>"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def test_bundle_resolves_to_its_xml(tmp_path):
    inner = _touch(str(tmp_path / "jakso.fcpxmld" / "Info.fcpxml"))
    assert pick.resolve(str(tmp_path / "jakso.fcpxmld")) == inner
    # Suora polku kelpaa sellaisenaan.
    assert pick.resolve(inner) == inner


def test_candidates_finds_both_muodot(tmp_path):
    plain = _touch(str(tmp_path / "kasin.fcpxml"))
    inner = _touch(str(tmp_path / "jakso.fcpxmld" / "Info.fcpxml"))
    assert set(pick.candidates(str(tmp_path))) == {plain, inner}


def test_own_export_is_not_a_candidate(tmp_path):
    """Silmukassa palataan lähteeseen, ei valmiiseen leikkaukseen."""
    source = _touch(str(tmp_path / "jakso.fcpxml"))
    _touch(str(tmp_path / "jakso-cut.fcpxml"))
    _touch(str(tmp_path / "jakso-cut.fcpxmld" / "Info.fcpxml"))
    # Numeroitu vienti on yhtä lailla oma tuotos.
    _touch(str(tmp_path / "jakso-cut v2.fcpxml"))
    assert pick.candidates(str(tmp_path)) == [source]


def test_old_finnish_export_is_still_recognised(tmp_path):
    """Tunnus vaihtui suomesta englanniksi, mutta levy ei tyhjentynyt.

    Aiemmat `-leikattu`-viennit ovat yhä käyttäjien hakemistoissa. Jos
    tunnuksen vaihtuminen tekisi niistä kelvollisia lähteitä, työkalu
    tarjoaisi omaa tulostaan takaisin syötteeksi eikä kukaan huomaisi ennen
    kuin leikkaus ajetaan leikatun päälle.
    """
    source = _touch(str(tmp_path / "jakso.fcpxml"))
    _touch(str(tmp_path / "jakso-leikattu.fcpxml"))
    _touch(str(tmp_path / "jakso-leikattu v2.fcpxml"))
    _touch(str(tmp_path / "jakso-leikattu.fcpxmld" / "Info.fcpxml"))
    assert pick.candidates(str(tmp_path)) == [source]


def test_candidates_are_newest_first(tmp_path):
    old = _touch(str(tmp_path / "vanha.fcpxml"))
    new = _touch(str(tmp_path / "uusi.fcpxml"))
    os.utime(old, (1_000_000, 1_000_000))
    assert pick.candidates(str(tmp_path))[0] == new


def test_label_names_the_bundle_not_its_contents(tmp_path):
    inner = _touch(str(tmp_path / "episode 12.fcpxmld" / "Info.fcpxml"))
    assert pick.label(inner) == "episode 12.fcpxmld"
    assert pick.label(str(tmp_path / "kasin.fcpxml")) == "kasin.fcpxml"


def test_single_candidate_needs_no_question(tmp_path):
    only = _touch(str(tmp_path / "jakso.fcpxml"))
    assert pick.pick(str(tmp_path)) == only


def test_without_a_terminal_nothing_is_asked(tmp_path, monkeypatch):
    """Putkessa ei saa jäädä odottamaan vastausta eikä avata ikkunaa."""
    monkeypatch.setattr(pick, "interactive", lambda: False)
    newest = _touch(str(tmp_path / "b.fcpxml"))
    older = _touch(str(tmp_path / "a.fcpxml"))
    os.utime(older, (1_000_000, 1_000_000))
    assert pick.ask([newest, older]) == newest
    assert pick.native(str(tmp_path)) is None
    # Tyhjä hakemisto ei avaa ikkunaa vaan palauttaa tyhjän.
    empty = tmp_path / "tyhja"
    empty.mkdir()
    assert pick.pick(str(empty)) is None


def test_missing_directory_is_not_an_error(tmp_path):
    assert pick.candidates(str(tmp_path / "ei-ole")) == []


@pytest.mark.skipif(
    sys.platform != "darwin",
    reason="Natiivi valintaikkuna on osascript, siis vain macOS",
)
def test_browser_gets_the_picker_from_the_server(tmp_path, monkeypatch):
    """Selaimessa ei ole tiedostovalitsinta joka antaisi polun.

    Ilman palvelimen puolen ikkunaa «Avaa XML…» ei tee selaimessa mitään eikä
    kerro miksi — juuri niin kävi. Ikkuna avautuu lähteen hakemistoon, koska
    seuraava jakso on käytännössä aina siinä.
    """
    from fastapi.testclient import TestClient

    from autoraffkat.server import app as server_app
    from autoraffkat.server.app import AppState, create_app

    source = _touch(str(tmp_path / "jakso" / "a.fcpxml"))
    chosen = _touch(str(tmp_path / "jakso" / "b.fcpxml"))
    asked = {}

    def fake_native(directory="", force=False):
        asked["directory"] = directory
        asked["force"] = force
        return chosen

    monkeypatch.setattr(server_app.pick, "native", fake_native)
    client = TestClient(create_app(AppState(xml_path=source)))
    assert client.post("/api/pick").json() == {"path": chosen}
    assert asked["directory"] == os.path.dirname(source)
    assert asked["force"] is True

    # Peruttu valinta ei ole virhe eikä saa vaihtaa tiedostoa.
    monkeypatch.setattr(server_app.pick, "native", lambda *a, **k: None)
    assert client.post("/api/pick").json() == {"path": ""}


def test_picker_says_so_when_there_is_none(tmp_path, monkeypatch):
    """Muualla kuin macOSissa ikkunaa ei ole, ja siitä on kerrottava.

    Selain saa ``unavailable``-lipun eikä tyhjää polkua: tyhjä näyttäisi
    peruutetulta valinnalta, jolloin «Avaa XML…» olisi taas se nappi joka ei
    tee mitään eikä kerro miksi.
    """
    from fastapi.testclient import TestClient

    from autoraffkat.server.app import AppState, create_app

    monkeypatch.setattr(sys, "platform", "win32")
    source = _touch(str(tmp_path / "jakso" / "a.fcpxml"))
    client = TestClient(create_app(AppState(xml_path=source)))
    assert client.post("/api/pick").json() == {"path": "", "unavailable": True}


def test_tagged_export_is_not_a_candidate(tmp_path):
    """Nimeen kirjoitetut säätimet eivät saa tehdä viennistä lähdettä."""
    source = _touch(str(tmp_path / "jakso.fcpxml"))
    _touch(str(tmp_path / "jakso-cut hectic audio.fcpxml"))
    _touch(str(tmp_path / "jakso-cut custom 2.5s louder stay v3.fcpxml"))
    assert pick.candidates(str(tmp_path)) == [source]


def test_a_foreign_word_after_the_suffix_is_still_a_source(tmp_path):
    """Tunnus tunnistaa vain omat sanansa.

    Muuten mikä tahansa «-cut»-loppuinen nimi katoaisi valikosta sen mukaan
    mitä sen perässä sattuu lukemaan.
    """
    source = _touch(str(tmp_path / "haastattelu-cut down.fcpxml"))
    assert pick.candidates(str(tmp_path)) == [source]


def test_dialog_nostetaan_eteen_ennen_kuin_osascript_ajetaan(monkeypatch):
    """Ikkuna joka jää muiden taakse näyttää jumiutuneelta työkalulta.

    Tavallinen Python-prosessi ei ole macOS:lle käyttöliittymäsovellus, joten
    ``osascript``in valintaikkuna jäi taakse ja odotti 300 s käyttäjää joka
    etsi sen Cmd+`-näppäimellä — sama vikaluokka kuin liitännäisen ikkunalla
    (``speechmix.editor``). Nosto tapahtuu jokaisen ikkunayrityksen edellä,
    ennen AppleScriptia.
    """
    jarjestys = []

    def kirjaa_eteen():
        jarjestys.append("eteen")
        return True

    vastaukset = iter([None, "", ""])  # virhe, sitten kaksi käyttäjän peruutusta

    def vale_osascript(script):
        jarjestys.append("osascript")
        return next(vastaukset)

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(pick, "interactive", lambda: True)
    monkeypatch.setattr(pick, "_ensure_foreground", kirjaa_eteen)
    monkeypatch.setattr(pick, "_osascript", vale_osascript)
    assert pick.native("/jokin/hakemisto") is None
    # Jokaista ikkunayritystä kohti yksi nosto, aina ennen AppleScriptia.
    assert jarjestys == ["eteen", "osascript", "eteen", "osascript"]

    jarjestys.clear()
    assert pick.native_folder("/jokin/hakemisto") is None
    assert jarjestys == ["eteen", "osascript"]


def test_eteen_nosto_ei_kaadu_ilman_ikkunapalvelinta(monkeypatch):
    """AppKitin puuttuminen tai ikkunapalvelimen pois jääminen ei ole virhe.

    Ikkuna aukeaa silloinkin, se on vain etsittävä itse — sama kuin
    ``speechmix.editor``issä. CI:n pytestissä ei ole ikkunapalvelinta, joten
    apurin saa kutsua missä vain eikä se saa koskaan nostaa poikkeusta.
    """
    monkeypatch.setattr(sys, "platform", "win32")

    def ei_saa_koskea():
        raise AssertionError("ei-darwinilla AppKitia ei kosketa")

    monkeypatch.setattr(pick, "_load_appkit", ei_saa_koskea)
    assert pick._ensure_foreground() is False

    monkeypatch.setattr(sys, "platform", "darwin")

    def ilman_appkitia():
        raise ImportError("No module named 'AppKit'")

    monkeypatch.setattr(pick, "_load_appkit", ilman_appkitia)
    assert pick._ensure_foreground() is False


def test_eteen_nosto_tekee_prosessista_tavallisen_sovelluksen(monkeypatch):
    """Kaksi askeltä, samat kuin ``speechmix.editor``issä.

    ``NSApplicationActivationPolicyRegular`` antaa prosessille Dock-kuvakkeen
    ja oikeuden nousta eteen, ja aktivointi nostaa sen ylimmäksi. Molemmat
    ennen ikkunan avaamista.
    """
    kutsut = []

    class ValeSovellus:
        def setActivationPolicy_(self, policy):
            kutsut.append(("policy", policy))

        def activateIgnoringOtherApps_(self, lippu):
            kutsut.append(("activate", lippu))

    class ValeNSApplication:
        @staticmethod
        def sharedApplication():
            return ValeSovellus()

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(pick, "_load_appkit", lambda: (ValeNSApplication, "regular"))
    assert pick._ensure_foreground() is True
    assert ("policy", "regular") in kutsut
    assert ("activate", True) in kutsut


def test_movement_tagged_export_is_not_a_candidate(tmp_path):
    """«move» on kirjoitettu tunnus, ei vieraan tiedoston sana."""
    from autoraffkat.pick import _is_output

    assert _is_output("jakso-cut broadcast move.fcpxml")
