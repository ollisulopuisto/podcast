"""Versionumero on kolmessa paikassa, ja sen pitää olla sama joka kerta.

Sama vahti kuin podcast-magicilla. Sitä ei ollut tässä, ja mitattuna
kolme paikkaa olivat eri versioissa:

* ``pyproject.toml`` 2026.8.27.113 — se mistä julkaisu nimetään
* ``__init__.py`` 2026.8.26.95 — **tämä kirjoitetaan jokaiseen vientiin**
  ``fi.autoraffkat.version``-kenttään, eli 18 julkaisun ajan jokainen
  vienti on väittänyt olevansa jonkin muun version tekemä
* ``autoraffkat.spec`` 2026.8.22.49 — ``CFBundleVersion``, joka ratkaisee
  tarjoaako macOS päivitystä

Yksikään ero ei kaada mitään. Ne vain saavat jonkin kohdan kertomaan
väärää — ja «mikä versio tämän teki» on ensimmäinen kysymys silloin kun
jokin vienti käyttäytyy oudosti.
"""

from __future__ import annotations

import re
from pathlib import Path

from autoraffkat import __version__

ROOT = Path(__file__).resolve().parents[1]


def test_pyproject_and_package_agree():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert re.search(r'^version = "(.+)"$', text, re.M).group(1) == __version__


def test_the_bundle_version_agrees():
    """``CFBundleVersion`` ratkaisee tarjoaako macOS päivitystä."""
    text = (ROOT / "autoraffkat.spec").read_text(encoding="utf-8")
    assert re.search(r'"CFBundleVersion": "(.+?)"', text).group(1) == __version__
    assert (
        re.search(r'"CFBundleShortVersionString": "(.+?)"', text).group(1)
        == __version__
    )


def test_the_version_is_calver():
    """``YYYY.M.D.N``, kuten CONTRIBUTING sanoo. Tagi on tämä etuliitteellä."""
    assert re.fullmatch(r"20\d\d\.\d{1,2}\.\d{1,2}\.\d+", __version__), __version__
