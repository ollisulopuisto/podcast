"""Aikajanan ja tiedostoajan muunnos ``mix.py``:ssä, vihamielisellä geometrialla.

`mix.py` muuntaa aikajanan ajan tiedoston ajaksi kahdeksassa kohdassa,
aina samalla kaavalla::

    base = placement.start - item.asset_start - placement.offset
    tiedostoaika = aikajana + base

Kaava on menossa ``speechmix``iin ``Track``in ``spans``eiksi, ja se on
tämän muuton kohta jossa hiljainen vääryys asuu: väärä etumerkki, unohtunut
toinen esiintymä tai `asset_start`in putoaminen tuottaa **kelvollisen
tiedoston, oikean mittaisen, väärässä kohdassa**. Mikään ei kaadu ja
vienti näyttää onnistuneelta.

Mitattu: **koko 290 testin sarja menee läpi kun `base`n etumerkki
käännetään**, ja menee läpi myös kun jokaisesta kappaleesta käytetään vain
ensimmäistä esiintymää. Syy on aineistossa: siinä geometria on
identiteetti — yksi esiintymä, `asset_start` nolla, aikajanan hetki sama
kuin tiedoston — ja silloin `base` on nolla, joka on sama kummin päin
tahansa.

Tässä on siis tarkoituksella hankala kappale — kaksi esiintymää eri
puolilla aikajanaa, `asset_start` kymmenen sekuntia, `base` eri merkkinen
kummassakin esiintymässä — ja odotetut luvut on laskettu käsin eikä
toteutuksesta. Muutosta ennen tarkistettiin että testi punaisee jokaisesta
kolmesta virheestä erikseen: `base`n etumerkin kääntö, `asset_start`in
pudotus ja vain ensimmäisen esiintymän käyttö.
"""

from fractions import Fraction

import numpy as np
import pytest

from autoraffkat.audio import mix
from autoraffkat.model import HOP, MediaItem, Placement

RATE = 48000

# Tiedoston t=0 on lähteen hetki 10 s.
#
#   esiintymä 1: aikajana 5–9 s   <-> tiedosto 3–7 s     base = -2
#   esiintymä 2: aikajana 20–26 s <-> tiedosto 21–27 s   base = +1
#
# Eri merkkinen kummassakin, ja tiedostovälit erillään toisistaan, jotta
# pudonnut tai kahdennettu esiintymä näkyy eikä peity toiseen.
ASSET_START = Fraction(10)
SPAN_A = (Fraction(5), Fraction(13), Fraction(4))   # offset, start, duration
SPAN_B = (Fraction(20), Fraction(31), Fraction(6))


@pytest.fixture
def item():
    return MediaItem(
        key="mic",
        name="MIC",
        path="/ei/lueta.wav",
        src="",
        asset_start=ASSET_START,
        has_audio=True,
        placements=[
            Placement(offset=o, start=s, duration=d) for o, s, d in (SPAN_A, SPAN_B)
        ],
    )


def _grid(*ranges, seconds=40.0):
    """Ruudukko jossa annetut aikajanan välit ovat tosia."""
    closed = np.zeros(int(seconds / HOP), dtype=bool)
    for low, high in ranges:
        closed[int(low / HOP) : int(high / HOP)] = True
    return closed


def test_geometry_is_the_two_spans_and_their_bases(item):
    """``_geometry`` on jo ``Track.spans``, muussa järjestyksessä."""
    frames, spans = mix._geometry(item, 12345)
    assert frames == 12345
    assert spans == ((5.0, 9.0, -2.0), (20.0, 26.0, 1.0))


def test_closed_ranges_uses_both_placements(item):
    """Kiinni molemmilla puolilla aikajanaa, ulos molempien tiedostokohdat."""
    closed = _grid((6.0, 8.0), (21.0, 23.0))
    ranges = mix.closed_ranges(item, closed, 0.0, RATE)

    assert ranges == [(4 * RATE, 6 * RATE), (22 * RATE, 24 * RATE)]


def test_closed_ranges_clips_to_the_placement(item):
    """Esiintymien väliin osuvasta ajasta ei ole tietoa, eikä sitä vaimenneta."""
    closed = _grid((0.0, 40.0))
    ranges = mix.closed_ranges(item, closed, 0.0, RATE)

    assert ranges == [(3 * RATE, 7 * RATE), (21 * RATE, 27 * RATE)]


def test_closed_ranges_follows_the_grid_start(item):
    """``program_start`` siirtää ruudukkoa, ei tiedostoa.

    Ruudukko alkaa aikajanan hetkestä ``program_start``, joten sen solu 0
    ei ole aikajanan nolla. Tämän unohtaminen siirtää vaimennuksen
    ruudukon alun verran ja on juuri niin näkymätön kuin miltä kuulostaa.
    """
    closed = _grid((1.0, 3.0), seconds=40.0)  # ruudukon alusta 1–3 s
    ranges = mix.closed_ranges(item, closed, 5.0, RATE)  # = aikajana 6–8 s

    assert ranges == [(4 * RATE, 6 * RATE)]


def test_speech_blocks_marks_only_this_speakers_own_blocks(item):
    """Lohkot ovat tiedoston aikaa, maski aikajanan."""
    block = 4800  # 0,1 s
    count = 300  # 30 s tiedostoa
    mask = _grid((6.0, 8.0))

    out = mix.speech_blocks(item, mask, 0.0, RATE, block, count)

    # Aikajana 6–8 s on tiedoston 4–6 s, eli lohkot 40–59.
    assert np.flatnonzero(out).tolist() == list(range(40, 60))


def test_speech_blocks_reaches_the_second_placement(item):
    """Toinen esiintymä on kaukana aikajanalla ja lähellä tiedostossa."""
    block = 4800
    count = 300
    mask = _grid((21.0, 23.0))

    out = mix.speech_blocks(item, mask, 0.0, RATE, block, count)

    # Aikajana 21–23 s on tiedoston 22–24 s, eli lohkot 220–239.
    assert np.flatnonzero(out).tolist() == list(range(220, 240))


def test_the_duck_envelope_lands_on_the_right_samples(item):
    """Vaimennuskäyrä on aikajanan aikaa, kerroin tiedoston näytteitä.

    Käyrä: nolla 5 s:ssä, −6 dB 6–8 s, takaisin nollaan 9 s:ssä — aikajanaa.
    Ensimmäisessä esiintymässä se on tiedoston 3–7 s.
    """
    job = {"speaker": "A", "item": item}
    points = [(5.0, 0.0), (6.0, -6.0), (8.0, -6.0), (9.0, 0.0)]
    gain = mix._envelope_block(job, {"A": points}, 0, 8 * RATE, RATE)

    at = lambda seconds: float(gain[int(seconds * RATE)])  # noqa: E731

    assert at(2.5) == pytest.approx(1.0)  # ennen esiintymää: koskematon
    assert at(4.0) == pytest.approx(10.0 ** (-6.0 / 20.0), rel=1e-4)  # täysi
    assert at(6.5) == pytest.approx(10.0 ** (-3.0 / 20.0), rel=1e-3)  # nousussa
    assert at(7.5) == pytest.approx(1.0)  # esiintymän jälkeen: koskematon


def test_the_duck_envelope_without_a_curve_is_unity(item):
    """Ilman käyrää tiedosto menee summaan sellaisenaan."""
    job = {"speaker": "A", "item": item}
    assert mix._envelope_block(job, {}, 0, 8 * RATE, RATE).tolist() == [1.0]
