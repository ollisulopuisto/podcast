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
    duck_min_gap = 1.0


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

    Nousu osuu aina hiljaisuuteen jossa mikään ei peitä sitä, joten se on
    aina hidas. Lasku on nopea vain kun se osuu peittävän puhujan aloitukseen
    ja jää sen alle; muuten se on yhtä hidas kuin nousu. Kumpikaan ei ala
    jakson ulkopuolelta.
    """
    from speechmix import masks

    grid, settings = _turn_taking(), _Settings()
    out = envelopes.duck_envelopes(grid, settings, 0.0)
    covering = masks.covering_masks(grid, settings)

    for name, mask in masks.duck_masks(grid, settings).items():
        if name not in out:
            continue
        expected = []
        for start, end, value in masks.runs(np.asarray(mask).astype(np.int8)):
            if not value:
                continue
            t0, t1 = start * envelopes.HOP, end * envelopes.HOP
            peitossa = envelopes._under_onset(covering.get(name), start)
            fall = settings.duck_fade if peitossa else settings.duck_release
            head = min(fall, (t1 - t0) / 2.0)
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


def _head_and_tail_silence(n=1500, first=200, last=1200):
    """Puhetta keskellä, hiljaisuutta molemmissa päissä."""
    on = np.zeros(n, dtype=bool)
    on[first:last] = True
    return on


def test_program_fades_land_in_the_silence():
    """Häivytys alkaa ohjelman alusta ja on ohi ennen ensimmäistä sanaa."""
    grid = _Grid(_Lane("a", _head_and_tail_silence()))
    end = 1500 * envelopes.HOP
    out = envelopes.program_fades(grid, 0.0, end)

    points = out["a"]
    assert points[0] == (0.0, envelopes.FADE_FLOOR_DB)
    head_end = points[1][0]
    assert points[1][1] == 0.0
    # 200 askelta * 20 ms = 4,0 s ensimmäiseen sanaan; vartti jää väliin.
    assert head_end <= 200 * envelopes.HOP - envelopes.FADE_GUARD_SEC

    assert points[-1] == (end, envelopes.FADE_FLOOR_DB)
    tail_start = points[-2][0]
    assert points[-2][1] == 0.0
    assert tail_start >= 1200 * envelopes.HOP + envelopes.FADE_GUARD_SEC


def test_program_fades_do_not_step_on_speech():
    """Puhe heti alusta ja loppuun asti: häivytystä ei kirjoiteta.

    Häivytys saa koskea vain hiljaisuutta ja tilaääntä. Puheen päälle
    ajettuna se on virhe jota ei kuule vientiä kuuntelematta: tiedosto on
    kelvollinen, oikean mittainen ja alkaa vaimeana.
    """
    grid = _Grid(_Lane("a", np.ones(1500, dtype=bool)))
    assert envelopes.program_fades(grid, 0.0, 1500 * envelopes.HOP) == {}


def test_program_fades_keep_the_ducks():
    """Vaimennuskäyrä säilyy häivytysten välissä, aikajärjestyksessä."""
    grid = _Grid(_Lane("a", _head_and_tail_silence()),
                 _Lane("b", _head_and_tail_silence()))
    end = 1500 * envelopes.HOP
    ducks = {"a": [(10.0, 0.0), (10.25, -9.0), (12.0, -9.0), (12.25, 0.0)]}
    out = envelopes.program_fades(grid, 0.0, end, ducks)

    times = [t for t, _ in out["a"]]
    assert times == sorted(times)
    assert (10.25, -9.0) in out["a"]
    assert "b" in out, "häivytys kuuluu jokaiselle mikille, ei vain vaimennetuille"


def test_envelope_outside_the_curve_holds_its_edge():
    """Käyrän ulkopuolella reunan arvo, ei nolla.

    Vaimennuskäyrä palaa itse nollaan molemmissa päissään, joten sille tämä
    on sama asia. Häivytykselle ei: sen viimeinen piste on ohjelman lopussa
    ja alimmillaan, ja nollaksi tulkittuna vienti nostaisi äänen takaisin
    juuri siinä kohdassa jossa sen pitäisi olla poissa.
    """
    fade = [(0.0, -96.0), (1.0, 0.0)]
    assert envelopes.envelope_at(fade, -1.0) == -96.0
    assert envelopes.envelope_at([(0.0, 0.0), (1.0, -96.0)], 2.0) == -96.0
    duck = [(1.0, 0.0), (1.25, -9.0), (2.0, -9.0), (2.25, 0.0)]
    assert envelopes.envelope_at(duck, 0.0) == 0.0
    assert envelopes.envelope_at(duck, 9.0) == 0.0


def test_program_fades_ignore_the_blip_at_the_grid_edge():
    """Ruudukon reunan yksittäinen tosi solu ei ole ohjelman ensimmäinen sana.

    Tunnistus antaa vajaassa ensimmäisessä ja viimeisessä ikkunassa yhden
    solun tosia. Sellaisenaan luettuna puhe alkaa hetkellä nolla ja päättyy
    ohjelman loppuun, eikä häivytykselle jää tilaa kummassakaan päässä — eli
    vika ei näy virheenä vaan puuttuvana häivytyksenä.
    """
    on = _head_and_tail_silence()
    on[0] = True
    on[-1] = True
    out = envelopes.program_fades(_Grid(_Lane("a", on)), 0.0, 1500 * envelopes.HOP)
    assert out, "reunan välähdys esti häivytyksen"
    assert out["a"][0] == (0.0, envelopes.FADE_FLOOR_DB)
    assert out["a"][-1] == (1500 * envelopes.HOP, envelopes.FADE_FLOOR_DB)


def _first_fall(points):
    """Ensimmäisen laskun kesto sekunteina."""
    from itertools import pairwise

    for (t0, v0), (t1, v1) in pairwise(points):
        if v1 < v0 - 0.5:
            return round(t1 - t0, 3)
    raise AssertionError(f"ei laskua: {points[:6]}")


def test_a_fall_under_the_other_speakers_onset_is_fast():
    """Peitossa oleva lasku saa olla nopea: toisen aloitus peittää sen."""
    n = 1200
    a_on = np.zeros(n, dtype=bool)
    b_on = np.zeros(n, dtype=bool)
    a_on[:300] = True
    b_on[800:1100] = True          # alkaa vasta kun a on jo vaiennut
    grid = _Grid(_Lane("a", a_on, np.full(n, -18.0)),
                 _Lane("b", b_on, np.full(n, -18.0)))
    out = envelopes.duck_envelopes(grid, _Settings(), 0.0)
    assert _first_fall(out["a"]) == _Settings.duck_fade


def test_an_exposed_fall_is_as_slow_as_the_rise():
    """Kun peittävä ääni on jo käynnissä, laskua ei peitä mikään.

    Nopea lasku on perusteltu vain toisen puhujan aloituksen alla — siinä
    aloitus peittää sen. Jos vaimennus alkaa siksi että **tämä** puhuja
    vaikeni kesken toisen puheen, aloitusta ei ole, ja sama nopea lasku on
    kuultava tasohyppy keskellä puhetta.
    """
    n = 1200
    a_on = np.zeros(n, dtype=bool)
    b_on = np.zeros(n, dtype=bool)
    a_on[:300] = True
    b_on[100:1100] = True          # käynnissä jo pitkään kun a vaikenee
    grid = _Grid(_Lane("a", a_on, np.full(n, -18.0)),
                 _Lane("b", b_on, np.full(n, -18.0)))
    out = envelopes.duck_envelopes(grid, _Settings(), 0.0)
    assert _first_fall(out["a"]) == _Settings.duck_release
