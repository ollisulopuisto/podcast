"""Versionumero on kolmessa paikassa, ja sen pitää olla sama joka kerta.

Sovelluspaketin ``CFBundleVersion`` ratkaisee, tarjoaako macOS päivitystä.
Jos se jää jälkeen `pyproject.toml`ista, käyttöliittymä kertoo yhtä versiota
ja Finderin tiedot toista — eikä kumpikaan ole väärin millään tavalla joka
kaataisi mitään.
"""

from __future__ import annotations

import re
from pathlib import Path

from podcastmagic import __version__

ROOT = Path(__file__).resolve().parents[1]


def test_pyproject_and_package_agree():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert re.search(r'^version = "(.+)"$', text, re.M).group(1) == __version__


def test_the_bundle_version_agrees():
    text = (ROOT / "podcast-magic.spec").read_text(encoding="utf-8")
    assert re.search(r'PM_VERSION", "(.+?)"', text).group(1) == __version__
