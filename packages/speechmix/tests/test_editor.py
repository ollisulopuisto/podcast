"""Liitännäisen oma ikkuna omassa prosessissaan — molemmat päät.

Ikkunaa ei voi avata testissä, eikä sitä yritetäkään. Se mitä tässä
väitetään on **yhteyskäytäntö**: mitä lapsi kirjoittaa ulos ja miten emo
lukee sen. Juuri siinä oli vika jota vastaan puolet näistä on kirjoitettu —
väliviesti «opening» näytti tulokselta, ja oikea tulos näytti puuttuvan.

Kumpikin pää on kirjastossa, koska niitä on kaksi vain yhdessä: emon
jäsennin ilman lapsen muotoa on arvaus. Kaksi kopiota jäsentimestä on sama
ajautuminen jota vastaan tämä repositorio on.
"""

from __future__ import annotations

import base64
import io
import json
import subprocess

import pytest

from speechmix import chain, editor

# --------------------------------------------------------------------------
# Emon pää: yhteyskäytännön jäsennin
# --------------------------------------------------------------------------


def lines(*messages: dict) -> str:
    return "".join(json.dumps(message) + "\n" for message in messages)


def test_the_opening_line_is_not_the_result():
    """«opening» on väliviesti, ei tulos.

    Lapsi kertoo sillä vain, saiko se ikkunan nousemaan eteen. Jäsennin joka
    ottaa ensimmäisen JSON-rivin pitäisi sitä tuloksena, jolloin käyttäjän
    ikkunaan jättämä tila katoaisi hiljaa — ja tila on koko syy siihen että
    tämä prosessi on olemassa.
    """
    result = editor.read_result(
        lines(
            {"kind": "opening", "foreground": True},
            {"kind": "done", "state": "dGlsYQ==", "params": {"mix": 46.3}},
        ),
        "",
    )
    assert result.state == "dGlsYQ=="
    assert result.params == {"mix": 46.3}


def test_a_window_that_stayed_behind_is_said_out_loud():
    """Tapahtui, ei näkynyt, ei kerrottu — se on tässä projektissa vika."""
    said: list[str] = []
    editor.read_result(
        lines(
            {"kind": "opening", "foreground": False},
            {"kind": "done", "state": "", "params": {}},
        ),
        "",
        log=said.append,
    )
    assert any("front" in message for message in said), said


def test_a_plugins_own_chatter_is_logged_not_fatal():
    """Liitännäiset kirjoittavat stdoutiin. Se ei ole yhteyskäytäntöä.

    Rivi joka ei ole JSONia on liitännäisen omaa puhetta, ja jäsennin joka
    kaatuu siihen kaataa käsittelyn syystä joka ei ole vika.
    """
    said: list[str] = []
    result = editor.read_result(
        "dxRevive: loading model Studio 2\n"
        + lines({"kind": "done", "state": "", "params": {}}),
        "",
        log=said.append,
    )
    assert result.state == ""
    assert any("Studio 2" in message for message in said), said


def test_a_child_that_failed_reports_its_own_reason():
    with pytest.raises(chain.ChainError, match="no plugin"):
        editor.read_result(lines({"kind": "failed", "error": "no plugin"}), "")


def test_a_child_that_died_without_saying_anything_falls_back_to_stderr():
    """Lapsi voi kaatua ennen kuin se ehtii kirjoittaa mitään.

    Silloin ainoa jäljellä oleva syy on stderrin viimeinen rivi. Tyhjä
    virheilmoitus olisi tässä pahin mahdollinen: käyttäjä näkee vain että
    painike ei tehnyt mitään.
    """
    with pytest.raises(chain.ChainError, match="Segmentation fault"):
        editor.read_result("", "dyld: lazy symbol binding\nSegmentation fault\n")


def test_a_child_that_said_nothing_at_all_is_still_a_readable_error():
    with pytest.raises(chain.ChainError, match="could not be opened"):
        editor.read_result("", "")


# --------------------------------------------------------------------------
# Emon pää: prosessin käynnistys
# --------------------------------------------------------------------------


def test_a_timeout_is_a_readable_error(monkeypatch):
    """Ikkuna jäi auki. Se ei ole kaatuminen eikä saa näyttää siltä."""

    def never(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="editor", timeout=1.0)

    monkeypatch.setattr(editor.subprocess, "run", never)
    with pytest.raises(chain.ChainError, match="too long"):
        editor.open_editor("/some/plugin.vst3", timeout=1.0)


def test_the_spec_reaches_the_child_as_one_json_object(monkeypatch):
    """Emon ja lapsen sopimus on yksi objekti stdinissä, ei argumentteja.

    Polku voi olla mitä tahansa mitä levyllä on, eikä komentorivi ole
    paikka lainausmerkeille.
    """
    seen: dict = {}

    def capture(command, **kwargs):
        seen["command"] = command
        seen["spec"] = json.loads(kwargs["input"])
        return subprocess.CompletedProcess(
            command, 0, lines({"kind": "done", "state": "", "params": {}}), ""
        )

    monkeypatch.setattr(editor.subprocess, "run", capture)
    editor.open_editor("/a plug in.vst3", {"mix": 50.0}, "dGlsYQ==")

    assert seen["command"][1:] == ["-m", "speechmix.editor"]
    assert seen["spec"] == {
        "plugin_path": "/a plug in.vst3",
        "params": {"mix": 50.0},
        "state": "dGlsYQ==",
    }


def test_an_empty_path_is_refused_before_a_process_is_started(monkeypatch):
    def explode(*args, **kwargs):
        raise AssertionError("prosessia ei saa käynnistää ilman polkua")

    monkeypatch.setattr(editor.subprocess, "run", explode)
    with pytest.raises(chain.ChainError, match="not found"):
        editor.open_editor("")


# --------------------------------------------------------------------------
# Lapsen pää
# --------------------------------------------------------------------------


class _Plugin:
    """Liitännäinen joka muistaa mitä sen ikkunassa tehtiin."""

    parameters = {"mix": None}

    def __init__(self):
        self.mix = 50.0
        self.raw_state = b"alkutila"
        self.shown = False

    def show_editor(self):
        # Käyttäjä kääntää säädintä ja vaihtaa mallin, sitten sulkee ikkunan.
        self.shown = True
        self.mix = 80.0
        self.raw_state = b"Studio 2"


def run_child(monkeypatch, spec: dict, plugin=None):
    """Ajaa lapsen pään ja palauttaa sen kirjoittamat viestit."""
    out = io.StringIO()
    monkeypatch.setattr(editor.sys, "stdin", io.StringIO(json.dumps(spec)))
    monkeypatch.setattr(editor.sys, "stdout", out)
    monkeypatch.setattr(editor, "_become_an_app", lambda: True)
    if plugin is not None:
        monkeypatch.setattr(chain, "load_plugin", lambda *a, **k: plugin)
    code = editor.main()
    return code, [json.loads(line) for line in out.getvalue().splitlines()]


def test_the_child_returns_the_state_the_user_left(monkeypatch):
    """Malli ei ole parametri. Tila on ainoa tie siihen.

    dxRevive julkaisee neljä parametria, eikä mallin valinta ole yksikään
    niistä — joten ilman tätä paluuta ajetaan aina liitännäisen oletusmallia
    eikä voida edes kertoa kummasta on kyse.
    """
    plugin = _Plugin()
    code, messages = run_child(
        monkeypatch, {"plugin_path": "/x.vst3", "params": {}, "state": None}, plugin
    )

    assert code == 0 and plugin.shown
    assert [message["kind"] for message in messages] == ["opening", "done"]
    done = messages[-1]
    assert base64.b64decode(done["state"]) == b"Studio 2"
    # Säädin seuraa mukana: käyttäjä on voinut kääntää sitä samassa ikkunassa.
    assert done["params"]["mix"] == pytest.approx(80.0)


def test_the_child_reports_a_failure_instead_of_dying_silently(monkeypatch):
    """Lapsiprosessi ei saa kadota sanomatta mitään."""

    def missing(*args, **kwargs):
        raise chain.ChainError("Plug-in not found: /x.vst3")

    monkeypatch.setattr(chain, "load_plugin", missing)
    code, messages = run_child(
        monkeypatch, {"plugin_path": "/x.vst3", "params": {}, "state": None}
    )
    assert code == 1
    assert messages[-1]["kind"] == "failed"
    assert "not found" in messages[-1]["error"]


def test_the_two_ends_agree(monkeypatch):
    """Lapsen tuloste luettuna emon jäsentimellä. Ei kahta muotoa, vaan yksi."""
    plugin = _Plugin()
    out = io.StringIO()
    monkeypatch.setattr(
        editor.sys, "stdin", io.StringIO(json.dumps({"plugin_path": "/x.vst3"}))
    )
    monkeypatch.setattr(editor.sys, "stdout", out)
    monkeypatch.setattr(editor, "_become_an_app", lambda: True)
    monkeypatch.setattr(chain, "load_plugin", lambda *a, **k: plugin)
    editor.main()

    result = editor.read_result(out.getvalue(), "")
    assert base64.b64decode(result.state) == b"Studio 2"
