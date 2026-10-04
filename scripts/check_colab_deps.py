#!/usr/bin/env python3
"""Tarkistaa Google Colab -ketjun (pipeline.py) riippuvuuksien versiopäivitykset PyPI:stä.

Lukee nykyiset lukitut versiot `colab-transcribe/src/colabtranscribe/colab/pipeline.py` -tiedostosta
ja vertaa niitä PyPI:n uusimpiin julkaistuihin versioihin.
Voidaan ajaa paikallisesti tai osana GitHub Actions -ajastusta.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PIPELINE_PATH = (
    ROOT / "colab-transcribe" / "src" / "colabtranscribe" / "colab" / "pipeline.py"
)


def parse_locked_packages(content: str) -> dict[str, str]:
    """Poimii pipeline.py:n install_dependencies()-funktion paketit ja versiot."""
    m = re.search(r"packages\s*=\s*\[(.*?)\]", content, re.DOTALL)
    if not m:
        return {}

    packages: dict[str, str] = {}
    for line in m.group(1).splitlines():
        line = line.strip().strip(",").strip('"').strip("'")
        if not line or line.startswith("#"):
            continue
        if "==" in line:
            pkg, ver = line.split("==", 1)
            packages[pkg.strip()] = ver.strip()
        elif "<" in line:
            pkg, ver = line.split("<", 1)
            packages[pkg.strip()] = f"<{ver.strip()}"
        else:
            packages[line] = "latest"
    return packages


def fetch_latest_pypi_version(package_name: str, timeout: float = 10.0) -> str:
    """Hakee paketin uusimman julkisen version PyPI:n JSON API:sta."""
    url = f"https://pypi.org/pypi/{package_name}/json"
    req = urllib.request.Request(url, headers={"User-Agent": "podcast-colab-dep-checker"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
            return str(data.get("info", {}).get("version", "unknown"))
    except Exception as err:
        return f"virhe: {err}"


def format_markdown_report(locked: dict[str, str], latest: dict[str, str]) -> str:
    """Luo markdown-muotoisen taulukon ja yhteenvedon tilasta."""
    lines = [
        "## Colab-transcribe: Riippuvuuksien päivitystarkistus",
        "",
        "| Paketti | Lukittu | Uusin PyPI | Tila |",
        "| :--- | :--- | :--- | :--- |",
    ]

    has_updates = False
    for pkg, locked_ver in locked.items():
        latest_ver = latest.get(pkg, "tuntematon")
        if latest_ver.startswith("virhe"):
            status = f"⚠️ {latest_ver}"
        elif locked_ver != latest_ver and not locked_ver.startswith("<"):
            status = "🔄 Päivitettävissä"
            has_updates = True
        elif locked_ver.startswith("<"):
            status = f"🔒 Rajattu ({locked_ver})"
            has_updates = True
        else:
            status = "✅ Ajantasalla"
        lines.append(f"| {pkg} | {locked_ver} | {latest_ver} | {status} |")

    lines.append("")
    if has_updates:
        lines.append(
            "> [!NOTE]\n"
            "> **Päivityksiä saatavilla.** Tarkista uudet versiot ja testaa yhteensopivuus "
            "ennen `pipeline.py`:n versioiden nostoa."
        )
    else:
        lines.append("✅ **Kaikki riippuvuudet ovat ajantasalla.**")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Tarkista Colab-ketjun riippuvuudet PyPI:stä")
    parser.add_argument(
        "--pipeline",
        type=Path,
        default=DEFAULT_PIPELINE_PATH,
        help="Polku pipeline.py -tiedostoon",
    )
    args = parser.parse_args()

    pipeline_file = args.pipeline
    if not pipeline_file.is_file():
        sys.stderr.write(f"Virhe: Tiedostoa ei löydy: {pipeline_file}\n")
        return 1

    content = pipeline_file.read_text(encoding="utf-8")
    locked = parse_locked_packages(content)
    if not locked:
        sys.stderr.write("Virhe: Ei löydetty paketteja pipeline.py:stä.\n")
        return 1

    latest = {}
    for pkg in locked:
        latest[pkg] = fetch_latest_pypi_version(pkg)

    report = format_markdown_report(locked, latest)
    print(report)

    # Kirjoita GitHub Actions Step Summaryyn jos ympäristömuuttuja on asetettu
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as f:
            f.write(report + "\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
