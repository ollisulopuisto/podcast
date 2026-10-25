"""Pikanäppäimet löytyvät käyttöliittymästä, eivät vain koodista.

Näppäimiä oli kaksi, ⌘E ja ⌘O, ja ne näkyivät vain painikkeiden kyljessä
kovakoodattuna «⌘»-merkkinä — myös Windowsissa, jossa näppäin on Ctrl.
Kolmas, raitakortin nosto Enterillä tai välilyönnillä, ei näkynyt missään.
Nyt jokainen näppäin on yhdessä luettelossa (`SHORTCUTS` app.js:ssä), ja
siitä syntyvät näppäinkäsittelijä, painikkeiden vihjeet ja ohjeikkuna.

Mittaus tehdään valeselaimessa (`ui_shortcuts.js`), joka painaa näppäimiä ja
kertoo mitä tapahtui; väitteet ovat tässä, jotta jokainen lupaus on oma
testinsä.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = (
    Path(__file__).resolve().parents[1] / "src" / "autoraffkat" / "server" / "static"
)
HARNESS = Path(__file__).parent / "ui_shortcuts.js"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node puuttuu")


def _measure(platform):
    done = subprocess.run(
        ["node", str(HARNESS), str(STATIC), platform],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert done.returncode == 0, done.stderr or done.stdout
    return json.loads(done.stdout)


@pytest.fixture(scope="module")
def mac():
    return _measure("mac")


@pytest.fixture(scope="module")
def other():
    return _measure("other")


@pytest.fixture(scope="module", params=["mac", "other"])
def run(request, mac, other):
    return {"mac": mac, "other": other}[request.param]


@needs_node
def test_the_harness_ran_without_errors(run):
    """Mittari itse ei saa kaatua kesken: puuttuva tulos näyttäisi vihreältä."""
    assert not run["errors"], run["errors"]


@needs_node
def test_the_registry_holds_every_shortcut_that_exists(run):
    """Luettelo on olemassa ja siinä on ainakin ne näppäimet jotka olivat jo.

    ⌘E vie, ⌘O avaa, Enter ja välilyönti nostavat kortin, ? avaa ohjeen ja
    Esc sulkee sen. Esikatselun rulla, veto ja tuplaklikkaus ovat hiiren
    eleitä, mutta yhtä piilossa, joten ne ovat samassa luettelossa.
    """
    ids = {s["id"] for s in run["registry"]}
    assert {"open", "export", "pick", "help", "close"} <= ids, ids
    combos = {s["id"]: s["combos"] for s in run["registry"]}
    assert {"key": "e", "mod": True} in combos["export"]
    assert {"key": "o", "mod": True} in combos["open"]
    assert {"key": "Enter", "mod": False} in combos["pick"]
    assert {"key": " ", "mod": False} in combos["pick"]
    assert {"key": "?", "mod": False} in combos["help"]
    assert {"key": "Escape", "mod": False} in combos["close"]


@needs_node
def test_every_shortcut_appears_in_the_sheet_in_both_languages(run):
    """(i) Ohjeikkuna syntyy luettelosta, joten jokainen rivi on siinä.

    Rivillä on käännetty selitys ja näppäin, ja kumpikin kieli piirtää
    saman joukon.
    """
    ids = [s["id"] for s in run["registry"]]
    assert ids
    for lang in ("fi", "en"):
        sheet = run["sheet"][lang]
        assert sorted(sheet["ids"]) == sorted(ids), lang
        labels = run["hints"][lang]["labels"]
        for sid in ids:
            assert labels[sid] in sheet["rows"][sid], (lang, sid)
        for group, title in run["hints"][lang]["groups"].items():
            assert title in sheet["text"], (lang, group)
        assert sheet["labelledby"], "ikkunalla ei ole otsikkoa ruudunlukijalle"
    assert run["sheet"]["fi"]["text"] != run["sheet"]["en"]["text"]


@needs_node
def test_every_shortcut_label_has_a_translation_in_both_languages(run):
    """(i) Uusi näppäin ilman käännöstä näkyisi ruudulla avaimena."""
    fi, en = set(run["strings"]["fi"]), set(run["strings"]["en"])
    needed = set()
    for s in run["registry"]:
        needed.add(s["label"])
        if s["text"]:
            needed.add(s["text"])
        if s["pointer"]:
            needed.add(s["pointer"])
    needed |= {f"keys.group.{g}" for g in run["groups"]}
    needed |= {"keys.title", "keys.button", "keys.close.button", "keys.space", "keys.or"}
    assert needed - fi == set(), sorted(needed - fi)
    assert needed - en == set(), sorted(needed - en)
    assert {s["group"] for s in run["registry"]} <= set(run["groups"])


@needs_node
def test_the_handler_reacts_only_to_registered_keys(run):
    """(ii) Näppäinkäsittelijä ei voi kasvattaa dokumentoimatonta näppäintä.

    Mittari painaa jokaista tulostettavaa merkkiä ja nimettyä näppäintä
    kahdeksalla muuntimien yhdistelmällä — sivulla, tekstikentässä, avoimessa
    ikkunassa ja raitakortilla — ja kirjaa jokaisen johon jokin reagoi.
    Jokaisen on löydyttävä luettelosta samassa tilassa. Ainoa poikkeus on
    Tab avoimessa ikkunassa: se on kohdistuksen loukku, ei pikanäppäin.
    """
    battery = run["battery"]
    for where in ("page", "field", "sheet", "card"):
        rows = battery[where]
        stray = [
            r
            for r in rows
            if not r["matched"] and not (where == "sheet" and r["key"] == "Tab")
        ]
        assert not stray, (where, stray)
    keys = {(r["key"], tuple(r["mods"])) for r in battery["page"]}
    assert ("e", ("metaKey",)) in keys and ("o", ("ctrlKey",)) in keys
    assert ("?", ()) in keys and ("?", ("shiftKey",)) in keys
    assert {r["key"] for r in battery["card"] if r["matched"] == "card"} == {"Enter", " "}


@needs_node
def test_every_keydown_listener_goes_through_the_registry():
    """(ii) Uusi `keydown`-kuuntelija ohi luettelon kaatuu tähän.

    Mittari painaa vain ikkunan ja raitakortin käsittelijöitä. Kolmas
    kuuntelija jossain muualla jäisi siltä näkemättä, joten jokaisen
    kuuntelijan on kysyttävä luettelolta.
    """
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    listeners = re.findall(r"addEventListener\('keydown',\s*([^\n]*)", app)
    assert listeners, "app.js:ssä ei ole yhtään keydown-kuuntelijaa"
    for start in listeners:
        assert re.match(r"\(e\) => (onShortcutKey\(e\)|shortcutKey\(e, 'card'\))", start), (
            f"keydown-kuuntelija ohi SHORTCUTS-luettelon: {start}"
        )


@needs_node
def test_a_single_key_does_nothing_while_typing(run):
    """Kirjoittaminen kenttään ei laukaise yksinäistä näppäintä.

    Kentässä reagoivat vain muuntimelliset (⌘E, ⌘O), kuten ennenkin.
    """
    for r in run["battery"]["field"]:
        assert {"metaKey", "ctrlKey"} & set(r["mods"]), r
    # Kortin sisällä on tekstikenttä (ryhmärivin mikin nimi). Välilyönti
    # siinä nosti kortin ja söi välilyönnin, joten nimeen ei saanut
    # kahta sanaa.
    assert run["spaceInCardField"] == {"picked": None, "prevented": False}
    for name, typed in run["scenarios"]["typed"].items():
        assert not typed["opened"], name
        assert not typed["prevented"], name


@needs_node
def test_question_mark_opens_the_sheet_and_escape_closes_it(run):
    """(iii) ? avaa, kohdistus siirtyy ikkunaan, Esc sulkee ja palauttaa sen."""
    sc = run["scenarios"]
    assert sc["questionOpens"]
    assert sc["questionPrevented"]
    assert sc["focusInside"] in ("child", "sheet")
    assert sc["escapeCloses"]
    assert sc["escapePrevented"]
    assert sc["focusReturned"]
    assert sc["questionToggles"] and sc["toggleFocusReturned"]
    assert sc["checkboxOpens"], "valintaruutu ei ole kirjoituskenttä"
    assert not sc["cmdQuestionOpens"], "⌘? kuuluu selaimelle"


@needs_node
def test_focus_is_trapped_in_the_open_sheet(run):
    sc = run["scenarios"]
    assert sc["tabStaysInside"] and sc["tabPrevented"]
    assert sc["shiftTabStaysInside"]
    assert sc["escapedFocusReturns"]


@needs_node
def test_the_header_button_opens_the_sheet_and_it_can_be_closed(run):
    """Näkyvä tie ohjeeseen: painike otsikossa ja sulkupainike ikkunassa."""
    sc = run["scenarios"]
    assert sc["buttonOpens"] and sc["buttonFocusReturned"]
    assert sc["closeButton"] and sc["closeButton"]["aria"]
    assert sc["closeButtonCloses"]
    assert sc["nativeCloseReturnsFocus"], "selaimen oma Esc ohitti palautuksen"
    for lang in ("fi", "en"):
        hint = run["hints"][lang]["shortcuts"]
        assert hint["kbd"] == ["?"], hint
        assert hint["aria"] == "?"


@needs_node
def test_the_sheet_follows_the_language(run):
    """(iii) Kielen vaihto piirtää avoimen ikkunan uudelleen, auki."""
    sc = run["scenarios"]["langSwitch"]
    assert sc["fi"] != sc["en"]
    assert run["hints"]["en"]["labels"]["export"] in sc["en"]
    assert run["hints"]["fi"]["labels"]["export"] in sc["fi"]
    assert sc["stillOpen"] and sc["focusInside"]
    assert run["scenarios"]["redrawAllRendersStatic"]


@needs_node
def test_is_mac_like_reads_the_platform(mac):
    """(iv) macOS ja iPadOS ovat Mac; Windows, Linux ja tuntematon eivät."""
    assert mac["macLike"] == {
        "MacIntel": True,
        "iPad": True,
        "uaData macOS": True,
        "Win32": False,
        "Linux": False,
        "uaData Windows": False,
        "ua only Mac": True,
        "none": False,
    }


@needs_node
def test_the_modifier_is_cmd_on_a_mac_and_ctrl_elsewhere(mac, other):
    """(iv) ⌘ Macissa, Ctrl muualla — painikkeessa, vihjeessä ja ikkunassa.

    Kovakoodattu ⌘ näytti Windowsissa näppäimen jota siinä ei ole.
    """
    for lang in ("fi", "en"):
        assert mac["hints"][lang]["export"]["kbd"] == ["⌘E"]
        assert mac["hints"][lang]["open"]["kbd"] == ["⌘O"]
        assert other["hints"][lang]["export"]["kbd"] == ["Ctrl+E"]
        assert other["hints"][lang]["open"]["kbd"] == ["Ctrl+O"]
        assert "⌘E" in mac["hints"][lang]["export"]["title"]
        assert "Ctrl+E" in other["hints"][lang]["export"]["title"]
        assert "⌘E" in mac["sheet"][lang]["rows"]["export"]
        assert "Ctrl+E" in other["sheet"][lang]["rows"]["export"]
        assert "⌘" not in other["sheet"][lang]["text"]
    # Ruudunlukijalle kumpikin, koska kumpikin toimii kummassakin.
    assert mac["hints"]["en"]["export"]["aria"] == "Meta+E Control+E"
    assert other["hints"]["en"]["export"]["aria"] == "Meta+E Control+E"


@needs_node
def test_the_old_shortcuts_still_work(run):
    """⌘E ja Ctrl+O tekevät saman kuin ennen, myös tekstikentästä; kortti
    nousee Enterillä ja välilyönnillä ja laskeutuu uudella painalluksella."""
    sc = run["scenarios"]
    assert sc["cmdE"] == {"exports": 1, "prevented": True}
    assert sc["ctrlShiftE"] == 2, "vaihto+Ctrl+E vei ennenkin"
    assert sc["ctrlOFromField"] == {"opens": 1, "prevented": True}
    assert sc["cmdEFromSheet"] == {"exports": 1, "closed": True}
    assert run["cardEnter"] == "K1"
    assert run["cardEnterAgain"] is None
    assert run["cardSpace"] == "K1"
    assert run["cardAria"] == "Enter Space"
