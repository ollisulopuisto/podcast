# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller-määrittely.

Whisper-moottorit ovat valinnaisia riippuvuuksia, joten ne kerätään vain jos
ne on asennettu käännösympäristöön. Kääntäminen ilman niitä on
tarkoituksellista: sovelluksen voi paketoida myös ilman moottoria, jolloin
käyttöliittymä kertoo mitä puuttuu — se on parempi kuin käännös joka kaatuu
puuttuvaan valinnaiseen pakettiin.

Mallien painoja ei paketoida. large-v3-turbo on gigatavun luokkaa, se
ladataan Hugging Facesta ensimmäisellä ajolla ja jää sen jälkeen käyttäjän
välimuistiin — kaikkien mallien pakkaaminen tekisi .app-paketista
monigigaisen sen takia että käyttäjä ehkä kokeilee toista mallia.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)

BASE_DIR = Path(SPEC).parent.resolve()
SRC_DIR = BASE_DIR / "src"
PKG = "podcastmagic"

datas = [
    (str(SRC_DIR / PKG / "server" / "static"), f"{PKG}/server/static"),
    (str(SRC_DIR / PKG / "server" / "static"), "server/static"),
]
assets_dir = BASE_DIR / "assets"
if assets_dir.exists():
    datas.append((str(assets_dir), "assets"))

binaries = []
bin_dir = BASE_DIR / "bin"
if bin_dir.exists():
    for item in bin_dir.glob("*"):
        if item.is_file() and not item.name.startswith("."):
            binaries.append((str(item), "bin"))

hiddenimports = [
    "fastapi",
    "fastapi.staticfiles",
    "fastapi.responses",
    "uvicorn",
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    "lxml",
    "lxml.etree",
    "webview",
]
hiddenimports += collect_submodules("uvicorn")
hiddenimports += collect_submodules(PKG)

if sys.platform == "darwin":
    hiddenimports += ["webview.platforms.cocoa", "objc", "AppKit", "WebKit", "Foundation"]
elif sys.platform.startswith("win"):
    hiddenimports += ["webview.platforms.winforms", "webview.platforms.edgechromium"]


def try_collect(name: str, *, dylibs: bool = False) -> None:
    """Kerää paketin datat ja moduulit, jos paketti on asennettu."""
    try:
        __import__(name)
    except Exception:  # noqa: BLE001 — valinnainen riippuvuus
        print(f"[spec] {name} puuttuu, ohitetaan.")
        return
    datas.extend(collect_data_files(name))
    hiddenimports.extend(collect_submodules(name))
    if dylibs:
        binaries.extend(collect_dynamic_libs(name))
    print(f"[spec] {name} mukaan.")


# mlx tuo mukanaan Metal-varjostimet (.metallib) datatiedostoina — ilman niitä
# paketti kääntyy, käynnistyy ja kaatuu vasta ensimmäiseen litterointiin.
try_collect("mlx", dylibs=True)
try_collect("mlx_whisper")
try_collect("tiktoken_ext.openai_public")
try_collect("faster_whisper")
try_collect("ctranslate2", dylibs=True)
# Mallien lataus ensimmäisellä ajolla.
try_collect("huggingface_hub")

a = Analysis(
    [str(SRC_DIR / PKG / "__main__.py")],
    pathex=[str(SRC_DIR)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "pytest"],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

icon_path = None
for name in ("podcast-magic.icns" if sys.platform == "darwin" else "podcast-magic.ico",
             "icon.icns" if sys.platform == "darwin" else "icon.ico"):
    candidate = assets_dir / name
    if candidate.exists():
        icon_path = str(candidate)
        break

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="podcast-magic",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_path,
)

coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, strip=False, upx=False,
               upx_exclude=[], name="podcast-magic")

if sys.platform == "darwin":
    version = os.environ.get("PM_VERSION", "2026.8.27.3")
    app = BUNDLE(
        coll,
        name="Podcast Magic.app",
        icon=icon_path,
        bundle_identifier="com.sulopuis.podcastmagic",
        info_plist={
            "CFBundleName": "Podcast Magic",
            "CFBundleDisplayName": "Podcast Magic",
            "CFBundleVersion": version,
            "CFBundleShortVersionString": version,
            "NSHighResolutionCapable": "True",
            "NSRequiresAquaSystemAppearance": "False",
            "CFBundleDocumentTypes": [
                {
                    "CFBundleTypeName": "Hindenburg Session",
                    "CFBundleTypeRole": "Editor",
                    "LSHandlerRank": "Alternate",
                    "CFBundleTypeExtensions": ["nhsx"],
                }
            ],
        },
    )
