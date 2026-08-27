"""Ikkunan nimi macOS:n valikkorivillä.

Kehityksessä ajettava nippu on Pythonin oma, joten valikkorivissä ja telakassa
lukee «Python». Ikkunan otsikko on oikein, joten vika ei näy mistään muualta
kuin siitä yhdestä paikasta jossa käyttäjä lukee ohjelman nimen.
"""

from __future__ import annotations

from Foundation import NSBundle

from podcastmagic import gui


def bundle_name() -> str | None:
    """Nimi sieltä mistä macOS sen lukee.

    Ei ohituksia puuttuvan pyobjc:n varalta: `pywebview` on kova riippuvuus ja
    testit ajetaan macOS:llä, joten ohitus tarkoittaisi vain sitä ettei tämä
    ole koskaan ajanut.
    """
    bundle = NSBundle.mainBundle()
    info = bundle.localizedInfoDictionary() or bundle.infoDictionary()
    return None if info is None else info.get("CFBundleName")


def test_app_is_named_after_the_app_not_the_interpreter():
    gui.name_the_app()
    assert bundle_name() == "Podcast Magic"
