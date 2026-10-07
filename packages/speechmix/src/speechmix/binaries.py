"""ffmpegin ja ffprobin paikannus.

autoraffkat ja podcast-magic niputtavat kumpikin oman ffmpeginsä ja
etsivät sen samasta kolmesta paikasta samassa järjestyksessä:
PyInstallerin purkuhakemistosta, suoritettavan vierestä ja ``PATH``ista.
Molemmat ovat PyInstaller-sovelluksia, joten «kukin niputtaa omansa» ei
tarkoita että ne niputtaisivat eri paikkoihin — koodi oli kahtena
kappaleena, ei kahtena tapauksena. Siksi tässä ei ole isännän koukkua:
sellaista ei tarvitse yksikään kolmesta, ja käyttämätön haara on tässä
repossa juuri se vika jota vastaan lintti on säädetty tiukaksi.
"""

from __future__ import annotations

import functools
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .errors import MissingBinary
from .messages import t


def get_binary_path(name: str) -> str:
    """Suoritettavan polku. Nostaa ``MissingBinary``n jos sitä ei ole."""
    bin_name = f"{name}.exe" if os.name == "nt" else name

    # 1. PyInstallerin purkuhakemisto.
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        meipass = Path(sys._MEIPASS)
        for candidate in (meipass / "bin" / bin_name, meipass / bin_name):
            if candidate.is_file():
                return str(candidate)

    # 2. Suoritettavan viereiset hakemistot.
    if getattr(sys, "frozen", False):
        exec_dir = Path(sys.executable).resolve().parent
        for candidate in (exec_dir / "bin" / bin_name, exec_dir / bin_name):
            if candidate.is_file():
                return str(candidate)

    # 3. Järjestelmän PATH.
    found = shutil.which(bin_name) or shutil.which(name)
    if found:
        return found

    raise MissingBinary(t("binaries.missing", name=name))


def require_ffmpeg() -> None:
    """Varmistaa että sekä ffmpeg että ffprobe ovat käytettävissä.

    Molemmat, koska ne tulevat eri paketeista ja eri niputuksista: purku
    tarvitsee ffmpegin ja keston lukeminen ffprobin, ja puuttuva jälkimmäinen
    huomattaisiin muuten vasta kesken ajon.
    """
    for tool in ("ffmpeg", "ffprobe"):
        get_binary_path(tool)


def _hwaccels() -> set[str]:
    """ffmpegin tuntemat laitteistokiihdytykset (``-hwaccels``)."""
    try:
        done = subprocess.run(
            [get_binary_path("ffmpeg"), "-hide_banner", "-hwaccels"],
            capture_output=True, text=True, timeout=10, stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired, MissingBinary):
        return set()
    lines = done.stdout.splitlines()[1:]
    return {line.strip() for line in lines if line.strip()}


@functools.lru_cache(maxsize=1)
def hw_decode_args() -> list[str]:
    """Laitteistopurun liput ffmpegille: Macilla VideoToolbox, muualla ei mitään.

    Vain **massapurkuun** (kaikki avainruudut). Mitattu 2026-10-07:
    1080p H.264 avainruudut 8,3 → 2,8 s (CPU-aika 9,9 → 2,0 s), 4K HEVC
    14,6 → 2,0 s, ruudut bitilleen samat ja aikaleimat samat. Yksittäiseen
    ruutuun se **ei** kannata: purkajan käynnistys maksaa enemmän kuin
    säästää (H.264 0,19 → 0,33 s/ruutu). Koodekki jota VideoToolbox ei osaa
    (VP9) puretaan ohjelmallisesti samoin tuloksin.
    """
    if sys.platform != "darwin":
        return []
    return ["-hwaccel", "videotoolbox"] if "videotoolbox" in _hwaccels() else []
