"""ffmpeg- ja ffprobe-binäärien paikannus paketista tai järjestelmästä."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


class MissingBinary(RuntimeError):
    """ffmpeg puuttuu. Viesti kertoo mistä sen saa."""


def get_binary_path(name: str) -> str:
    """Etsii suoritettavan binäärin: paketti, sovelluksen vierus, PATH."""
    bin_name = f"{name}.exe" if os.name == "nt" else name

    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        meipass = Path(sys._MEIPASS)
        for candidate in (meipass / "bin" / bin_name, meipass / bin_name):
            if candidate.is_file():
                return str(candidate)

    if getattr(sys, "frozen", False):
        exec_dir = Path(sys.executable).resolve().parent
        for candidate in (exec_dir / "bin" / bin_name, exec_dir / bin_name):
            if candidate.is_file():
                return str(candidate)

    found = shutil.which(bin_name) or shutil.which(name)
    if found:
        return found

    raise MissingBinary(
        f"{name} puuttuu. Asenna: brew install ffmpeg — tai käännä sovellus, "
        "jolloin binääri tulee mukana."
    )


def has_binary(name: str) -> bool:
    try:
        get_binary_path(name)
        return True
    except MissingBinary:
        return False
