"""Tiedostojen löytäminen ilman että polkua tarvitsee kirjoittaa.

Työjärjestys on aina sama: Hindenburg vie istunnon kansioon, ja seuraava
työkalu avataan siihen. Polun naputtelu on kitkaa juuri siinä kohdassa.
"""

from __future__ import annotations

import os
from pathlib import Path

SESSION_SUFFIX = ".nhsx"

# Näiden päätteiden tiedostot ovat tämän työkalun omia tuotoksia. Ne saa
# valita — vaimennus lukee nimenomaan litteroitua istuntoa — mutta uusin
# ehdotetaan lähteeksi vasta jos muuta ei ole.
DERIVED = (" litteroitu", " vaimennettu")


def sessions(directory: str | Path) -> list[str]:
    """Kansion istuntotiedostot, uusin ensin."""
    try:
        entries = [
            os.path.join(str(directory), name)
            for name in os.listdir(str(directory))
            if name.lower().endswith(SESSION_SUFFIX) and not name.startswith(".")
        ]
    except OSError:
        return []
    entries.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return entries


def is_derived(path: str | Path) -> bool:
    stem = Path(path).stem
    return any(stem.endswith(mark) for mark in DERIVED)


def newest(directory: str | Path) -> str:
    """Todennäköisin lähde kansiossa: uusin alkuperäinen istunto."""
    found = sessions(directory)
    for path in found:
        if not is_derived(path):
            return path
    return found[0] if found else ""


def resolve(argument: str) -> str:
    """Argumentti poluksi: tiedosto sellaisenaan, kansiosta uusin istunto."""
    path = os.path.abspath(os.path.expanduser(argument))
    if os.path.isdir(path):
        return newest(path)
    return path


def browse(directory: str | Path) -> dict:
    """Kansion sisältö selaimen valitsinta varten.

    Vain kansiot ja istuntotiedostot. Äänitiedostojen listaaminen tekisi
    listasta satarivisen eikä auttaisi: äänet luetaan istunnon poolista.
    """
    base = Path(os.path.abspath(os.path.expanduser(str(directory) or "~")))
    if not base.is_dir():
        base = base.parent if base.parent.is_dir() else Path.home()
    dirs, files = [], []
    try:
        for entry in sorted(base.iterdir(), key=lambda p: p.name.lower()):
            if entry.name.startswith("."):
                continue
            if entry.is_dir():
                dirs.append({"name": entry.name, "path": str(entry)})
            elif entry.suffix.lower() == SESSION_SUFFIX:
                files.append(
                    {
                        "name": entry.name,
                        "path": str(entry),
                        "mtime": entry.stat().st_mtime,
                        "derived": is_derived(entry),
                    }
                )
    except OSError as exc:
        return {"dir": str(base), "parent": str(base.parent), "dirs": [], "files": [], "error": str(exc)}
    files.sort(key=lambda f: f["mtime"], reverse=True)
    return {
        "dir": str(base),
        "parent": str(base.parent) if base.parent != base else "",
        "dirs": dirs,
        "files": files,
        "error": "",
    }
