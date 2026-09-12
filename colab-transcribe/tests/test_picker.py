"""Tiedostojen ja hakemistojen valintaikkunoiden testit.

Käyttäjän ei tarvitse kirjoittaa polkuja käsin TUI:ssa:
valintaikkuna avaa Finderin (tai järjestelmän natiivin valitsimen) ja
palauttaa valitun polun.
"""

from __future__ import annotations

import subprocess

from colabtranscribe import picker


def test_has_native_picker_on_darwin(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setattr(
        "shutil.which", lambda cmd: "/usr/bin/osascript" if cmd == "osascript" else None
    )
    assert picker.has_native_picker() is True


def test_has_native_picker_false_when_no_tool(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setattr("shutil.which", lambda cmd: None)
    assert picker.has_native_picker() is False


def test_pick_folder_macos_success(monkeypatch, tmp_path):
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setattr(picker, "_ensure_foreground", lambda: True)

    def fake_run(args, capture_output, text, timeout):
        class Result:
            returncode = 0
            stdout = f"{tmp_path}\n"
            stderr = ""

        return Result()

    monkeypatch.setattr(subprocess, "run", fake_run)
    chosen = picker.pick_folder(prompt="Valitse kansio")
    assert chosen == str(tmp_path)


def test_pick_folder_macos_user_cancel(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setattr(picker, "_ensure_foreground", lambda: True)

    def fake_run(args, capture_output, text, timeout):
        class Result:
            returncode = 0
            stdout = ""  # -128 error catches and returns empty string
            stderr = ""

        return Result()

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert picker.pick_folder() is None


def test_pick_folder_resolves_symlinks_or_spaces(monkeypatch, tmp_path):
    target = tmp_path / "oma kansio"
    target.mkdir()
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setattr(picker, "_ensure_foreground", lambda: True)

    def fake_run(args, capture_output, text, timeout):
        class Result:
            returncode = 0
            stdout = f"{target}/\n"
            stderr = ""

        return Result()

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert picker.pick_folder() == str(target)
