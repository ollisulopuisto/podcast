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
