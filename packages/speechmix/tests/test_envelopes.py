"""Vaimennus päätöksinä.

``duck_envelopes`` palauttaa käyrän, ei ääntä. Sama laskenta kelpaa sekä
Final Cutin keyframeiksi että näytteisiin poltettavaksi, ja juuri siksi se on
kirjastossa eikä kummassakaan isännässä.
"""

import numpy as np

from speechmix import envelopes


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


class _Placement:
    def __init__(self, offset, end, start):
        self.offset, self.end, self.start = offset, end, start
        self.duration = end - offset


class _Item:
    def __init__(self, placements, asset_start=0.0):
        self.placements, self.asset_start = placements, asset_start


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


def test_programme_time_becomes_file_time_per_placement():
    """Ruudukko on aikajanan aikaa, tiedosto omaansa."""
    closed = np.zeros(200, dtype=bool)
    closed[50:100] = True  # 1.0 s … 2.0 s ohjelma-ajassa
    item = _Item([_Placement(offset=0.0, end=10.0, start=5.0)], asset_start=0.0)
    ranges = envelopes.closed_ranges(item, closed, program_start=0.0, rate=48000)
    assert ranges == [(int(6.0 * 48000), int(7.0 * 48000))]


def test_a_span_outside_the_placement_is_not_touched():
    """Ruudukon ulkopuolelle jäävästä ei ole tietoa, eikä vienti käytä sitä."""
    closed = np.zeros(200, dtype=bool)
    closed[:20] = True
    item = _Item([_Placement(offset=50.0, end=60.0, start=0.0)])
    assert envelopes.closed_ranges(item, closed, program_start=0.0, rate=48000) == []
