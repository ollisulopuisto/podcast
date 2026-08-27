"""Vaimennus päätöksinä.

``duck_envelopes`` palauttaa käyrän, ei ääntä. Sama laskenta kelpaa sekä
Final Cutin keyframeiksi että näytteisiin poltettavaksi, ja juuri siksi se on
kirjastossa eikä kummassakaan isännässä.
"""

import numpy as np
import pytest

from speechmix import envelopes, session


class _Lane:
    def __init__(self, name, on, level=None):
        self.name = name
        self.on = np.asarray(on, dtype=bool)
        self.level = np.full(self.on.shape, -20.0) if level is None else level


class _Grid:
    def __init__(self, *lanes):
        self.speakers = list(lanes)


class _Settings:
    duck = True
    duck_db = -9.0
    duck_fade = 0.25
    duck_release = 0.40
    duck_dominance_db = 6.0
    duck_lookahead = 0.15
    duck_hold = 0.40
    duck_min_open = 0.20
    duck_min_closed = 0.60


def _turn_taking(n=800):
    a = np.zeros(n, dtype=bool)
    b = np.zeros(n, dtype=bool)
    a[:n // 2] = True
    b[n // 2:] = True
    return _Grid(_Lane("a", a), _Lane("b", b))


def test_ducking_off_means_no_points():
    class Off(_Settings):
        duck = False

    assert envelopes.duck_envelopes(_turn_taking(), Off(), 0.0) == {}


def test_the_curve_goes_down_and_comes_back_to_unity():
    """Vaimennus on paikallinen tapahtuma, ei tila."""
    out = envelopes.duck_envelopes(_turn_taking(), _Settings(), 0.0)
    assert out, "vuorottelevilla puhujilla pitäisi syntyä vaimennusta"
    for points in out.values():
        values = [db for _, db in points]
        assert min(values) == -9.0
        assert points[0][1] == 0.0 and points[-1][1] == 0.0
        times = [t for t, _ in points]
        assert times == sorted(times)


def test_the_value_between_points_is_linear_and_zero_outside():
    points = [(10.0, 0.0), (10.25, -9.0), (12.0, -9.0), (12.4, 0.0)]
    assert envelopes.envelope_at(points, 9.0) == 0.0
    assert envelopes.envelope_at(points, 13.0) == 0.0
    assert envelopes.envelope_at(points, 11.0) == -9.0
    assert envelopes.envelope_at(points, 10.125) == -4.5
    assert envelopes.envelope_at([], 1.0) == 0.0


def test_the_same_curve_can_be_burnt_into_samples():
    """Toinen sauma: sama päätös, eri emissio.

    autoraffkat kirjoittaa ``duck_envelopes``in pisteet Final Cutin
    keyframeiksi. automixerillä ei ole mitään mihin automaatio kirjoitettaisiin,
    joten se kertoo tällä — ja kummankin on saatava sama käyrä, tai vaimennus
    riippuisi siitä kumpi isäntä sen teki.

    Ruudukko ja käyrä ovat aikajanan aikaa, kerroin tiedoston. Muunnos on
    jakson sisällä lineaarinen, sama kaava kuin ``session.file_ranges``issa.
    """
    rate = 48000
    # Aikajanan hetki 10 on tiedoston hetki 0.
    track = session.whole_file("", start=10.0, duration=10.0)
    points = [(11.0, 0.0), (11.0, -9.0), (12.0, -9.0), (12.0, 0.0)]

    gain = envelopes.envelope_gain(track, points, 0, 3 * rate, rate)

    quiet = 10.0 ** (-9.0 / 20.0)
    # Tiedoston sekunnit 1–2 ovat aikajanan 11–12.
    assert gain[: rate - 1] == pytest.approx(1.0)
    assert gain[rate + 10 : 2 * rate - 10] == pytest.approx(quiet, abs=1e-6)
    assert gain[2 * rate + 1 :] == pytest.approx(1.0)


def test_without_a_curve_the_file_goes_in_untouched():
    """Puhuja jolle ei syntynyt vaimennusta menee summaan sellaisenaan."""
    track = session.whole_file("", start=0.0, duration=1.0)
    assert envelopes.envelope_gain(track, [], 0, 100, 48000).tolist() == [1.0]
    assert envelopes.envelope_gain(None, [(0.0, -9.0)], 0, 100, 48000).tolist() == [1.0]
