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
        "vst-pipeline": {
            "name": "vst-pipeline",
            "endpoint": "gpu-t4-xxx",
            "variant": "GPU",
            "accelerator": "T4",
            "keep_alive_pid": 12345,
        }
    }
    cfg.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(session, "get_sessions_config_path", lambda: cfg)
    res = session.load_sessions()
    assert "vst-pipeline" in res
    assert res["vst-pipeline"]["accelerator"] == "T4"


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

    def fake_run(cmd, check=True):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(session.subprocess, "run", fake_run)
    code = session.stop_session("test-sess")
    assert code == 0
    assert calls == [["colab", "stop", "-s", "test-sess"]]
