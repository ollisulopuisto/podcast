"""Julkaise Mac ensin ja jaa liian suuret arkistot tarkistettaviksi osiksi."""

from __future__ import annotations

import argparse
import hashlib
import shlex
import subprocess
import tempfile
from pathlib import Path

# GitHubin vastauksen raja ajossa 40871931298: koko < 2147483648 tavua.
ASSET_LIMIT = 2_147_483_648
# Kokovalinta, ei mittaus: 1 GiB jättää reilusti tilaa API:n rajan alle.
PART_SIZE = 1_073_741_824
BUFFER_SIZE = 1024 * 1024


def split_archive(source: Path, destination: Path, *, part_size: int = PART_SIZE) -> list[Path]:
    """Lue arkisto kerran, pidä muistissa vain puskuri ja laske myös kokonaisuuden tiiviste."""
    if not 0 < part_size < ASSET_LIMIT:
        raise ValueError("Virheellinen osakoko")
    size = source.stat().st_size
    if size == 0:
        raise ValueError(f"Tyhjä arkisto: {source.name}")
    parts = []
    checksums = []
    archive_hash = hashlib.sha256()
    with source.open("rb") as reader:
        for index, offset in enumerate(range(0, size, part_size)):
            part = destination / f"{source.name}.part{index:04d}"
            part_hash = hashlib.sha256()
            remaining = min(part_size, size - offset)
            with part.open("xb") as writer:
                while remaining:
                    chunk = reader.read(min(BUFFER_SIZE, remaining))
                    if not chunk:
                        raise ValueError(f"Arkisto lyheni kesken jaon: {source.name}")
                    writer.write(chunk)
                    archive_hash.update(chunk)
                    part_hash.update(chunk)
                    remaining -= len(chunk)
            parts.append(part)
            checksums.append(f"{part_hash.hexdigest()}  {part.name}\n")
        if reader.read(1):
            raise ValueError(f"Arkisto kasvoi kesken jaon: {source.name}")
    checksums.append(f"{archive_hash.hexdigest()}  {source.name}\n")
    checksum_file = destination / f"{source.name}.sha256"
    checksum_file.write_text("".join(checksums), encoding="utf-8")
    readme = destination / f"{source.name}.reassemble.txt"
    command = "cat " + " ".join(shlex.quote(p.name) for p in parts)
    command += " > " + shlex.quote(source.name)
    readme.write_text(
        f"{source.name}: {size} bytes / tavua\n\n"
        "Lataa kaikki osat ja .sha256-tiedosto samaan hakemistoon.\n"
        "Yhdistä osat alla olevassa järjestyksessä ja tarkista tiivisteet.\n"
        "Pura arkisto vasta kun kaikki tarkistukset onnistuvat.\n\n"
        "Download all parts and the .sha256 file into the same directory.\n"
        "Run these commands there (Linux or macOS shell). Extract the archive\n"
        "only after every checksum passes. A missing or damaged part is an error.\n\n"
        f"{command}\nsha256sum -c {shlex.quote(checksum_file.name)}\n\n"
        "macOS: korvaa sha256sum komennolla shasum -a 256.\n"
        "macOS: replace sha256sum with shasum -a 256.\n",
        encoding="utf-8",
    )
    return [*parts, checksum_file, readme]


def prepare_asset(source: Path, destination: Path) -> list[Path]:
    """Raja on aidosti avoin: tasan 2 GiB täytyy myös jakaa."""
    size = source.stat().st_size
    if size == 0:
        raise ValueError(f"Tyhjä julkaisutiedosto: {source.name}")
    if size >= ASSET_LIMIT:
        print(f"Jaetaan / splitting {source.name}: {size} bytes, limit < {ASSET_LIMIT}", flush=True)
        return split_archive(source, destination)
    return [source]


def require_asset(dist: Path, pattern: str, platform: str) -> Path:
    """Puuttuva tai moniselitteinen paketti ei ole onnistunut julkaisu."""
    matches = sorted(dist.glob(pattern))
    if len(matches) != 1 or not matches[0].is_file():
        raise ValueError(f"{platform}: odotettiin yhtä pakettia ({pattern})")
    return matches[0]


def publish_macos(dist: Path, notes: Path, tag: str, repo: str) -> None:
    """Olemassa olevaa julkaisua ei poisteta eikä sen tiedostoja korvata."""
    mac = require_asset(dist, "podcast-magic-macos-*.dmg", "macOS")
    if not 0 < mac.stat().st_size < ASSET_LIMIT:
        raise ValueError("macOS: levykuvan täytyy olla epätyhjä ja alle 2 GiB")
    subprocess.run(
        ["gh", "release", "create", tag, str(mac), "--repo", repo,
         "--title", tag, "--notes-file", str(notes), "--generate-notes", "--verify-tag"],
        check=True,
    )


def publish_others(dist: Path, tag: str, repo: str) -> None:
    """Mac on jo saatavilla; muiden valmistelu- ja siirtovirheet jäävät virheiksi."""
    for platform, extension in [("windows", "zip"), ("linux", "tar.gz")]:
        archive = require_asset(dist, f"podcast-magic-{platform}-*.{extension}", platform)
        with tempfile.TemporaryDirectory(prefix="release-parts-", dir=dist) as directory:
            assets = prepare_asset(archive, Path(directory))
            subprocess.run(
                ["gh", "release", "upload", tag, *(str(p) for p in assets), "--repo", repo],
                check=True,
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True, choices=("macos", "others"))
    parser.add_argument("--dist", required=True, type=Path)
    parser.add_argument("--notes", type=Path)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--repo", required=True)
    args = parser.parse_args()
    if args.stage == "macos":
        if args.notes is None:
            parser.error("--notes vaaditaan macOS-julkaisulle")
        publish_macos(args.dist, args.notes, args.tag, args.repo)
    else:
        publish_others(args.dist, args.tag, args.repo)


if __name__ == "__main__":
    main()
