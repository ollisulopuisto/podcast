"""Colab-istunnon tilan tarkistus ja hallinta."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

#: Colab CLI:n sanomat kun istunnon kone on kadonnut (Google otti sen
#: takaisin): 0.7.5 ``Session 'whisper' not found.`` (käyttäjäraportti
#: 19.11), uudemmat ``appears to be lost``. Jaettu ``__main__``in kanssa:
#: sama tunnistus elävyyskyselyssä ja ajon lokirivienseurannassa.
SESSION_GONE = re.compile(r"Session '[^']*' (?:appears to be lost|not found)")


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
    """Tarkista onko istunto olemassa ja käynnissä — myös Colabilta kysyen.

    Paikallinen kirjaus (ja sen keep-alive-prosessi) voi elää vaikka Google
    on ottanut koneen takaisin (käyttäjäraportti 19.11): silloin vastaus on
    ``Session '<nimi>' not found.`` ja istuntoa ei ole. Kysely voi vain
    kieltää: verkkovika tai muu epäselvä vastaus palauttaa paikallisen
    tuloksen, ja ajon oma kerta-uudelleenyritys korjaa loput."""
    sess = get_session(session_name)
    if not sess:
        return False
    pid = sess.get("keep_alive_pid")
    if pid is not None and not _is_pid_alive(int(pid)):
        return False
    return _remote_alive(session_name)


def _remote_alive(session_name: str) -> bool:
    """Kysy Colabilta: False vain kun vastaus sanoo istunnon kadonneen."""
    try:
        from .onboarding import colab_env

        res = subprocess.run(
            ["colab", "exec", "-s", session_name, "true"],
            capture_output=True,
            text=True,
            check=False,
            env=colab_env(),
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return True
    return SESSION_GONE.search(res.stdout or "") is None


def stop_session(session_name: str) -> int:
    """Sulje Colab-istunto ajamalla `colab stop -s <session_name>`."""
    try:
        from .onboarding import colab_env

        res = subprocess.run(
            ["colab", "stop", "-s", session_name], check=False, env=colab_env()
        )
        return res.returncode
    except FileNotFoundError:
        return 127
