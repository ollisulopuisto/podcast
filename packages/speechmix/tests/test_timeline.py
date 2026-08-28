"""A track with a placement on a programme timeline.

Not "an FCPXML asset". An FCPXML asset is that; an automixer session track is
that. The conversion between programme time and file time is linear inside a
span, and that one formula is all the timeline knowledge the pipeline needs.
"""

import numpy as np
import pytest

from speechmix.errors import NotMono
from speechmix.timeline import Span, Track, aligned, overlaps

RATE = 48000


def test_programme_time_maps_to_file_time():
    span = Span(programme_start=10.0, programme_end=20.0, file_offset=3.0)
    assert span.to_file_time(10.0) == 3.0
    assert span.to_file_time(12.5) == 5.5
    assert span.duration == 10.0


def test_a_track_knows_where_it_is_not():
    track = Track("mic.wav", "olli", [Span(10.0, 20.0, 3.0), Span(40.0, 50.0, 25.0)])
    assert track.to_file_time(12.0) == 5.0
    assert track.to_file_time(41.0) == 26.0
    assert track.to_file_time(30.0) is None, "a gap must be None, not an extrapolation"
    assert track.span_at(30.0) is None


def test_a_backwards_span_is_refused():
    with pytest.raises(ValueError):
        Span(programme_start=20.0, programme_end=10.0)


def test_a_microphone_is_always_mono():
    """Two channels break the arithmetic in three places silently: de-bleeding
    reads only the first channel, the programme ceiling broadcasts stems of
    differing channel counts, and panning is a mono-source idea.
    """
    with pytest.raises(NotMono):
        Track("mic.wav", "olli", [], mono=False)


def test_two_parts_of_a_multicam_never_overlap():
    """Peräkkäisten osien mikit eivät voi vuotaa toisiinsa.

    Ilman tätä toisen osan tiedosto tarjottiin silti vuotolähteeksi,
    ``aligned`` palautti pelkkää nollaa, ja lokiin tuli «vuotopolkua ei
    saatu ratkaistua» pariutumisesta joka ei ollut koskaan mahdollinen.
    Virheilmoitus jota ei voi uskoa on huonompi kuin ei ilmoitusta.

    Oli autoraffkatin ``mix.overlaps``. Se on puhdasta jaksogeometriaa eikä
    tunne FCPXML:ää, ja automixerin vuodonvähennys tarvitsee saman säännön.
    """
    first = Track("a.wav", "olli", [Span(0.0, 819.0)])
    second = Track("b.wav", "olli", [Span(819.0, 4632.0)])

    assert overlaps(first, first)
    assert not overlaps(first, second), "eri osat eivät ole päällekkäin"
    assert not overlaps(second, first)
    # Raja on kosketus, ei päällekkäisyys: peräkkäiset osat jakavat hetken.
    assert not overlaps(Track("", "", [Span(0.0, 10.0)]), Track("", "", [Span(10.0, 20.0)]))
    assert overlaps(Track("", "", [Span(0.0, 10.0)]), Track("", "", [Span(9.0, 20.0)]))


def test_the_partner_lands_on_the_same_timeline_moment():
    """Eri tiedostot, eri alut — vuotoa ei voi vähentää ennen kohdistusta.

    Kuvaus on jakson sisällä lineaarinen ja näytetaajuus sama, joten tämä on
    kokonaisluvun siirto. Uudelleennäytteistys siirtäisi vaihetta ja pilaisi
    juuri sen mitä vuodon estimoinnissa yritetään mitata.

    Oli autoraffkatin ``mix._aligned``, jonne automixer ei ylety.
    """
    # Kohde on aikajanan hetkellä 0 tiedostonsa hetkestä 0.
    target = Track("target.wav", "a", [Span(0.0, 4.0, 0.0)])
    # Lähde on samassa kohdassa aikajanaa mutta alkaa tiedostossaan
    # sekunnin myöhemmin.
    source = Track("source.wav", "b", [Span(0.0, 4.0, 1.0)])

    out = aligned(target, source, np.arange(4 * RATE, dtype=np.float64), RATE, 4 * RATE)

    # Aikajanan hetki 0 on lähdetiedoston hetki 1 s.
    assert out[0] == pytest.approx(float(RATE))
    assert out[RATE] == pytest.approx(float(2 * RATE))


def test_a_partner_that_is_never_present_aligns_to_silence():
    """Nolla on oikea vastaus, ja se on eri asia kuin virhe."""
    target = Track("t.wav", "a", [Span(0.0, 4.0)])
    elsewhere = Track("s.wav", "b", [Span(100.0, 104.0)])

    out = aligned(target, elsewhere, np.ones(4 * RATE), RATE, 4 * RATE)

    assert not out.any()
