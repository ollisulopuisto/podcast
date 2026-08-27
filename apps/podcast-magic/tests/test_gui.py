"""Ikkunan nimi macOS:n valikkorivillä.

Kehityksessä ajettava nippu on Pythonin oma, joten valikkorivissä ja telakassa
lukee «Python». Ikkunan otsikko on oikein, joten vika ei näy mistään muualta
kuin siitä yhdestä paikasta jossa käyttäjä lukee ohjelman nimen.
"""

from __future__ import annotations

import sys

import pytest

from podcastmagic import gui

# Nipun nimi on macOS:n käsite, ja `Foundation` on olemassa vain siellä.
# Ohitus on alustan tosiasia eikä puuttuva työkalu: paketointiputki ajaa
# testit kaikilla kolmella alustalla, ja tämä on niistä yhden asia.
only_macos = pytest.mark.skipif(sys.platform != "darwin", reason="CFBundleName on macOS:n")


def bundle_name() -> str | None:
    """Nimi sieltä mistä macOS sen lukee.

    Tuonti on funktion sisällä: `Foundation` tulee pyobjc:n mukana eikä sitä
    ole muilla alustoilla, ja moduulitason tuonti kaataisi koko tiedoston
    keräyksen Linuxilla ennen kuin ainoakaan testi ajaa.
    """
    from Foundation import NSBundle

    bundle = NSBundle.mainBundle()
    info = bundle.localizedInfoDictionary() or bundle.infoDictionary()
    return None if info is None else info.get("CFBundleName")


@only_macos
def test_app_is_named_after_the_app_not_the_interpreter():
    gui.name_the_app()
    assert bundle_name() == "Podcast Magic"


def test_a_packaged_program_opens_a_window_only_where_there_is_one():
    """Ikkuna on oletus paketissa — paitsi Linuxilla.

    Pakattu ohjelma ei voi tulostaa osoitetta terminaaliin, joten ikkuna on
    oikea oletus. Linuxilla `pywebview` tarvitsee GTK:n ja WebKit2:n koneelta
    eikä paketista, ja niiden puuttuessa ohjelma ei avaisi mitään eikä
    kertoisi mitään — selain on siellä se joka varmasti on.
    """
    from podcastmagic.__main__ import wants_window

    assert wants_window(None, frozen=True, system="darwin") is True
    assert wants_window(None, frozen=True, system="win32") is True
    assert wants_window(None, frozen=True, system="linux") is False
    assert wants_window(None, frozen=False, system="darwin") is False
    # Pyydetty ikkuna on pyydetty ikkuna, myös Linuxilla.
    assert wants_window(True, frozen=False, system="linux") is True
    assert wants_window(False, frozen=True, system="darwin") is False
