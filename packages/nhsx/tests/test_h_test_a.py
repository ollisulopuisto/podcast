"""Mitattu istunto ``h-test A.nhsx``: mitä Hindenburg oikeasti kirjoittaa.

Istunto on tehty testisignaaleista (``scripts/generate_test_signals.py``,
PARSER-NEEDS.md File A) ja vietu Hindenburg PRO 2.05.2718:sta. Se mittaa
mitä lukijan on kestettävä: puuttuvat attribuutit, radan lajit, kaksi
erilaista häivytyskirjoitusta.
"""

from pathlib import Path

from nhsx.read import children, read

DATA = Path(__file__).parent / "data"


def test_missing_start_means_zero():
    """Hindenburg jättää ``Start``in kirjoittamatta kun se on nolla."""
    session = read(DATA / "h-test A.nhsx")
    first_track = session.tracks[0]
    assert first_track.name == "A1-A3"
    assert first_track.regions[0].start == 0.0
    assert first_track.regions[0].length == 5.0


def test_pan_and_volume_are_track_attributes():
    """Pan ja radan vahvistus ovat radan attribuutteja, eivät alueen."""
    session = read(DATA / "h-test A.nhsx")
    by_name = {t.name: t for t in session.tracks}
    assert by_name["A4"].elem.get("Pan") == "-0.25"
    assert by_name["A5"].elem.get("Pan") == "0.1"
    assert by_name["A6"].elem.get("Pan") is None
    assert by_name["A9-A10"].elem.get("Volume") == "6"
    assert by_name["A11"].elem.get("Volume") == "-6"


def test_region_gain_is_region_attribute():
    """Alueen Gain on alueen attribuutti (A10: Gain +6 radan Volyym +6 päällä)."""
    session = read(DATA / "h-test A.nhsx")
    by_name = {t.name: t for t in session.tracks}
    a10 = by_name["A9-A10"].regions[1]
    assert a10.elem.get("Gain") == "6.0"


def test_fadein_is_a_region_attribute():
    """A8:n häivytys on kirjoitettu alueen attribuutiksi ``FadeIn``.

    Tämä on toinen kahdesta häivytyskirjoituksesta: toinen on ``<Fade>``
    -lapselementti. Kumpikaan ei saa kadota lukematta.
    """
    session = read(DATA / "h-test A.nhsx")
    by_name = {t.name: t for t in session.tracks}
    a8 = by_name["A1-A3"].regions[4]
    assert a8.elem.get("FadeIn") == "01.600"


def test_fade_children_carry_start_length_gain():
    """A7: kaksi ``<Fade>``-lasta: ankka −10 dB:iin ja takaisin.

    Ilman Gainia luiska palaa ykköseen — sama mitta kuin
    ``tests/test_measured_session.py``ssä, nyt kahdella häivytyksellä.
    """
    session = read(DATA / "h-test A.nhsx")
    by_name = {t.name: t for t in session.tracks}
    a7 = by_name["A1-A3"].regions[3]
    fades = children(a7.elem, "Fade")
    assert len(fades) == 2
    assert fades[0].get("Start") == "02.500"
    assert fades[0].get("Length") == "01.666"
    assert fades[0].get("Gain") == "-10"
    assert fades[1].get("Start") == "10.834"
    assert fades[1].get("Length") == "01.666"
    assert fades[1].get("Gain") is None
