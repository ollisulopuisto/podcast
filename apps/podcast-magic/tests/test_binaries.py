"""Niputettavat ffmpeg-binäärit: yksi lähde, naulattu versio, tarkistussummat.

Väärä tai vaihtunut binääri ei näy mistään: paketti kääntyy, käynnistyy ja
kaatuu vasta käyttäjän koneella ensimmäiseen ääneen.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import fetch_binaries as fb


def test_every_supported_platform_has_a_pinned_checksum():
    for slug in fb.SLUGS.values():
        for tool in ("ffmpeg", "ffprobe"):
            assert f"{tool}-{slug}" in fb.SHA256, f"{tool}-{slug}"


def test_the_three_platforms_we_build_for_are_supported():
    """Windows ja Linux ovat mukana, eivät vain valitsimessa.

    `--os linux` oli argparsen valinta ilman haaraa: komento onnistui,
    hakematta mitään, ja käännös jatkoi ilman ffmpegiä.
    """
    assert fb.slug_for("darwin", "arm64") == "darwin-arm64"
    assert fb.slug_for("darwin", "x86_64") == "darwin-x64"
    assert fb.slug_for("linux", "x86_64") == "linux-x64"
    assert fb.slug_for("linux", "arm64") == "linux-arm64"
    assert fb.slug_for("windows", "x86_64") == "win32-x64"


def test_the_names_on_disk_carry_the_windows_suffix():
    assert fb.tool_filename("ffmpeg", "windows") == "ffmpeg.exe"
    assert fb.tool_filename("ffmpeg", "linux") == "ffmpeg"
