"""Maskit ruudukolla.

Nämä olivat kahdessa paikassa sovelluksissa ennen kuin ne siirtyivät tänne.
Testit ovat kirjastossa, koska koodikin on: se on koko siirron pointti.
"""

import numpy as np
from speechmix import masks


class _Lane:
    def __init__(self, name, on, level=None):
        self.name = name
        self.on = np.asarray(on, dtype=bool)
        self.level = np.full(self.on.shape, -20.0) if level is None else np.asarray(level)


class _Grid:
    def __init__(self, *lanes):
        self.speakers = list(lanes)


class _Settings:
    duck = True
    duck_dominance_db = 6.0
    duck_lookahead = 0.15
    duck_hold = 0.40
    duck_min_open = 0.20
    duck_release = 0.40
    duck_min_closed = 0.60


def test_runs_finds_the_spans():
    assert masks.runs(np.array([0, 0, 1, 1, 1, 0], dtype=np.int8)) == [
        (0, 2, 0),
        (2, 5, 1),
        (5, 6, 0),
    ]
    assert masks.runs(np.array([], dtype=np.int8)) == []


def test_a_cough_does_not_open_the_gate():
    """``min_open`` pudottaa liian lyhyet jaksot."""
    on = np.zeros(200, dtype=bool)
    on[50:52] = True  # 40 ms
    on[100:160] = True  # 1.2 s
    opened = masks.open_windows(on, lookahead=0.0, hold=0.0, min_open=0.20)
    assert not opened[50:52].any()
    assert opened[100:160].all()


def test_lookahead_opens_before_the_word_and_hold_keeps_it_open():
    on = np.zeros(200, dtype=bool)
    on[100:150] = True
    opened = masks.open_windows(on, lookahead=0.20, hold=0.20, min_open=0.0)
    assert opened[90:100].all(), "ennakko ei avannut porttia ennen puhetta"
    assert opened[150:160].all(), "pito ei jättänyt lauseen häntää mukaan"


def test_nobody_is_ducked_when_nobody_is_speaking():
    """Hiljaisuuteen laskeva portti kuuluu aina, koska mikään ei peitä sitä."""
    silence = np.zeros(300, dtype=bool)
    grid = _Grid(_Lane("a", silence), _Lane("b", silence))
    assert masks.duck_masks(grid, _Settings()) == {} or all(
        not m.any() for m in masks.duck_masks(grid, _Settings()).values()
    )


def test_the_loudest_microphone_stays_open():
    """Kaksi mikkiä samassa huoneessa kuulevat molemmat puhujat."""
    n = 400
    a_on = np.zeros(n, dtype=bool)
    a_on[100:300] = True
    grid = _Grid(
        _Lane("a", a_on, np.full(n, -18.0)),
        _Lane("a_leak", a_on, np.full(n, -34.0)),  # vuoto, 16 dB hiljempaa
    )
    out = masks.duck_masks(grid, _Settings())
    assert not out["a"][150:250].any(), "kovin mikki vaimennettiin"
    assert out["a_leak"][150:250].any(), "vuotava mikki jäi auki"


def test_solo_masks_are_where_only_one_speaks():
    n = 300
    a = np.zeros(n, dtype=bool)
    b = np.zeros(n, dtype=bool)
    a[:200] = True
    b[100:] = True
    out = masks.solo_masks(_Grid(_Lane("a", a), _Lane("b", b)))
    assert out["a"][:100].all()
    assert not out["a"][100:200].any(), "päällekkäinen puhe ei ole soloa"
    assert out["b"][200:].all()
