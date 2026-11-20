"""Istunnon hallinnan ja tilan testit."""

from __future__ import annotations

import json
from pathlib import Path

from colabtranscribe import session


def test_load_sessions_when_file_missing(tmp_path: Path, monkeypatch):
    non_existent = tmp_path / "does_not_exist.json"
    monkeypatch.setattr(session, "get_sessions_config_path", lambda: non_existent)
    assert session.load_sessions() == {}


def test_load_sessions_returns_dict(tmp_path: Path, monkeypatch):
    cfg = tmp_path / "sessions.json"
    data = {
        "whisper": {
            "name": "whisper",
            "endpoint": "gpu-t4-xxx",
            "variant": "GPU",
            "accelerator": "T4",
            "keep_alive_pid": 12345,
        }
    }
    cfg.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(session, "get_sessions_config_path", lambda: cfg)
    res = session.load_sessions()
    assert "whisper" in res
    assert res["whisper"]["accelerator"] == "T4"


def test_is_session_alive_checks_process(tmp_path: Path, monkeypatch):
    cfg = tmp_path / "sessions.json"
    cfg.write_text(
        json.dumps(
            {
                "alive-sess": {"name": "alive-sess", "keep_alive_pid": 99999},
                "dead-sess": {"name": "dead-sess", "keep_alive_pid": 88888},
                "no-pid-sess": {"name": "no-pid-sess"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(session, "get_sessions_config_path", lambda: cfg)

    def fake_pid_exists(pid: int) -> bool:
        return pid == 99999

    monkeypatch.setattr(session, "_is_pid_alive", fake_pid_exists)

    assert session.is_session_alive("alive-sess") is True
    assert session.is_session_alive("dead-sess") is False
    # Jos pid puuttuu, istunto katsotaan olemassa olevaksi tiedoston perusteella
    assert session.is_session_alive("no-pid-sess") is True
    assert session.is_session_alive("non-existent") is False


def test_stop_session_runs_colab_stop(monkeypatch):
    import subprocess

    calls = []

    def fake_run(cmd, check=True, env=None):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(session.subprocess, "run", fake_run)
    code = session.stop_session("test-sess")
    assert code == 0
    assert calls == [["colab", "stop", "-s", "test-sess"]]


def test_stop_finds_the_bundled_colab(monkeypatch):
    from colabtranscribe import session as session_mod

    seen = []
    monkeypatch.setattr("colabtranscribe.onboarding.bundled_colab", lambda: "/env/bin/colab")

    def run(cmd, check=False, env=None):
        seen.append((cmd, env["PATH"].split(":")[0]))
        return type("R", (), {"returncode": 0})()

    monkeypatch.setattr("subprocess.run", run)
    assert session_mod.stop_session("s") == 0
    assert seen == [(["colab", "stop", "-s", "s"], "/env/bin")]


def _cfg_with(tmp_path: Path, monkeypatch, name: str = "whisper") -> None:
    cfg = tmp_path / "sessions.json"
    cfg.write_text(json.dumps({name: {"name": name}}), encoding="utf-8")
    monkeypatch.setattr(session, "get_sessions_config_path", lambda: cfg)


def test_is_session_alive_asks_colab_and_believes_a_gone_answer(
    tmp_path: Path, monkeypatch
):
    """Paikallinen kirjaus elää, mutta Google on ottanut koneen (19.11):
    vastaus "Session 'whisper' not found." tarkoittaa kuollutta."""
    _cfg_with(tmp_path, monkeypatch)

    class Gone:
        returncode = 1
        stdout = "[colab] Session 'whisper' not found.\n"

    monkeypatch.setattr(session.subprocess, "run", lambda *a, **k: Gone())
    assert session.is_session_alive("whisper") is False


def test_is_session_alive_keeps_true_on_an_inconclusive_probe(
    tmp_path: Path, monkeypatch
):
    """Verkkovika tai puuttuva CLI ei saa tappaa elävää kirjettä: vanha
    käytös jää, ja ajon oma uudelleenyritys korjaa tilanteen."""
    _cfg_with(tmp_path, monkeypatch)

    class NetDown:
        returncode = 1
        stdout = "URLError: network unreachable"

    monkeypatch.setattr(session.subprocess, "run", lambda *a, **k: NetDown())
    assert session.is_session_alive("whisper") is True

    def no_cli(*a, **k):
        raise FileNotFoundError

    monkeypatch.setattr(session.subprocess, "run", no_cli)
    assert session.is_session_alive("whisper") is True


def test_is_session_alive_short_circuits_without_a_local_record(
    tmp_path: Path, monkeypatch
):
    """Ei paikallista kirjausta, ei kyselyä Colabiin."""
    monkeypatch.setattr(
        session, "get_sessions_config_path", lambda: tmp_path / "none.json"
    )
    called = []
    monkeypatch.setattr(
        session.subprocess, "run", lambda *a, **k: called.append(a) or None
    )
    assert session.is_session_alive("whisper") is False
    assert called == []
