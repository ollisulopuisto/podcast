"""Resurssipolkujen ratkaisu kehitystilassa ja pakatussa sovelluksessa."""

from __future__ import annotations

import sys
from pathlib import Path


def get_resource_path(relative_path: str | Path) -> Path:
    """Ratkaisee resurssin (esim. staattisen web-sisällön) polun.

    PyInstaller purkaa resurssit väliaikaiseen ``sys._MEIPASS``-hakemistoon.
    Kehitystilassa käytetään moduulin suhteellista polkua.
    """
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base_dir = Path(sys._MEIPASS)
    else:
        base_dir = Path(__file__).resolve().parent
    return base_dir / relative_path


def get_app_dir() -> Path:
    """Sovelluksen asennus- tai suoritushakemisto."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def get_app_icon_path() -> Path | None:
    """Ikkuna- ja telakkakuvakkeen polku, tai None jos kuvaketta ei ole."""
    if sys.platform == "darwin":
        preferred = (
            "assets/podcast-magic.icns",
            "assets/icon.icns",
            "assets/icon_1024.png",
            "assets/icon_512.png",
            "server/static/icon.png",
        )
    elif sys.platform.startswith("win"):
        preferred = ("assets/podcast-magic.ico", "assets/icon.ico", "server/static/favicon.ico")
    else:
        preferred = ("assets/icon_512.png", "server/static/icon.png")

    for rel in preferred:
        p = get_resource_path(rel)
        if p.is_file():
            return p
    app_root = get_app_dir()
    for rel in preferred:
        p = app_root / rel
        if p.is_file():
            return p
    return None


def state_dir() -> Path:
    """Hakemisto asetuksille ja välimuistille käyttäjän kotihakemistossa.

    Litteroinnin JSON-välimuisti menee kuitenkin työhakemistoon käyttäjän
    näkyville: se on työn tulos eikä ohjelman sisäistä kirjanpitoa, ja
    piilotettuna sen olemassaoloa ei arvaisi kun litterointi ohitetaan.
    """
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "Podcast Magic"
    elif sys.platform.startswith("win"):
        import os

        base = Path(os.environ.get("APPDATA", Path.home())) / "Podcast Magic"
    else:
        base = Path.home() / ".config" / "podcast-magic"
    base.mkdir(parents=True, exist_ok=True)
    return base
