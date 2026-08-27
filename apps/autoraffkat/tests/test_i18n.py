"""Käännösten ja jaetun kirjaston sauma.

autoraffkat rekisteröi oman ``t``:nsä ``speechmix``in kääntäjäksi. Sauma on
kapea mutta ei triviaali: kirjasto liikkuu viikoittain ja sen viesti voi
olla olemassa ennen kuin tämän luettelossa on sille riviä.
"""

import pytest

import speechmix
from autoraffkat import i18n


@pytest.fixture(autouse=True)
def _finnish():
    token = i18n._current.set("fi")
    yield
    i18n._current.reset(token)


def test_a_library_message_comes_out_in_finnish():
    """Kirjaston avain, tämän teksti."""
    assert speechmix.messages.t("binaries.missing", name="ffmpeg").startswith(
        "ffmpeg puuttuu"
    )


def test_a_key_this_catalogue_lacks_falls_back_to_the_library_english():
    """Tuntematon avain ei saa päätyä ruudulle sellaisenaan.

    ``i18n.t`` palauttaa tuntemattoman avaimen sellaisenaan, mikä on oikein
    tämän omille viesteille — kaikki ovat luettelossa. Kirjaston viesteille
    se olisi väärin: kirjasto voi lisätä avaimen ennen kuin tämä lisää
    rivin, ja silloin käyttäjä lukisi ruudulta «audio.chain_length».
    Rekisteröity kääntäjä kieltäytyy tuntemattomasta, ja ``messages.t``
    käyttää omaa englantiaan.
    """
    speechmix.messages.FALLBACK["testi.vain_kirjastossa"] = "Only in the library."
    try:
        assert (
            speechmix.messages.t("testi.vain_kirjastossa") == "Only in the library."
        )
    finally:
        del speechmix.messages.FALLBACK["testi.vain_kirjastossa"]


def test_the_two_catalogues_agree_on_placeholders():
    """Sama avain, samat muotoiluarvot molemmissa luetteloissa.

    Eri nimi ei kaada mitään: ``t`` nappaa ``KeyError``in ja palauttaa
    muotoilemattoman tekstin, joten käyttäjä lukisi «{name} puuttuu» ja
    virheen syy jäisi kertomatta.
    """
    import string

    def fields(text):
        return {
            name for _, name, _, _ in string.Formatter().parse(text) if name
        }

    mismatched = {}
    for key, template in speechmix.messages.FALLBACK.items():
        entry = i18n.CATALOG.get(key)
        if entry is None:
            continue
        for lang, text in entry.items():
            if fields(text) != fields(template):
                mismatched[f"{key}/{lang}"] = (fields(template), fields(text))
    assert not mismatched, mismatched


def test_every_catalogue_entry_has_both_languages():
    missing = {
        key: sorted(set(i18n.LANGUAGES) - set(entry))
        for key, entry in i18n.CATALOG.items()
        if set(i18n.LANGUAGES) - set(entry)
    }
    assert not missing, missing
