"""Binäärien (ffmpeg, ffprobe) polun haku.

Colab-muistikirja ja paketointi vaativat erillistä logiikkaa, joten tämä
on irroitettu omaksi moduulikseen.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


class MissingBinary(RuntimeError):
    """Pyydetty binääriä ei löydy."""


def get_binary_path(name: str) -> str:
    """Hakee binäärin polun. Nostaa MissingBinary jos ei löydy.

    Hakujärjestys:
    1. Ympäristömuuttuja (esim. FFPROBE_PATH)
    2. PATH (shutil.which)
    3. Paketin mukana tuleva binääri (paketoinnissa)
    """
    env_var = f"{name.upper()}_PATH"
    if env_var in os.environ:
        path = os.environ[env_var]
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path

    # PATH-haku
    found = shutil.which(name)
    if found:
        return found

    # Paketin mukana tuleva binääri (pyinstaller jne.)
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS) if hasattr(sys, "_MEIPASS") else Path(sys.executable).parent
        candidate = base / name
        if candidate.is_file():
            return str(candidate)

    raise MissingBinary(f"Binääriä '{name}' ei löydy (ei PATHissa, ei paketissa)")
