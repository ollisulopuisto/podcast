#!/usr/bin/env python3
"""Lataa staattiset ffmpeg- ja ffprobe-binäärit pakkausta varten.

macOS, Windows ja Linux, ja kaikki samasta julkaisusta: kolme lähdettä
tarkoittaisi kolmea eri ffmpeg-versiota samassa ohjelmassa, ja ero näkyisi
vasta jonkun koneella purettuna äänenä.
"""

from __future__ import annotations

import argparse
import hashlib
import platform
import shutil
import tempfile
import urllib.request
from pathlib import Path

# Binäärit tulevat `ffmpeg-static`-projektin julkaisuista. Sitä käyttää
# samanniminen npm-paketti, joten sitä ladataan päivittäin miljoonia kertoja —
# eli se on jotain muuta kuin yhden ihmisen kotisivu.
#
# Syy vaihtoon macOS:llä: evermeet.cx julkaisee vain x86_64-käännöksiä. Apple
# Siliconilla sellainen toimii vain Rosettan kautta, ja koko työkalun hitain
# vaihe on juuri ffmpeg. Rosettaa ei myöskään ole valmiiksi asennettuna, joten
# paketti pyysi ensimmäisellä ajolla asentamaan sen — tai jäi ilman
# verhokäyriä.
#
# Syy vaihtoon Windowsilla: gyan.dev-zip oli naulaamaton ja
# tarkistussummaton — `ffmpeg-release-essentials.zip` on eri tiedosto joka
# kuukausi, ja se on täsmälleen se ulkopuolisen palvelimen hiljainen vaihdos
# jota vastaan summat tässä ovat.
#
# Versio on naulattu ja tarkistussummat mukana. Käännösten pitää olla samat
# koneesta ja päivästä toiseen.
RELEASE = "b6.1.1"
BASE = f"https://github.com/eugeneware/ffmpeg-static/releases/download/{RELEASE}"

# (käyttöjärjestelmä, arkkitehtuuri) -> julkaisun tiedostonimen loppuosa.
SLUGS = {
    ("darwin", "arm64"): "darwin-arm64",
    ("darwin", "x86_64"): "darwin-x64",
    ("linux", "arm64"): "linux-arm64",
    ("linux", "x86_64"): "linux-x64",
    ("windows", "x86_64"): "win32-x64",
}

SHA256 = {
    "ffmpeg-darwin-arm64": "a90e3db6a3fd35f6074b013f948b1aa45b31c6375489d39e572bea3f18336584",
    "ffprobe-darwin-arm64": "bb2db6f5d8cef919da12fbf592119a987202a8c060a886f3cab091f9cab90b64",
    "ffmpeg-darwin-x64": "ebdddc936f61e14049a2d4b549a412b8a40deeff6540e58a9f2a2da9e6b18894",
    "ffprobe-darwin-x64": "fa3add0ce901f7241abe0dfc0155d958fc834aca3f8ce61f87cc712ae669c1e0",
    "ffmpeg-linux-x64": "e7e7fb30477f717e6f55f9180a70386c62677ef8a4d4d1a5d948f4098aa3eb99",
    "ffprobe-linux-x64": "4f231a1960d83e403d08f7971e271707bec278a9ae18e21b8b5b03186668450d",
    "ffmpeg-linux-arm64": "6bb182d0d75d23028db82e9e4f723ca69b853d055698486e6984ddb2c06fb8ce",
    "ffprobe-linux-arm64": "d17ae9b4c297d48e2521ba14e417bb0537c6ff77c584cdbcd6bb0d8d0307a2e8",
    "ffmpeg-win32-x64": "04e1307997530f9cf2fe35cba2ca7e8875ca91da02f89d6c7243df819c94ad00",
    "ffprobe-win32-x64": "3a7e2dc003dc2cd1472827e4c7c4f056ae1ae0ae7c5bbc580c99b49827351ba4",
}


def os_name(raw: str | None = None) -> str:
    """`platform.system()`in monta kirjoitustapaa yhdeksi nimeksi."""
    name = (raw or platform.system()).lower()
    if "darwin" in name or "mac" in name:
        return "darwin"
    if "win" in name:
        return "windows"
    return "linux"


def arch_name(raw: str | None = None) -> str:
    machine = (raw or platform.machine()).lower()
    return "arm64" if machine in ("aarch64", "arm64") else "x86_64"


def slug_for(target_os: str, arch: str) -> str:
    try:
        return SLUGS[(os_name(target_os), arch_name(arch))]
    except KeyError:
        raise SystemExit(
            f"Ei binäärejä alustalle {os_name(target_os)}-{arch_name(arch)}. "
            f"Tuetut: {', '.join(f'{o}-{a}' for o, a in SLUGS)}"
        ) from None


def tool_filename(tool: str, target_os: str) -> str:
    return f"{tool}.exe" if os_name(target_os) == "windows" else tool


def _verify(path: Path, expected: str) -> None:
    """Tarkistussumma. Väärä tiedosto ei saa päätyä pakettiin hiljaa."""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != expected:
        raise SystemExit(
            f"Tarkistussumma ei täsmää: {path.name}\n  odotettu {expected}\n  saatu    {digest}"
        )


def _arch_of(path: Path) -> str:
    """Mach-O-binäärin arkkitehtuuri, tai '?' jos sitä ei saa selville.

    Luetaan otsikosta eikä `file`-komennolla, jotta tämä toimii myös siellä
    missä sitä ei ole. Vain macOS: siellä väärä arkkitehtuuri on se joka
    toimii kääntäjän koneella ja hajoaa käyttäjän koneella.
    """
    with open(path, "rb") as fh:
        head = fh.read(8)
    if len(head) < 8 or head[:4] not in (b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe"):
        return "?"
    cpu = int.from_bytes(head[4:8], "little")
    return {0x0100000C: "arm64", 0x01000007: "x86_64"}.get(cpu, "?")


def download_file(url: str, dest: Path) -> None:
    print(f"Ladataan: {url} -> {dest}")
    urllib.request.urlretrieve(url, str(dest))


def fetch_binaries(
    target_os: str | None = None, output_dir: Path | None = None
) -> Path:
    system = os_name(target_os)
    arch = arch_name()
    slug = slug_for(system, arch)

    dest_dir = output_dir or (Path(__file__).resolve().parents[1] / "bin")
    dest_dir.mkdir(parents=True, exist_ok=True)

    print(f"Haetaan binäärit alustalle {slug} kohteeseen {dest_dir}...")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        for tool in ("ffmpeg", "ffprobe"):
            asset = f"{tool}-{slug}"
            dest = dest_dir / tool_filename(tool, system)
            if dest.exists():
                if system != "darwin" or _arch_of(dest) == arch:
                    print(f"{tool} on jo olemassa kohteessa {dest}")
                    continue
                print(f"{tool} on väärää arkkitehtuuria, haetaan uudestaan")
                dest.unlink()

            temp = tmp_path / asset
            download_file(f"{BASE}/{asset}", temp)
            _verify(temp, SHA256[asset])
            shutil.copy2(temp, dest)
            dest.chmod(0o755)
            print(f"Asennettu: {dest}")

    return dest_dir


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Hae staattiset ffmpeg- ja ffprobe-binäärit."
    )
    parser.add_argument(
        "--os", choices=["darwin", "windows", "linux"], help="Kohdekäyttöjärjestelmä"
    )
    parser.add_argument("--dest", type=Path, help="Kohdehakemisto (oletus: ./bin)")
    args = parser.parse_args()

    fetch_binaries(target_os=args.os, output_dir=args.dest)


if __name__ == "__main__":
    main()
