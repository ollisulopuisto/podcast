#!/usr/bin/env python3
"""Yhden komennon käännös: Podcast Magic macOS-sovellukseksi.

    uv run --extra mlx python scripts/build_app.py --dmg

Whisper-moottori on valinnainen riippuvuus, ja se otetaan mukaan siitä
ympäristöstä jossa käännös ajetaan. Ilman ``--extra mlx`` syntyy paketti
jossa käyttöliittymä toimii mutta litterointi kertoo puuttuvasta moottorista.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
APP_NAME = "Podcast Magic"


def ensure_icons() -> None:
    """Tekee .icns-kuvakkeen PNG-sarjasta, jos sitä ei vielä ole."""
    if sys.platform != "darwin":
        return
    assets = ROOT_DIR / "assets"
    if (assets / "podcast-magic.icns").exists() or (assets / "icon.icns").exists():
        return
    if shutil.which("iconutil") is None or not (assets / "icon_1024.png").exists():
        return

    iconset = assets / "icon.iconset"
    iconset.mkdir(exist_ok=True)
    mapping = {
        "icon_16x16.png": "icon_16.png",
        "icon_16x16@2x.png": "icon_32.png",
        "icon_32x32.png": "icon_32.png",
        "icon_32x32@2x.png": "icon_64.png",
        "icon_128x128.png": "icon_128.png",
        "icon_128x128@2x.png": "icon_256.png",
        "icon_256x256.png": "icon_256.png",
        "icon_256x256@2x.png": "icon_512.png",
        "icon_512x512.png": "icon_512.png",
        "icon_512x512@2x.png": "icon_1024.png",
    }
    for target, source in mapping.items():
        path = assets / source
        if path.exists():
            shutil.copy2(path, iconset / target)
    done = subprocess.run(["iconutil", "-c", "icns", str(iconset),
                           "-o", str(assets / "podcast-magic.icns")])
    if done.returncode == 0:
        print("Kuvake: assets/podcast-magic.icns")
    shutil.rmtree(iconset, ignore_errors=True)


def build(clean: bool = False, fetch: bool = True, dmg: bool = False) -> int:
    os.chdir(ROOT_DIR)
    ensure_icons()

    bin_dir = ROOT_DIR / "bin"
    have_ffmpeg = (bin_dir / "ffmpeg").exists() or (bin_dir / "ffmpeg.exe").exists()
    if fetch and not have_ffmpeg:
        # ffmpeg on ainoa ehdoton ulkoinen riippuvuus: ilman sitä ääntä ei saa
        # levyltä lainkaan, ei litterointiin eikä tason mittaukseen.
        print("Haetaan staattiset ffmpeg-binäärit…")
        sys.path.insert(0, str(ROOT_DIR / "scripts"))
        from fetch_binaries import fetch_binaries

        fetch_binaries()

    spec = ROOT_DIR / "podcast-magic.spec"
    if not spec.exists():
        print(f"Virhe: {spec} puuttuu.", file=sys.stderr)
        return 1

    cmd = [sys.executable, "-m", "PyInstaller"]
    if clean:
        cmd.append("--clean")
    cmd += ["-y", str(spec)]
    print(f"Käännetään: {' '.join(cmd)}")
    done = subprocess.run(cmd)
    if done.returncode != 0:
        print("Käännös epäonnistui.", file=sys.stderr)
        return done.returncode

    if sys.platform == "darwin":
        bundle = ROOT_DIR / "dist" / f"{APP_NAME}.app"
        if bundle.exists():
            print(f"\nValmis:\n  {bundle}")
        if dmg:
            sys.path.insert(0, str(ROOT_DIR / "scripts"))
            from make_dmg import make_dmg

            return make_dmg(app_path=bundle)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Käännä Podcast Magic sovellukseksi.")
    parser.add_argument("--clean", action="store_true", help="puhdista build-hakemistot")
    parser.add_argument("--no-fetch", dest="fetch", action="store_false",
                        help="älä hae ffmpeg-binäärejä")
    parser.add_argument("--dmg", action="store_true", help="pakkaa myös levykuvaksi")
    args = parser.parse_args()
    sys.exit(build(clean=args.clean, fetch=args.fetch, dmg=args.dmg))


if __name__ == "__main__":
    main()
