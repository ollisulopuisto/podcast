"""Colab-istunnon tilan tarkistus ja hallinta."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any


def get_sessions_config_path() -> Path:
    """Polku Colab CLI:n istuntotiedostoon."""
    return Path.home() / ".config" / "colab-cli" / "sessions.json"


def _is_pid_alive(pid: int) -> bool:
    """Tarkista onko prosessi käynnissä."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def load_sessions() -> dict[str, dict[str, Any]]:
    """Lue kaikki paikalliset Colab-istunnot."""
    path = get_sessions_config_path()
    if not path.is_file():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def get_session(session_name: str) -> dict[str, Any] | None:
    """Hae yksittäisen istunnon tiedot jos se on olemassa."""
    sessions = load_sessions()
    return sessions.get(session_name)


def is_session_alive(session_name: str) -> bool:
    """Tarkista onko istunto olemassa ja käynnissä."""
    sess = get_session(session_name)
    if not sess:
        return False
    pid = sess.get("keep_alive_pid")
    if pid is not None:
        return _is_pid_alive(int(pid))
    return True


def stop_session(session_name: str) -> int:
    """Sulje Colab-istunto ajamalla `colab stop -s <session_name>`."""
    try:
        res = subprocess.run(["colab", "stop", "-s", session_name], check=False)
        return res.returncode
    except FileNotFoundError:
        return 127
