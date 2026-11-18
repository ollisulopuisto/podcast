"""Generoitu teksti löytää Tekstityksen sovelluspaketista, ja paketin
tiedostot valitaan natiivilla ikkunalla (käyttäjäraportti 2026-11-18)."""

import os
import stat
import sys

import pytest
from fastapi.testclient import TestClient

from autoraffkat import package as pkg
from autoraffkat import pick
from autoraffkat.server import app as server_app
from autoraffkat.server.app import AppState, create_app


def _fake_cli(path, help_text="render-alpha  Render captions"):
    path.write_text(f"#!/bin/sh\necho '{help_text}'\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return str(path)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv(pkg.TEKSTITYS_ENV, raising=False)
    monkeypatch.setattr(pkg, "_GENERATED_CACHE", {"at": 0.0, "value": False})


def test_find_tekstitys_uses_the_app_bundle_cli_when_path_has_none(tmp_path, monkeypatch):
    """Asennettu Tekstitys.app tuo vain TekstitysCLI:n paketin sisään."""
    cli = _fake_cli(tmp_path / "TekstitysCLI")
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr(pkg, "TEKSTITYS_APP_CLI", (str(tmp_path / "puuttuu"), cli))

    assert pkg.find_tekstitys() == cli
    assert pkg.generated_source_available() is True


def test_find_tekstitys_prefers_the_environment_override(tmp_path, monkeypatch):
    own = _fake_cli(tmp_path / "oma")
    monkeypatch.setenv(pkg.TEKSTITYS_ENV, own)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/tekstitys")

    assert pkg.find_tekstitys() == own


def test_find_tekstitys_ignores_a_broken_override(tmp_path, monkeypatch):
    monkeypatch.setenv(pkg.TEKSTITYS_ENV, str(tmp_path / "ei-ole"))
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/tekstitys")

    assert pkg.find_tekstitys() == "/usr/bin/tekstitys"


def test_missing_tekstitys_is_reported_not_found(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr(pkg, "TEKSTITYS_APP_CLI", (str(tmp_path / "puuttuu"),))

    assert pkg.find_tekstitys() is None
    assert pkg.generated_source_available() is False


def test_old_tekstitys_without_render_alpha_is_unavailable(tmp_path, monkeypatch):
    cli = _fake_cli(tmp_path / "TekstitysCLI", "burn  transcribe")
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr(pkg, "TEKSTITYS_APP_CLI", (cli,))

    assert pkg.generated_source_available() is False


def test_generated_card_is_rendered_with_the_bundle_cli(tmp_path, monkeypatch):
    """Ilman löytöä kortti jäi hiljaa pois; nyt ajetaan paketin CLI."""
    cli = _fake_cli(tmp_path / "TekstitysCLI")
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr(pkg, "TEKSTITYS_APP_CLI", (cli,))
    import subprocess

    real_run = subprocess.run
    calls = []

    class Done:
        returncode = 0
        stdout = "{}"
        stderr = ""

    def fake_run(cmd, **kw):
        if "render-alpha" not in cmd:
            return real_run(cmd, **kw)
        calls.append(cmd)
        out = cmd[cmd.index("--out") + 1]
        with open(out, "w") as fh:
            fh.write("mov")
        return Done()

    monkeypatch.setattr(subprocess, "run", fake_run)
    settings = pkg.PackageSettings(
        intro=pkg.TitleCard(mode="generated", text="Otsikko", duration=4.0)
    )

    result, problems = pkg.materialize_generated(settings, str(tmp_path / "work"))

    assert problems == []
    assert calls and calls[0][0] == cli
    assert result.intro.mode == "file"
    assert os.path.exists(result.intro.path)


def test_state_reports_whether_generated_text_is_available(tmp_path, monkeypatch):
    monkeypatch.setattr(pkg, "generated_source_available", lambda: False)
    client = TestClient(create_app(AppState(xml_path="")))
    assert client.get("/api/state").json()["generated_available"] is False

    monkeypatch.setattr(pkg, "_GENERATED_CACHE", {"at": 0.0, "value": False})
    monkeypatch.setattr(pkg, "generated_source_available", lambda: True)
    assert client.get("/api/state").json()["generated_available"] is True


def test_pick_file_endpoint_returns_the_chosen_path(monkeypatch):
    seen = {}

    def fake(start, title, force=False):
        seen.update(start=start, title=title, force=force)
        return "/Volumes/x/alpha.mov"

    monkeypatch.setattr(server_app.pick, "has_native_picker", lambda: True)
    monkeypatch.setattr(server_app.pick, "native_file", fake)
    client = TestClient(create_app(AppState(xml_path="")))

    reply = client.post("/api/pick-file", json={"title": 'Valitse "alku"\\'})

    assert reply.json() == {"path": "/Volumes/x/alpha.mov"}
    assert seen["force"] is True
    assert '"' not in seen["title"] and "\\" not in seen["title"]


def test_pick_file_endpoint_without_a_picker_says_unavailable(monkeypatch):
    monkeypatch.setattr(server_app.pick, "has_native_picker", lambda: False)
    client = TestClient(create_app(AppState(xml_path="")))

    assert client.post("/api/pick-file", json={}).json() == {
        "path": "", "unavailable": True,
    }


def test_native_file_on_macos_asks_for_one_file_and_returns_an_absolute_path(monkeypatch):
    prompts = []

    def fake_osascript(script):
        prompts.append(script)
        return "/Users/x/alku.mov"

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(pick, "_osascript", fake_osascript)
    monkeypatch.setattr(pick, "_ensure_foreground", lambda: True)

    assert pick.native_file("", "Valitse alku", force=True) == "/Users/x/alku.mov"
    assert "multiple selections" not in prompts[0]
    assert '"Valitse alku"' in prompts[0]


def test_native_file_cancel_returns_none(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(pick, "_osascript", lambda script: "")
    monkeypatch.setattr(pick, "_ensure_foreground", lambda: True)

    assert pick.native_file("", "Valitse", force=True) is None
