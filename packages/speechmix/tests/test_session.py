"""Sauma: raitoja joilla on paikka ohjelman aikajanalla.

Nämä testit ovat paketin README:n lupaus koodina. Kirjasto ei saa tuntea
yhtäkään istuntoformaattia, joten aikajanan tieto on **jaksoina** — alku,
loppu ja tiedostoaika alussa — eikä FCPXML:n ``placements``-olioina. Jokainen
alla oleva funktio oli ennen tätä joko autoraffkatin ``audio/mix.py``:ssä tai
``envelopes.py``:ssä ``item``-muodossa, jota vain yksi kolmesta sovelluksesta
osaa rakentaa.

Muunnos on jakson sisällä lineaarinen, ja se yksi kaava on kaikki mitä ketju
tarvitsee aikajanasta:

    tiedostoaika = jakso.file_offset + (ohjelma-aika - jakso.start)
"""

from fractions import Fraction

import numpy as np
import pytest

from speechmix import session
from speechmix.masks import HOP

RATE = 48000


def test_the_one_formula_holds_inside_a_span():
    """Jakson sisällä kuvaus on lineaarinen, ja tämä on se kaava."""
    span = session.Span(start=10.0, end=20.0, file_offset=3.0)
    assert span.base == pytest.approx(-7.0)  # tiedostoaika = base + aikajana
    assert span.file_at(10.0) == pytest.approx(3.0)
    assert span.file_at(15.0) == pytest.approx(8.0)
    assert span.duration == pytest.approx(10.0)


def test_exact_rationals_survive_the_seam():
    """autoraffkat antaa Fractioneita, ja niiden on pysyttävä tarkkoina.

    FCPXML:n ajat ovat rationaalilukuja (1001/30000 s ruutu), ja ruudukon
    reunalla liukuluvun viimeinen bitti riittää pudottamaan solun. Sauma ei
    saa pakottaa niitä liukuluvuiksi — se on muunnos, ei kuvaus.
    """
    span = session.Span(
        start=Fraction(1001, 30000), end=Fraction(2002, 30000),
        file_offset=Fraction(1, 3),
    )
    assert span.base == Fraction(1, 3) - Fraction(1001, 30000)
    assert isinstance(span.base, Fraction)


def _track(*spans, speaker="A"):
    return session.Track(
        path="", speaker=speaker,
        spans=[session.Span(*s) for s in spans],
    )


def test_file_ranges_map_the_grid_to_file_samples():
    """Ruudukko on aikajanan aikaa, tiedosto omaansa."""
    # Aikajanan hetki 10 on tiedoston hetki 0.
    track = _track((10.0, 20.0, 0.0))
    mask = np.zeros(int(20.0 / HOP), dtype=bool)
    mask[int(11.0 / HOP) : int(12.0 / HOP)] = True  # aikajanalla 11–12 s

    ranges = session.file_ranges(track, mask, program_start=0.0, rate=RATE)

    assert ranges == [(int(1.0 * RATE), int(2.0 * RATE))]


def test_file_ranges_stay_inside_the_span():
    """Jakson ulkopuolella ei ole tiedostoa, joten sinne ei kirjoiteta."""
    track = _track((10.0, 12.0, 0.0))
    mask = np.zeros(int(20.0 / HOP), dtype=bool)
    mask[int(15.0 / HOP) : int(16.0 / HOP)] = True  # aikajanalla klipin jälkeen

    assert session.file_ranges(track, mask, program_start=0.0, rate=RATE) == []


def test_mask_samples_is_file_ranges_painted_out():
    """Sama muunnos, totuusarvotaulukkona: vuodon estimointi lukee tätä."""
    track = _track((0.0, 4.0, 0.0))
    mask = np.zeros(int(4.0 / HOP), dtype=bool)
    mask[int(1.0 / HOP) : int(2.0 / HOP)] = True

    out = session.mask_samples(track, mask, 0.0, RATE, 4 * RATE)

    assert out[: RATE].sum() == 0
    assert out[RATE : 2 * RATE].all()
    assert out[2 * RATE :].sum() == 0


def test_mask_blocks_answers_per_block_not_per_sample():
    """Tasonkuljettaja kysyy lohkoittain: puhuiko omistaja tässä lohkossa."""
    track = _track((0.0, 4.0, 0.0))
    mask = np.zeros(int(4.0 / HOP), dtype=bool)
    mask[int(1.0 / HOP) : int(2.0 / HOP)] = True
    block = RATE // 2  # puoli sekuntia

    out = session.mask_blocks(track, mask, 0.0, RATE, block, 8)

    # Lohkot 2 ja 3 ovat sekunnit 1,0–2,0.
    assert list(out) == [False, False, True, True, False, False, False, False]


def test_overlaps_separates_the_parts_of_a_multicam():
    """Peräkkäisten osien mikit eivät voi vuotaa toisiinsa.

    Ilman tätä toisen osan tiedosto tarjottiin vuotolähteeksi, ``aligned``
    palautti pelkkää nollaa, ja lokiin tuli «vuotopolkua ei saatu ratkaistua»
    pariutumisesta joka ei ollut koskaan mahdollinen.
    """
    a = _track((0.0, 10.0, 0.0))
    b = _track((10.0, 20.0, 0.0))
    assert session.overlaps(a, a)
    assert not session.overlaps(a, b)
    assert not session.overlaps(b, a)
    assert session.overlaps(_track((0.0, 10.0, 0.0)), _track((9.0, 20.0, 0.0)))


def test_aligned_puts_the_partner_on_the_same_timeline_moment():
    """Eri tiedostot, eri alut — vuotoa ei voi vähentää ennen kohdistusta.

    Oli ``mix._aligned``, ja tämän paketin oma testi joutui tuomaan
    autoraffkatin päästäkseen siihen käsiksi. Kirjaston testi joka tuo
    sovelluksen on merkki siitä että koodi on väärässä paketissa.
    """
    # Kohde alkaa aikajanan hetkellä 0 tiedoston hetkestä 0.
    target = _track((0.0, 4.0, 0.0))
    # Lähde on samassa aikajanan kohdassa mutta alkaa tiedostossaan
    # sekunnin myöhemmin.
    source = _track((0.0, 4.0, 1.0), speaker="B")

    audio = np.arange(4 * RATE, dtype=np.float64)
    out = session.aligned(target, source, audio, RATE, 4 * RATE)

    # Aikajanan hetki 0 on lähdetiedoston hetki 1 s.
    assert out[0] == pytest.approx(float(RATE))
    assert out[RATE] == pytest.approx(float(2 * RATE))


def test_geometry_tells_stems_apart_by_where_they_sit():
    """Summa lasketaan näyte näytteeltä, mikä on oikein vain samassa kohdassa."""
    frames = 4 * RATE
    here = _track((0.0, 4.0, 0.0))
    also_here = _track((0.0, 4.0, 0.0), speaker="B")
    elsewhere = _track((4.0, 8.0, 0.0), speaker="C")

    assert session.geometry(here, frames) == session.geometry(also_here, frames)
    assert session.geometry(here, frames) != session.geometry(elsewhere, frames)
    assert session.geometry(here, frames) != session.geometry(here, frames + 1)


def test_a_whole_file_is_a_track_with_one_span():
    """automixerin muoto: koko tiedosto yhdessä kohdassa aikajanaa.

    Tämä on koko sauma wav-isännälle. Sen jälkeen ruudukko, vaimennus,
    ristivuoto ja tasonkuljettaja ovat samaa koodia kuin autoraffkatilla.
    """
    track = session.whole_file("a.wav", "Olli", start=2.5, duration=7.5)

    assert track.speaker == "Olli"
    assert len(track.spans) == 1
    assert track.spans[0].start == pytest.approx(2.5)
    assert track.spans[0].end == pytest.approx(10.0)
    # Tiedoston hetki 0 on aikajanan hetki 2,5.
    assert track.spans[0].file_at(2.5) == pytest.approx(0.0)
    assert track.spans[0].file_at(5.0) == pytest.approx(2.5)
