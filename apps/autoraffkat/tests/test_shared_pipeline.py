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
from speechmix import envelopes, freshness, masks


def test_the_ducking_decision_comes_from_the_library():
    assert mix.duck_envelopes is envelopes.duck_envelopes
    assert mix.envelope_at is envelopes.envelope_at


def test_the_app_converts_and_the_library_computes():
    """Kaksi noista neljästä ei ole enää sama olio, ja niin kuuluukin.

    ``closed_ranges`` ja ``speech_blocks`` ottavat nyt ``Track``in, joten
    sovellukseen jää nimenomaan se mikä sille kuuluu: muunnos omasta
    istuntoformaatista. Identiteetti ei siis enää kelpaa mittariksi — sen
    tilalle tulee kaksi vahvempaa. Ensin: sovelluksen versio antaa täsmälleen
    saman tuloksen kuin kirjaston, eli se todella delegoi eikä laske itse.
    """
    from fractions import Fraction

    import numpy as np

    from autoraffkat.model import MediaItem, Placement

    item = MediaItem(
        key="k", name="n", path="/x.wav", src="",
        asset_start=Fraction(10),
        placements=[Placement(offset=Fraction(5), start=Fraction(13),
                              duration=Fraction(4))],
    )
    closed = np.zeros(500, dtype=bool)
    closed[300:400] = True

    assert mix.closed_ranges(item, closed, 0.0, 48000) == envelopes.closed_ranges(
        mix.track_of(item), closed, 0.0, 48000
    )


def test_the_timeline_formula_lives_in_exactly_one_function():
    """Ja toiseksi: ``asset_start`` esiintyy sovelluksessa vain ``track_of``issa.

    Aikajanan ja tiedostoajan muunnos oli kahdeksassa kohdassa, ja se on
    kaava joka ei kaadu kun se menee väärin — se tuottaa kelvollisen, oikean
    mittaisen tiedoston väärässä kohdassa. Kopio ei siis paljastu ajamalla,
    vaan vasta kuuntelemalla valmista ohjelmaa. Siksi tämä luetaan
    lähdekoodista eikä käyttäytymisestä.
    """
    import ast
    from pathlib import Path

    source = Path(mix.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    outside = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name == "track_of":
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Attribute) and inner.attr == "asset_start":
                outside.append(f"{node.name}:{inner.lineno}")
    assert not outside, f"aikajanamuunnos on myös täällä: {outside}"


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
