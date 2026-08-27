"""Ketju tulee kirjastosta, eikä siitä ole toista kopiota.

Tämä testi ei mittaa ääntä. Se mittaa sitä ettei kukaan ole vahingossa
kopioinut jaettua laskentaa takaisin sovellukseen — mikä on juuri se
ajautuminen jonka takia ``packages/speechmix`` on olemassa. Kopio ei kaadu
mihinkään: se toimii, ja alkaa hiljaa erota alkuperäisestä.

Identiteettivertailu on tarkoituksellinen. ``is`` menee läpi vain jos
sovellus käyttää **samaa oliota** kuin kirjasto; sisällöltään samanlainen
kopio hylätään.
"""

from autoraffkat import decide
from autoraffkat.audio import mix
from speechmix import envelopes, freshness, masks, session


def test_the_ducking_decision_comes_from_the_library():
    assert mix.duck_envelopes is envelopes.duck_envelopes
    assert mix.envelope_at is envelopes.envelope_at


def test_the_timeline_arithmetic_comes_from_the_library():
    """Aikajanan ja tiedostoajan välinen muunnos on saumaa, ei sovellusta.

    ``closed_ranges``, ``speech_blocks``, ``_mask_samples``, ``_aligned`` ja
    ``overlaps`` olivat kaikki samaa yhtä kaavaa, ja kolme viimeistä olivat
    tässä tiedostossa ``item.placements``in muodossa — kirjastossa mutta vain
    yhden sovelluksen ulottuvilla. automixerin vaimennus, ristivuoto ja
    tasonkuljettaja jäivät sen takia tekemättä.

    ``session.py`` on nyt niiden koti, ja ``MediaItem.as_track`` on se osa
    joka jää tänne: se on kaikki mitä FCPXML:n tuntemista tarvitaan.
    """
    assert mix.session is session


def test_the_duck_defaults_are_the_measured_ones():
    """Mitattu luku kopioituna on kaksi vastausta samaan kysymykseen.

    Vaimennuksen ajat ja syvyys mitattiin oikealla aineistolla ja olivat
    tässä sovelluksessa. Toinen isäntä olisi kirjoittanut omansa, eivätkä
    ne kaataisi mitään — ne alkaisivat vain erota, ja kaksi eri vaimennusta
    yhden nimen alla on tarkalleen se vika jota vastaan tämä työtila on.

    automixerin puolella on tämän peilikuva. Kummankin sovelluksen
    lukema tarkistetaan **kirjastoa** vastaan eikä toista sovellusta
    vastaan: kirjasto on se yksi paikka jossa muutos tehdään, eikä
    kummankaan testin tarvitse tuoda toista sovellusta sisään.
    """
    from autoraffkat.model import AudioSettings

    settings = AudioSettings()
    assert settings.duck_db == masks.DUCK_DB
    assert settings.duck_fade == masks.DUCK_FADE
    assert settings.duck_release == masks.DUCK_RELEASE
    assert settings.duck_hold == masks.DUCK_HOLD
    assert settings.duck_lookahead == masks.DUCK_LOOKAHEAD
    assert settings.duck_min_open == masks.DUCK_MIN_OPEN
    assert settings.duck_min_closed == masks.DUCK_MIN_CLOSED
    assert settings.duck_dominance_db == masks.DUCK_DOMINANCE_DB


def test_the_masks_come_from_the_library():
    assert mix.duck_masks is masks.duck_masks
    assert mix.solo_masks is masks.solo_masks
    assert mix.speech_masks is masks.speech_masks


def test_the_window_helpers_come_from_the_library():
    """Kuvan leikkaus ja äänen vaimennus lukevat samaa puheentunnistusta.

    Kaksi kopiota näistä tarkoittaisi että portti aukeaa kuvalle ja äänelle
    eri hetkellä, eikä mikään kertoisi siitä.
    """
    assert decide.open_windows is masks.open_windows
    assert decide.drop_short is masks.drop_short
    assert decide.trim_end is masks.trim_end
    assert decide._runs is masks.runs


def test_the_fingerprint_fields_come_from_the_library():
    """Kentät kuvaavat mitä ketju tekee, joten ne kuuluvat ketjulle.

    Missä leima sijaitsee on sovelluksen asia, ja se jää tänne.
    """
    assert mix.FINGERPRINT_FIELDS is freshness.FINGERPRINT_FIELDS
    assert mix.FINGERPRINT_VERSION == freshness.FINGERPRINT_VERSION
    assert hasattr(mix, "stamp_dir"), "leiman sijainti on sovelluksen omaa"


def test_the_hop_is_one_number_for_the_whole_workspace():
    from autoraffkat.model import HOP

    assert HOP is masks.HOP
