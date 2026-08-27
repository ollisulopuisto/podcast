"""Kirjaston viestit ja isännän käännös."""

import pytest

from speechmix import messages


@pytest.fixture(autouse=True)
def _clean():
    """Kääntäjä on prosessin laajuinen: testi ei saa jättää omaansa."""
    messages.set_translator(None)
    yield
    messages.set_translator(None)


def test_the_library_speaks_without_a_host():
    """Kirjastoa on voitava käyttää ilman isännän käännöskoneistoa.

    Kolmesta sovelluksesta vain yhdellä on i18n. Jos kirjasto vaatisi sen,
    kaksi muuta joutuisivat rakentamaan tyhjän kuoren pelkästään voidakseen
    tuoda paketin — ja virheteksti on tässä se ainoa asia joka kertoo mitä
    meni pieleen.
    """
    text = messages.t("audio.plugin_length", before=100, after=95)
    assert "100" in text and "95" in text
    assert "audio.plugin_length" not in text, "avain vuoti tekstiin"


def test_an_unknown_key_still_says_something_useful():
    """Tuntematon avain ei saa kaataa eikä hävitä.

    Virheen käsittely on juuri se polku jota ei koeajeta, ja
    ``KeyError`` sen sisällä korvaisi oikean syyn väärällä.
    """
    text = messages.t("audio.ei_tallaista", name="mikki")
    assert "audio.ei_tallaista" in text
    assert "mikki" in text


def test_the_host_translation_wins():
    """Isäntä antaa oman käännöksensä, ja sitä käytetään.

    autoraffkatilla on kaksi kieltä ja ``ContextVar``iin sidottu valinta,
    koska käsittely ajaa taustasäikeessä samalla kun käyttöliittymä kysyy
    tilaa. Kirjasto ei tiedä siitä mitään — se vain kysyy.
    """
    messages.set_translator(lambda key, **kw: f"HOST:{key}:{sorted(kw)}")
    assert messages.t("audio.plugin_length", before=1, after=2) \
        == "HOST:audio.plugin_length:['after', 'before']"


def test_a_broken_host_translator_does_not_break_the_chain():
    """Isännän käännös voi kaatua; käsittely ei saa kaatua sen mukana.

    Viesti syntyy aina virhepolulla, ja jos käännös nostaa poikkeuksen
    siinä, alkuperäinen syy katoaa ja tilalle tulee sekava jälki jostain
    aivan muualta.
    """
    def broken(key, **kw):
        raise RuntimeError("käännös hajosi")

    messages.set_translator(broken)
    text = messages.t("audio.chain_length", before=1, after=2)
    assert "1" in text and "2" in text


def test_the_host_language_reaches_the_library(monkeypatch):
    """Ketjun virhe tulee ulos isännän kielellä, ei kirjaston.

    Kirjasto ei tunne autoraffkatin i18n:ää eikä saa tuntea, mutta
    käyttäjä ei saa nähdä englantia suomenkielisessä käyttöliittymässä.
    Rekisteröinti on ainoa side, ja tämä on ainoa testi joka kertoo jos se
    katkeaa — se katkeaisi hiljaa, oikeaan aikaan ja väärällä kielellä.
    """
    messages.set_translator(
        lambda key, **kw: {"audio.chain_length":
                           "Käsittely muutti pituutta ({before} → {after})."}
        .get(key, key).format(**kw)
    )
    assert messages.t("audio.chain_length", before=100, after=95) \
        == "Käsittely muutti pituutta (100 → 95)."
