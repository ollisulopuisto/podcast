"""Mielivaltainen häivytyskäyrä Hindenburgin `<Fade>`-luiskiksi.

Hindenburgin luiska on raised-cosine tasolle (``nhsx.mix._share``, mitattu).
Käyttäjän omat häivytykset ovat pitkiä, loivenevia nousuja — eri muoto.
Käyrä pilkotaan lyhyiksi luiskiksi, ja tarkistus tehdään lukemalla tulos
takaisin samalla koodilla jolla automixer sen soittaa.
"""

from __future__ import annotations

import math
from itertools import pairwise

import numpy as np
from lxml import etree

from nhsx import fades, read
from nhsx.mix import level_at, plan

LENGTH = 20.0


def _curve(t: float) -> float:
    """Käyttäjän kaltainen käyrä, dB: nousu hiljaisuudesta, tasanne, lasku.

    Muoto mitattu vst s13e03:n MID/END-pohjista: −68 dB:stä −8 dB:iin
    noin 8,6 sekunnissa, alussa nopeasti (−8 dB / 0,5 s) ja loivenevasti.
    """
    if t < 9.0:
        return -8.0 - 60.0 * math.exp(-t / 1.6)
    if t < 13.0:
        return -8.0
    return max(-80.0, -8.0 - 0.6 * (t - 13.0) ** 3)


def _points(func, step=0.05, length=LENGTH):
    return [(i * step, func(i * step)) for i in range(int(length / step) + 1)]


def _read_back(tmp_path, segments, length=LENGTH):
    """Kirjoittaa luiskat alueeseen ja lukee ne ``plan``illa kuten automixer."""
    (tmp_path / "m.wav").write_bytes(b"")
    path = tmp_path / "s.nhsx"
    path.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<Session>
  <AudioPool Path="" Location="{tmp_path}"><File Id="1" Name="m.wav"/></AudioPool>
  <Tracks><Track Name="musa">
    <Region Ref="1" Start="05.000" Length="{length:.3f}" Offset="00.000"/>
  </Track></Tracks>
</Session>""", encoding="utf-8")
    tree = etree.parse(str(path))
    region = next(tree.getroot().iter("Region"))
    fades.write(region, segments)
    tree.write(str(path), encoding="UTF-8", xml_declaration=True)
    (clip,) = plan(read(path)).clips
    return clip.ramps


def _db(linear: float) -> float:
    return 20.0 * math.log10(max(linear, 1e-12))


def test_curve_round_trips_within_tolerance(tmp_path):
    points = _points(_curve)
    segments = fades.segments(points)
    ramps = _read_back(tmp_path, segments)
    errors = []
    for t, want in _points(_curve, step=0.01):
        if t < fades.FIRST_RAMP_S:
            continue
        got = _db(level_at(ramps, t))
        if want >= fades.AUDIBLE_DB:
            errors.append(abs(got - want))
        else:
            # Kuulumattoman alla riittää että pysytään kuulumattomana.
            assert got < fades.AUDIBLE_DB + fades.TOLERANCE_DB, (t, got, want)
    assert max(errors) <= fades.TOLERANCE_DB


def test_flat_curve_needs_one_ramp():
    segments = fades.segments(_points(lambda t: -12.0))
    assert len(segments) == 1
    assert segments[0].start == 0.0
    assert segments[0].gain_db == -12.0


def test_hold_writes_no_ramp_and_economy_is_bounded():
    segments = fades.segments(_points(_curve))
    gains = [s.gain_db for s in segments]
    assert all(a != b for a, b in pairwise(gains))
    # 20 s käyrä: kymmeniä luiskia, ei satoja.
    assert len(segments) < 60


def test_ramps_follow_each_other_inside_the_region():
    segments = fades.segments(_points(_curve))
    for a, b in pairwise(segments):
        assert a.start + a.length <= b.start + 1e-9
    assert segments[-1].start + segments[-1].length <= LENGTH + 1e-9


def test_written_attributes_are_hindenburg_shaped(tmp_path):
    segments = fades.segments(_points(_curve))
    region = etree.fromstring('<Region Ref="1" Length="20.000"><Fade Length="1"/></Region>')
    fades.write(region, segments)
    children = region.findall("Fade")
    # Vanhat luiskat korvataan, ei lisätä perään.
    assert len(children) == len(segments)
    for child in children:
        assert set(child.attrib) <= {"Start", "Length", "Gain"}
        for name in ("Start", "Length"):
            if name in child.attrib:
                assert len(child.get(name).split(".")[1]) == 3


def test_silence_is_written_as_a_number():
    segments = fades.segments(_points(lambda t: float("-inf")))
    assert all(np.isfinite(s.gain_db) for s in segments)
    assert segments[0].gain_db == fades.SILENCE_DB


def test_silence_after_a_fall_arrives_promptly(tmp_path):
    """vst s13e03 INTRO: lasku päättyi −42,6 dB:iin, ja loput 71,75 s
    hiljaisuudesta kirjoitettiin yhdeksi raised-cosine-luiskaksi −90:een.
    Musiikki soi −43…−52 dB:ssä koko keskustelun alla. Kuulumattoman rajan
    alla «riittää että pysyy alhaalla» ei riitä, kun alhaalla on minuutti."""

    def fall_then_silence(t):
        if t < 10.0:
            return 0.0
        if t < 13.0:
            return -50.0 * (t - 10.0) / 3.0
        return float("-inf")

    length = 80.0
    segments = fades.segments(_points(fall_then_silence, length=length))
    ramps = _read_back(tmp_path, segments, length=length)
    for t in (14.0, 20.0, 40.0, 79.0):
        assert _db(level_at(ramps, t)) <= -80.0, t


def test_a_bed_starting_below_unity_does_not_click(tmp_path):
    """Alueen taso on 0 dB ensimmäiseen luiskaan asti, joten ensimmäiset
    10 ms soivat lähes täysillä. vst s13e03 v2: END-pohjan alussa 10 ms
    purske −11 dBFS:ssä, käyttäjä näki ja kuuli sen. Häivytys hiljaisuudesta
    (alueen ``FadeIn``) peittää luiskan."""
    from nhsx.mix import envelope

    segments = fades.segments(_points(lambda t: -56.66))
    (tmp_path / "m.wav").write_bytes(b"")
    path = tmp_path / "s.nhsx"
    path.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<Session><AudioPool Path="" Location="{tmp_path}"><File Id="1" Name="m.wav"/></AudioPool>
<Tracks><Track Name="musa"><Region Ref="1" Length="20.000"/></Track></Tracks></Session>""",
                    encoding="utf-8")
    tree = etree.parse(str(path))
    fades.write(next(tree.getroot().iter("Region")), segments)
    tree.write(str(path), encoding="UTF-8", xml_declaration=True)
    (clip,) = plan(read(path)).clips
    rate = 48000
    env = envelope(clip.length, rate, clip.ramps, clip.fade_in, clip.fade_out)
    assert 20 * math.log10(float(np.max(env[: int(0.02 * rate)]))) <= -45.0


def _bed(t):
    if t < 2.0:
        return float("-inf")
    if t < 10.0:
        return -80.0 + 80.0 * (t - 2.0) / 8.0
    if t < 14.0:
        return 0.0
    return float("-inf") if t > 18.0 else -40.0 * (t - 14.0) / 4.0


def _rise_error(tmp_path, segments):
    ramps = _read_back(tmp_path, segments)
    worst = 0.0
    for k in range(200, 1000):
        want = _bed(k / 100)
        got = _db(level_at(ramps, k / 100))
        if want >= fades.AUDIBLE_DB or got >= fades.AUDIBLE_DB:
            worst = max(worst, abs(got - want))
    return worst


def test_a_rise_is_two_long_ramps_and_a_fall_is_one(tmp_path):
    """vst s13e03: käyttäjä kuuli INTRO-pohjan nousun sätkivänä. 21 lyhyttä
    raised-cosine-luiskaa pysäyttää vahvistuksen muutosnopeuden jokaisessa
    liitoksessa (mitattu: nousu 11,7 dB / 1,9 s, 17 % ajasta lähes
    nollanopeudella, 2,5 Hz). Tasanne ei tarvitse luiskaa. Lasku on yksi
    luiska. Nousu on kaksi: käyttäjän nousu on suora desibeleinä (≈8 dB/s),
    yksi amplitudiluiska poikkeaa siitä jopa 13,7 dB, ja käyttäjä kuuli sen
    huonompana. Kaksi pitkää luiskaa liittyy vain kerran."""
    segments = fades.long_segments(_points(_bed))
    # alun 10 ms, nousu 2 luiskaa, lasku
    assert len(segments) == 4, segments
    rise = segments[1:3]
    assert all(r.length >= 1.9 for r in rise), rise
    ramps = _read_back(tmp_path, segments)
    levels = [level_at(ramps, t / 100) for t in range(2000)]
    end = int((rise[1].start + rise[1].length) * 100)
    # Nousu ei laske missään.
    assert all(b >= a - 1e-12 for a, b in pairwise(levels[2:end]))


def test_two_ramp_rise_follows_the_db_straight_curve_closer(tmp_path):
    two = _rise_error(tmp_path, fades.long_segments(_points(_bed)))
    # Yksi luiska: 13,7 dB (mitattu). Kaksi: selvästi alle.
    assert two < 8.0, two


def test_long_ramp_stays_inaudible_where_the_curve_is_silent(tmp_path):
    segments = fades.long_segments(_points(lambda t: -90.0 if t < 3.0 else -6.0))
    ramps = _read_back(tmp_path, segments)
    assert _db(level_at(ramps, 1.0)) < fades.AUDIBLE_DB
    assert abs(_db(level_at(ramps, 19.0)) - -6.0) < 0.01
