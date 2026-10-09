"""Musiikkipohjan käyrä puheen mukaan: toistaako se käyttäjän käsityön.

Vertailukohta on vst s13e03, jonka kolme pohjaa käyttäjä häivytti korvalla.
Käyrät mitattiin häivytetyn ja häivyttämättömän tiedoston suhteena 0,1 s
ikkunoissa (local-hburg, 2026-10-05). Puheen rajat ovat samasta
mittauksesta, kaikki raidat, alle 1,5 s tauot umpeen.

Yksi jakso, kolme pohjaa: nämä ovat lähtöarvoja, eivät sääntöä.
"""

from __future__ import annotations

from itertools import pairwise

from nhsx import musicbed

# Aikajanan sekunteja. Alue, puhe pohjan ympärillä, ja käyttäjän käyrän
# tunnuspisteet: tasanteen alku, tasanteen loppu, ja missä käyrä on 36 dB
# tasanteen alla (kuulumaton puheen alla).
INTRO = {
    "region": (8.887, 8.887 + 102.851),
    "speech": [(0.0, 23.00), (33.28, 60.0)],
    "plateau": 23.89, "drop": 32.89, "silent": 39.8,
}
MID = {
    "region": (2256.059, 2280.059),
    "speech": [(2200.0, 2272.22), (2280.58, 2300.0)],
    "plateau": 2273.56, "fall": 2277.96, "silent": 2279.66,
}
END = {
    "region": (2810.824, 2828.074),
    "speech": [(2780.0, 2817.14)],
    "plateau": 2819.32, "fall": 2823.92, "silent": 2827.12,
}


def _at(bed, curve, when):
    """Käyrän arvo aikajanan hetkellä, dB tasanteeseen nähden."""
    start = bed["region"][0]
    best = min(curve, key=lambda p: abs(p[0] - (when - start)))
    return best[1]


def _first(bed, curve, test, after=None):
    start = bed["region"][0]
    for t, db in curve:
        if (after is None or t + start >= after) and test(db):
            return t + start
    return None


def _curve(bed, cold_open=False):
    return musicbed.curve(*bed["region"], bed["speech"], cold_open=cold_open)


def test_end_bed_rises_holds_and_falls_like_the_users():
    curve = _curve(END)
    plateau = _first(END, curve, lambda db: db >= -0.5)
    assert abs(plateau - END["plateau"]) <= 1.0
    fall = _first(END, curve, lambda db: db < -1.0, after=plateau)
    assert abs(fall - END["fall"]) <= 0.5
    silent = _first(END, curve, lambda db: db <= -36.0, after=fall)
    assert abs(silent - END["silent"]) <= 0.5


def test_mid_bed_fits_its_fall_before_the_next_speaker():
    curve = _curve(MID)
    plateau = _first(MID, curve, lambda db: db >= -0.5)
    assert abs(plateau - MID["plateau"]) <= 1.0
    fall = _first(MID, curve, lambda db: db < -1.0, after=plateau)
    assert abs(fall - MID["fall"]) <= 0.5
    silent = _first(MID, curve, lambda db: db <= -30.0, after=fall)
    assert silent < MID["speech"][1][0]
    assert abs(silent - MID["silent"]) <= 0.5


def test_intro_holds_under_the_cold_open_then_dips_under_the_host():
    curve = _curve(INTRO, cold_open=True)
    # Kylmän alun alla pohja soi, ei vaikene: käyttäjällä noin −22 dB
    # tasanteen −10 alla, eli −12 (INTRO t 0,6–13 s).
    assert abs(_at(INTRO, curve, 12.0) - -12.0) <= 1.0
    plateau = _first(INTRO, curve, lambda db: db >= -0.5)
    assert abs(plateau - INTRO["plateau"]) <= 1.0
    drop = _first(INTRO, curve, lambda db: db < -1.0, after=plateau)
    assert abs(drop - INTRO["drop"]) <= 0.3
    # Juontajan alla hyllyllä, sitten pois.
    # Mitattu −19,3 tasanteen −10,0 alla (INTRO t 25,7–28,0).
    assert abs(_at(INTRO, curve, 36.0) - -9.3) <= 1.0
    silent = _first(INTRO, curve, lambda db: db <= -36.0, after=drop)
    assert abs(silent - INTRO["silent"]) <= 1.0


def test_intro_climbs_long_and_gently_like_the_ableton_bed():
    """Abletonilla tehty pohja ei pumppaa, NHSX-pohjan nousu pumppaa (sokkotesti
    vst s13e03: A_ableton_bed ja USER hyviä, kaikki automixer-nousut huonoja).
    Abletonin nousu alkaa noin 8 s ennen tasannetta: +3,6 dB 8 s:ssa, sitten
    +8 dB 2 s:ssa. Vanha nousi 12 dB 1,65 s:ssa."""
    curve = _curve(INTRO, cold_open=True)
    plateau = _first(INTRO, curve, lambda db: db >= -0.5)
    start = INTRO["region"][0]
    slopes = [
        (b[1] - a[1]) / (b[0] - a[0])
        for a, b in pairwise(curve)
        if plateau - 10.5 <= a[0] + start < plateau
    ]
    assert max(slopes) <= 4.5
    left = _at(INTRO, curve, plateau - 8.0)
    assert -12.0 <= left <= -8.0 and left > _at(INTRO, curve, plateau - 10.0)
    assert _at(INTRO, curve, plateau - 2.0) <= -6.0


def test_without_cold_open_the_bed_starts_from_silence():
    curve = _curve(MID)
    assert curve[0][1] <= musicbed.SILENCE_DB


def test_bed_with_no_gap_in_the_speech_is_refused():
    bed = {"region": (10.0, 30.0), "speech": [(0.0, 60.0)]}
    assert musicbed.curve(*bed["region"], bed["speech"]) is None


def test_end_bed_is_written_as_a_rise_and_a_fall_only():
    """Käyttäjä: «yksi pitkä nousu». INTRO-pohjan 21 luiskaa sätkivät."""
    from nhsx import fades

    curve = _curve(END)
    segs = fades.long_segments([(t, db - 10.0) for t, db in curve])
    assert len(segs) <= 4, segs
