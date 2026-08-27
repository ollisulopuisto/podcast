"""Vaimennus päätöksinä.

``duck_envelopes`` palauttaa käyrän, ei ääntä. Sama laskenta kelpaa sekä
Final Cutin keyframeiksi että näytteisiin poltettavaksi, ja juuri siksi se on
kirjastossa eikä kummassakaan isännässä.
"""

import numpy as np
import pytest

from speechmix import envelopes
from speechmix.timeline import Span, Track


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


def test_the_curve_is_programme_time_not_grid_time():
    """Ruudukon solu 0 ei ole ohjelman nolla vaan ``program_start``.

    Mitattu: ``program_start``in pudottaminen kokonaan meni läpi koko
    sarjasta. Se ei kaada mitään — se siirtää jokaisen vaimennuksen
    ruudukon alun verran, ja aineistossa ruudukko alkaa nollasta, joten
    siirto on siellä nolla. Oikeassa jaksossa se ei ole.
    """
    grid, settings = _turn_taking(), _Settings()
    at_zero = envelopes.duck_envelopes(grid, settings, 0.0)
    later = envelopes.duck_envelopes(grid, settings, 100.0)

    assert set(at_zero) == set(later) and at_zero
    for name, points in at_zero.items():
        assert [(t + 100.0, db) for t, db in points] == [
            (pytest.approx(t), db) for t, db in later[name]
        ]


def test_the_curve_matches_the_mask_point_for_point():
    """Neljä pistettä jaksoa kohden, ja liu'ut jakson **sisällä**.

    Lasku osuu toisen puhujan aloitukseen ja jää sen alle; nousu osuu
    hiljaisuuteen jossa mikään ei peitä sitä. Siksi ne ovat eri mittaiset
    ja siksi kumpikaan ei ala jakson ulkopuolelta.
    """
    from speechmix import masks

    grid, settings = _turn_taking(), _Settings()
    out = envelopes.duck_envelopes(grid, settings, 0.0)

    for name, mask in masks.duck_masks(grid, settings).items():
        if name not in out:
            continue
        expected = []
        for start, end, value in masks.runs(np.asarray(mask).astype(np.int8)):
            if not value:
                continue
            t0, t1 = start * envelopes.HOP, end * envelopes.HOP
            head = min(settings.duck_fade, (t1 - t0) / 2.0)
            tail = min(settings.duck_release, (t1 - t0) - head)
            expected += [
                (pytest.approx(t0), 0.0),
                (pytest.approx(t0 + head), settings.duck_db),
                (pytest.approx(t1 - tail), settings.duck_db),
                (pytest.approx(t1), 0.0),
            ]
        assert out[name] == expected


def test_the_value_between_points_is_linear_and_zero_outside():
    points = [(10.0, 0.0), (10.25, -9.0), (12.0, -9.0), (12.4, 0.0)]
    assert envelopes.envelope_at(points, 9.0) == 0.0
    assert envelopes.envelope_at(points, 13.0) == 0.0
    assert envelopes.envelope_at(points, 11.0) == -9.0
    assert envelopes.envelope_at(points, 10.125) == -4.5
    assert envelopes.envelope_at([], 1.0) == 0.0


def test_programme_time_becomes_file_time_per_span():
    """Ruudukko on aikajanan aikaa, tiedosto omaansa."""
    closed = np.zeros(200, dtype=bool)
    closed[50:100] = True  # 1.0 s … 2.0 s ohjelma-ajassa
    track = Track("mic.wav", "a", [Span(0.0, 10.0, 5.0)])
    ranges = envelopes.closed_ranges(track, closed, program_start=0.0, rate=48000)
    assert ranges == [(int(6.0 * 48000), int(7.0 * 48000))]


def test_a_span_outside_the_placement_is_not_touched():
    """Ruudukon ulkopuolelle jäävästä ei ole tietoa, eikä vienti käytä sitä."""
    closed = np.zeros(200, dtype=bool)
    closed[:20] = True
    track = Track("mic.wav", "a", [Span(50.0, 60.0, 0.0)])
    assert envelopes.closed_ranges(track, closed, program_start=0.0, rate=48000) == []


# ------------------------------------------------------------------ geometria
#
# Vihamielinen geometria: kaksi paikkaa eri puolilla aikajanaa ja ``base``
# eri merkkinen kummassakin. Identtinen geometria — yksi paikka,
# ``file_offset`` sama kuin ``programme_start`` — testaa vain nollaa, ja
# nolla on sama kummin päin tahansa. Mitattuna kaksi kolmesta
# muunnosvirheestä meni läpi koko sarjasta ennen näitä.
#
#   paikka 1: ohjelma 5–9 s   <-> tiedosto 3–7 s     base = -2
#   paikka 2: ohjelma 20–26 s <-> tiedosto 21–27 s   base = +1
RATE = 48000
AWKWARD = [Span(5.0, 9.0, 3.0), Span(20.0, 26.0, 21.0)]


@pytest.fixture
def mic():
    return Track("mic.wav", "A", list(AWKWARD))


def _grid_mask(*ranges, seconds=40.0):
    out = np.zeros(int(seconds / envelopes.HOP), dtype=bool)
    for low, high in ranges:
        out[int(low / envelopes.HOP) : int(high / envelopes.HOP)] = True
    return out


def test_closed_ranges_uses_every_span(mic):
    closed = _grid_mask((6.0, 8.0), (21.0, 23.0))
    assert envelopes.closed_ranges(mic, closed, 0.0, RATE) == [
        (4 * RATE, 6 * RATE),
        (22 * RATE, 24 * RATE),
    ]


def test_closed_ranges_clip_to_the_spans(mic):
    """Paikkojen väliin osuvasta ajasta ei ole tietoa, eikä sitä kosketa."""
    assert envelopes.closed_ranges(mic, _grid_mask((0.0, 40.0)), 0.0, RATE) == [
        (3 * RATE, 7 * RATE),
        (21 * RATE, 27 * RATE),
    ]


def test_closed_ranges_follow_the_grid_start(mic):
    """Ruudukon solu 0 ei ole ohjelman nolla vaan ``program_start``."""
    closed = _grid_mask((1.0, 3.0))
    assert envelopes.closed_ranges(mic, closed, 5.0, RATE) == [(4 * RATE, 6 * RATE)]


def test_speech_blocks_are_file_time(mic):
    out = envelopes.speech_blocks(mic, _grid_mask((6.0, 8.0)), 0.0, RATE, 4800, 300)
    assert np.flatnonzero(out).tolist() == list(range(40, 60))


def test_speech_blocks_reach_the_second_span(mic):
    out = envelopes.speech_blocks(mic, _grid_mask((21.0, 23.0)), 0.0, RATE, 4800, 300)
    assert np.flatnonzero(out).tolist() == list(range(220, 240))


def test_duck_gain_lands_on_the_right_samples(mic):
    """Käyrä on aikajanan aikaa, kerroin tiedoston näytteitä."""
    points = [(5.0, 0.0), (6.0, -6.0), (8.0, -6.0), (9.0, 0.0)]
    gain = envelopes.duck_gain(mic, points, 0, 8 * RATE, RATE)

    def at(seconds):
        return float(gain[int(seconds * RATE)])

    assert at(2.5) == pytest.approx(1.0)  # ennen paikkaa: koskematon
    assert at(4.0) == pytest.approx(10.0 ** (-6.0 / 20.0), rel=1e-4)
    assert at(6.5) == pytest.approx(10.0 ** (-3.0 / 20.0), rel=1e-3)
    assert at(7.5) == pytest.approx(1.0)  # paikan jälkeen: koskematon


def test_duck_gain_without_a_curve_is_unity(mic):
    """Ilman käyrää tiedosto menee summaan sellaisenaan."""
    assert envelopes.duck_gain(mic, [], 0, 8 * RATE, RATE).tolist() == [1.0]


def test_geometry_is_the_spans_and_the_frame_count(mic):
    """Summa lasketaan näyte näytteeltä, joten sijainnin pitää täsmätä."""
    assert envelopes.geometry(mic, 12345) == (
        12345,
        ((5.0, 9.0, 3.0), (20.0, 26.0, 21.0)),
    )
    moved = Track("mic.wav", "A", [Span(5.0, 9.0, 4.0), AWKWARD[1]])
    assert envelopes.geometry(moved, 12345) != envelopes.geometry(mic, 12345)
