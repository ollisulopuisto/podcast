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
    duck_min_gap = 1.0


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


def test_close_gaps_is_the_dual_of_drop_short():
    """``drop_short`` poistaa lyhyet todet, ``close_gaps`` lyhyet epätodet."""
    mask = np.zeros(100, dtype=bool)
    mask[10:40] = True
    mask[45:80] = True          # viiden solun aukko, 0,10 s
    assert masks.close_gaps(mask, 0.2)[40:45].all()
    assert not masks.close_gaps(mask, 0.05)[40:45].any()
    # Reunat eivät ole aukkoja: käyrän ulkopuolta ei täytetä.
    assert not masks.close_gaps(mask, 1.0)[:10].any()
    assert not masks.close_gaps(mask, 1.0)[80:].any()


def test_a_plosive_does_not_reopen_the_ducked_microphone():
    """Vuoto joka hipaisee kynnystä avasi mikin kesken toisen lauseen.

    Kahden mikin nauhoituksessa vuoto on mediaanissa 12,8 dB hiljempaa, mutta
    plosiivit ja naurahdukset käyvät `duck_dominance_db`:n sisällä. Yksi
    sellainen antoi vuotavalle mikille `duck_min_open` + `duck_hold`
    -mittaisen aukon keskellä vaimennusta, eli täystasoinen vuoto palasi
    puoleksi sekunniksi toisen mikin omaa puhetta vasten: kampasuodatusta,
    joka kuuluu metallisena kaikuna.

    Hystereesi oli yksipuolinen. `duck_min_closed` pudottaa lyhyet
    vaimennukset, mutta lyhyitä *aukkoja* vaimennuksen sisällä ei poistanut
    mikään.
    """
    n = 600
    a_on = np.ones(n, dtype=bool)               # a puhuu koko ajan
    leak_level = np.full(n, -34.0)
    leak_level[300:310] = -18.0                 # 0,20 s plosiivia, tasoissa
    grid = _Grid(
        _Lane("a", a_on, np.full(n, -18.0)),
        _Lane("leak", a_on, leak_level),
    )
    out = masks.duck_masks(grid, _Settings())
    assert out["leak"][100:250].all(), "vaimennus ei alkanut lainkaan"
    assert out["leak"][300:310].all(), "plosiivi avasi mikin kesken vaimennuksen"


def test_the_duck_does_not_lift_for_a_breath_in_the_other_speaker():
    """Vaimennus nousee vain jos vaimennettu puhuja tosiaan puhuu.

    Aukko vaimennuksessa syntyy joko siitä että **tämä** puhuja avaa mikkinsä
    tai siitä että peittävä puhe loppui. Jälkimmäinen loppuu myös
    sisäänhengitykseen: mitattuna jaksolla peittävän puhujan taso käy
    -57…-62 dB:ssä puolen sekunnin ajan kesken lausetta, peittävä jakso
    katkeaa siihen, ja vaimennettu mikki nousee täyteen tasoon hengityksen
    ajaksi. Kukaan ei puhu, ja huone nousee kuuluviin.

    Ehto on sisällössä eikä kestossa: jos tämän puhujan portti ei aukea
    aukon aikana kertaakaan, aukolle ei ole syytä eikä sitä tehdä. Se
    selviää ilman kynnystä, joten se kestää myös jakson vaihtumisen.
    """
    n = 1200
    a_on = np.zeros(n, dtype=bool)          # a on vaimennettava, ei puhu
    b_on = np.ones(n, dtype=bool)           # b puhuu koko ajan...
    b_on[500:560] = False                   # ...paitsi 1,2 s hengitys
    grid = _Grid(_Lane("a", a_on, np.full(n, -60.0)),
                 _Lane("b", b_on, np.full(n, -18.0)))
    out = masks.duck_masks(grid, _Settings())
    assert out["a"][300:480].all(), "vaimennus ei alkanut"
    assert out["a"][500:560].all(), "hengitys nosti vaimennetun mikin"


def test_the_duck_still_lifts_when_the_speaker_actually_talks():
    """Sisältöehto ei saa jättää mikkiä kiinni silloin kun puhuja puhuu."""
    n = 1200
    a_on = np.zeros(n, dtype=bool)
    b_on = np.ones(n, dtype=bool)
    a_on[500:800] = True                    # a ottaa vuoron
    levels_a = np.full(n, -60.0)
    levels_a[500:800] = -18.0
    grid = _Grid(_Lane("a", a_on, levels_a),
                 _Lane("b", b_on, np.full(n, -18.0)))
    out = masks.duck_masks(grid, _Settings())
    assert not out["a"][560:760].any(), "oma vuoro jäi vaimennetuksi"
