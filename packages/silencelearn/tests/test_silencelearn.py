"""Opittu kynnys: laskenta ilman istuntoa ja ilman ääntä.

Kirjasto saa syötteenään raidat ja ``Source``n, joka vastaa kahteen kysymykseen:
mitkä sanat tiedostossa ovat ja mikä on taso tietyllä välillä. Testit antavat
molemmat valmiina, joten ne mittaavat laskentaa eivätkä ffmpegiä tai nhsx:ää.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import numpy as np
import pytest

import silencelearn as sl
from silencelearn import Region, Track

BASE_DB = -70.0


class Fake:
    """Taso on sen jakson taso jonka sisään välin keskipiste osuu."""

    def __init__(self, spans: dict[str, list[tuple[float, float, float]]],
                 words: dict[str, list[tuple[float, float]]], missing: bool = False):
        self.spans = spans
        self._words = words
        self._missing = missing
        self.word_calls: list[str] = []

    def words(self, ref):
        self.word_calls.append(ref)
        return self._words.get(ref, [])

    def level(self, ref, start, end):
        if ref not in self.spans:
            return None
        middle = (start + end) / 2
        for a, b, db in self.spans[ref]:
            if a <= middle < b:
                return db
        return BASE_DB

    def missing(self):
        return self._missing


def word(start: float, length: float = 0.5) -> tuple[float, float]:
    return (start, length)


def head(ref: str, muted_to: float = 10.0, end: float = 60.0) -> Track:
    return Track(ref, [
        Region(ref, 0.0, muted_to, 0.0, muted=True),
        Region(ref, muted_to, end - muted_to, muted_to),
    ])


SPEECH_DB = -14.0


def speech(starts, db=SPEECH_DB):
    return [(s, s + 0.5, db) for s in starts]


def test_the_threshold_is_the_level_of_the_muted_clips_not_of_the_cough():
    """Vuoto −30,5 dBFS 40 %:ssa alueesta, yskäisy −8 dBFS 4 %:ssa."""
    source = Fake({"a": [(1.0, 5.0, -30.5), (7.0, 7.4, -8.0), *speech([12, 14, 20, 30])]},
                  {"a": [word(t) for t in (12.0, 14.0, 20.0, 30.0)]})
    found = sl.calibrate([head("a")], source)["a"]
    assert found.threshold is not None, found.reason
    assert found.threshold == pytest.approx(-30.5 + sl.MARGIN_DB, abs=1.0)
    assert found.threshold < -8 - 15
    assert found.muted_seconds == pytest.approx(10.0)


def test_a_track_with_too_little_muted_audio_is_not_calibrated():
    track = Track("a", [Region("a", 0.0, 1.0, 0.0, muted=True),
                        Region("a", 1.0, 59.0, 1.0)])
    found = sl.calibrate([track], Fake({"a": speech([20])}, {"a": [word(20.0)]}))["a"]
    assert found.threshold is None
    assert found.muted_seconds == pytest.approx(1.0)
    assert "vähän" in found.reason


def test_clips_as_loud_as_the_speech_are_not_a_threshold():
    """Vahingossa vaimennettu puhe: kynnys sen tasolla vaientaisi kaiken."""
    source = Fake({"a": [(0.0, 10.0, SPEECH_DB), *speech([12, 14, 20, 30])]},
                  {"a": [word(t) for t in (12.0, 14.0, 20.0, 30.0)]})
    found = sl.calibrate([head("a")], source)["a"]
    assert found.threshold is None
    assert "puheen" in found.reason


def test_a_word_left_unmuted_is_never_below_the_threshold():
    """Muokatulla ajalla vaimentamatta jätetty sana on käyttäjän päätös."""
    track = Track("a", [Region("a", 0.0, 10.0, 0.0, muted=True),
                        Region("a", 10.0, 50.0, 10.0),
                        Region("a", 60.0, 5.0, 60.0, muted=True)])
    source = Fake({"a": [(1.0, 9.0, -24.0), *speech([12, 14, 20]), (24.0, 24.5, -27.0)]},
                  {"a": [word(12.0), word(14.0), word(20.0), word(24.0)]})
    found = sl.calibrate([track], source)["a"]
    assert found.threshold is not None, found.reason
    assert found.threshold <= -27.0 - sl.KEEP_MARGIN_DB + 0.01
    assert found.clamp_note


def test_leak_from_another_track_raises_the_threshold():
    """Toisen puhuessa vaimennettu mikki kuulee hänet: harvinainen vuoto ei näy
    koko vaimennetun ajan persentiilissä, mutta kynnyksen pitää estää se."""
    a = head("a")
    b = Track("b", [Region("b", 0.0, 60.0, 0.0)])
    leak = [(2.0, 3.0, -40.0), (3.5, 4.5, -40.0), (5.5, 6.5, -40.0), (7.5, 8.5, -40.0)]
    source = Fake(
        {"a": [*leak, *speech([12, 14, 20, 30])],
         "b": [(s, e, -10.0) for s, e, _ in leak]},
        {"a": [word(t) for t in (12.0, 14.0, 20.0, 30.0)],
         "b": [word(2.0, 1.0), word(3.5, 1.0), word(5.5, 1.0), word(7.5, 1.0)]},
    )
    found = sl.calibrate([a, b], source)["a"]
    assert found.threshold is not None, found.reason
    assert found.threshold >= -40.0 + sl.MARGIN_DB - 0.5


def test_the_gap_limit_sits_between_bleed_and_simultaneous_speech():
    """Vuodon ero 20 dB, yhtäaikaisen puheen ero −6 dB: raja niiden välissä."""
    a = Track("a", [Region("a", 0.0, 5.0, 0.0, muted=True), Region("a", 5.0, 55.0, 5.0)])
    b = Track("b", [Region("b", 0.0, 55.0, 0.0), Region("b", 55.0, 5.0, 55.0, muted=True)])
    a_words = [10.0, 20.0, 30.0, 40.0]
    b_words = [1.5, 3.0, *a_words]
    # Vuoto ja B:n taso kestävät pidempään kuin sanat jotka ne laukaisevat:
    # reunaikkunat, joiden keskipiste on kummankin ulkopuolella, mittaisivat
    # eron nollaksi eivätkä kertoisi vuodosta mitään.
    source = Fake(
        {"a": [(0.5, 4.5, -40.0), *speech(a_words, -14.0)],
         "b": [(0.5, 4.5, -20.0), *[(t, t + 0.5, -20.0) for t in a_words]]},
        {"a": [word(t) for t in a_words], "b": [word(t) for t in b_words]},
    )
    found = sl.calibrate([a, b], source)["a"]
    assert found.bleed_gap == pytest.approx(20.0, abs=0.5)
    assert found.speech_gap == pytest.approx(-6.0, abs=0.5)
    assert found.dominance == pytest.approx(7.0, abs=0.6)
    assert not found.gap_note


def test_missing_audio_is_said_instead_of_no_muted_regions():
    found = sl.calibrate([head("a")], Fake({}, {"a": [word(12.0)]}, missing=True))["a"]
    assert found.threshold is None
    assert found.reason == "ääntä ei löytynyt"


def test_nothing_muted_says_so():
    track = Track("a", [Region("a", 0.0, 60.0, 0.0)])
    found = sl.calibrate([track], Fake({"a": []}, {"a": [word(20.0)]}))["a"]
    assert found.threshold is None and found.muted_seconds == 0.0
    assert "ei käsin vaimennettuja alueita" in found.reason


def test_the_edited_time_ends_at_the_last_muted_region():
    tracks = [head("a", muted_to=20.0), head("b", muted_to=7.0)]
    assert sl.horizon(tracks) == pytest.approx(20.0)
    assert sl.horizon([Track("a", [Region("a", 0.0, 9.0, 0.0)])]) == 0.0


def test_a_files_words_are_read_once_however_many_regions_use_it():
    """Sanat luetaan tiedostosta, ja sama tiedosto voi olla aikajanalla monesti."""
    track = Track("a", [Region("a", 0.0, 10.0, 0.0, muted=True),
                        Region("a", 10.0, 10.0, 10.0), Region("a", 20.0, 10.0, 20.0),
                        Region("a", 30.0, 30.0, 30.0)])
    source = Fake({"a": speech([12, 22, 32])}, {"a": [word(12.0), word(22.0), word(32.0)]})
    sl.calibrate([track], source)
    assert source.word_calls.count("a") == 1


@pytest.mark.parametrize("q", [0, 10, 25, 50, 90, 95, 100])
@pytest.mark.parametrize("n", [1, 2, 3, 7, 40])
def test_the_percentile_is_numpys(n, q):
    """Kirjasto ei tuo numpya, joten sen persentiili on kirjoitettu itse."""
    rng = np.random.default_rng(n * 101 + q)
    values = list(rng.normal(-40, 10, n))
    assert sl.percentile(values, q) == pytest.approx(float(np.percentile(values, q)), abs=1e-9)


def test_the_library_imports_nothing_but_the_standard_library():
    """Tämä tiedosto ladataan sellaisenaan Colabiin, ja siellä ei ole työtilaa.

    Yksi tiedosto ja pelkkä standardikirjasto: muuten Colabissa ajettava
    skripti kaatuisi tuontiin, eikä mikään paikallinen testi huomaisi sitä.
    """
    source = Path(sl.__file__)
    tree = ast.parse(source.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    stdlib = set(sys.stdlib_module_names) | {"__future__"}
    assert names <= stdlib, sorted(names - stdlib)
    assert source.name == "silencelearn.py", "Colabiin ladataan yhtenä tiedostona"


# --- Puheen taso ja lohkot (PR 57, siirretty kirjastoon) --------------------


def test_muted_pieces_next_to_each_other_are_one_block():
    pieces = [Region("a", i * 0.08, 0.08, i * 0.08, muted=True) for i in range(125)]
    blocks = sl._muted_blocks(pieces)
    assert len(blocks) == 1
    assert blocks[0][0] == pytest.approx(0.0) and blocks[0][1] == pytest.approx(10.0)


def test_muted_blocks_are_split_by_a_real_gap_and_ignore_unmuted_regions():
    regions = [
        Region("a", 20.0, 5.0, 20.0, muted=True),
        Region("a", 0.0, 4.0, 0.0, muted=True),
        Region("a", 4.0, 16.0, 4.0),          # vaimentamaton: rako
        Region("a", 3.0, 3.0, 3.0, muted=True),  # limittyy: loppu on suurempi
    ]
    assert sl._muted_blocks(regions) == [(0.0, 6.0), (20.0, 5.0)]


def test_a_gap_just_above_the_limit_keeps_two_blocks():
    one = Region("a", 0.0, 5.0, 0.0, muted=True)
    two = Region("a", 5.0 + 0.02, 5.0, 5.02, muted=True)
    assert len(sl._muted_blocks([one, two])) == 2
    close = Region("a", 5.0 + 0.005, 5.0, 5.005, muted=True)
    assert len(sl._muted_blocks([one, close])) == 1


def test_a_turn_cut_into_many_pieces_gives_its_seconds_and_its_windows():
    """125 palaa à 0,08 s ovat alle ikkunan (ja alle 0,1 s), joten kukin pala yksin
    ei antaisi yhtään mittausta; yhtenä lohkona ne ovat 10 s."""
    pieces = [Region("a", i * 0.08, 0.08, i * 0.08, muted=True) for i in range(125)]
    track = Track("a", [*pieces, Region("a", 10.0, 50.0, 10.0)])
    source = Fake({"a": [(0.0, 10.0, -30.5), *speech([12, 14, 20, 30])]},
                  {"a": [word(t) for t in (12.0, 14.0, 20.0, 30.0)]})
    found = sl.calibrate([track], source)["a"]
    assert found.threshold is not None, found.reason
    assert found.muted_seconds == pytest.approx(10.0)
    assert found.frames > 30


def test_the_speech_level_is_taken_from_the_words_the_user_left_unmuted():
    """Muokatun ajan jälkeen litteroidut sanat voivat olla kohinaa (Perttu, 07
    uutiset: −49 dBFS, puhe −25…−31) eivätkä saa laskea puheen tasoa."""
    track = Track("a", [
        Region("a", 0.0, 10.0, 0.0, muted=True),
        Region("a", 10.0, 50.0, 10.0),
        Region("a", 60.0, 5.0, 60.0, muted=True),
        Region("a", 65.0, 55.0, 65.0),
    ])
    vetted = {12.0: -20.0, 14.0: -16.0, 16.0: -14.0, 18.0: -10.0}
    noise = [70.0 + i for i in range(11)]
    spans = [(1.0, 9.0, -30.5)]
    spans += [(t, t + 0.5, db) for t, db in vetted.items()]
    spans += [(t, t + 0.5, -49.0) for t in noise]
    source = Fake({"a": spans}, {"a": [word(t) for t in (*vetted, *noise)]})
    found = sl.calibrate([track], source)["a"]
    assert found.threshold is not None, found.reason
    assert found.speech_level == pytest.approx(sl.percentile(list(vetted.values()), 25.0))


def test_without_vetted_words_the_speech_level_is_the_upper_quarter_of_the_transcript():
    """Ei yhtään vaimentamatta jätettyä sanaa muokatulla ajalla: puhetaso mitataan
    litteroiduista sanoista, mutta niiden hiljaisin neljännes on usein kohinaa."""
    starts = [12.0 + 1.4 * i for i in range(40)]
    loud = starts[15:]
    spans = [(1.0, 9.0, -30.5)] + [(t, t + 0.5, -14.0) for t in loud]
    spans += [(t, t + 0.5, -60.0) for t in starts[:15]]
    source = Fake({"a": spans}, {"a": [word(t) for t in starts]})
    found = sl.calibrate([head("a")], source)["a"]
    assert found.threshold is not None, found.reason
    assert found.speech_level == pytest.approx(-14.0)


def test_pieces_that_touch_exactly_are_one_block_and_the_gap_limit_is_inclusive():
    one = Region("a", 0.0, 5.0, 0.0, muted=True)
    touching = Region("a", 5.0, 5.0, 5.0, muted=True)
    assert sl._muted_blocks([one, touching]) == [(0.0, 10.0)]
    at_limit = Region("a", 5.0 + sl.BLOCK_GAP, 5.0, 5.0, muted=True)
    assert len(sl._muted_blocks([one, at_limit])) == 1


def test_a_short_piece_inside_a_long_one_does_not_shorten_the_block():
    long = Region("a", 0.0, 10.0, 0.0, muted=True)
    inside = Region("a", 2.0, 3.0, 2.0, muted=True)
    assert sl._muted_blocks([long, inside]) == [(0.0, 10.0)]


def test_exactly_the_minimum_number_of_vetted_words_is_enough_for_the_speech_level():
    """``MIN_SPEECH_WORDS`` sanaa riittää: kolme vaimentamatonta sanaa ennen horisonttia."""
    track = Track("a", [
        Region("a", 0.0, 10.0, 0.0, muted=True),
        Region("a", 10.0, 50.0, 10.0),
        Region("a", 60.0, 5.0, 60.0, muted=True),
        Region("a", 65.0, 55.0, 65.0),
    ])
    vetted = [12.0, 14.0, 16.0]
    assert len(vetted) == sl.MIN_SPEECH_WORDS
    noise = [70.0 + i for i in range(11)]
    spans = [(1.0, 9.0, -30.5)] + [(t, t + 0.5, -14.0) for t in vetted]
    spans += [(t, t + 0.5, -49.0) for t in noise]
    source = Fake({"a": spans}, {"a": [word(t) for t in (*vetted, *noise)]})
    found = sl.calibrate([track], source)["a"]
    assert found.speech_level == pytest.approx(-14.0)  # ei kohinan p75/p25


def test_a_threshold_exactly_guard_db_below_the_speech_level_is_refused():
    """Raja on avoin ylös: kynnys = puhetaso − ``GUARD_DB`` hylätään."""
    speech_db = -30.5 + sl.MARGIN_DB + sl.GUARD_DB   # kynnys = −30,5 + 1 = −29,5
    source = Fake({"a": [(1.0, 9.0, -30.5), *speech([12, 14, 20, 30], db=speech_db)]},
                  {"a": [word(t) for t in (12.0, 14.0, 20.0, 30.0)]})
    found = sl.calibrate([head("a")], source)["a"]
    assert found.threshold is None and "puheen" in found.reason
    just_above = Fake(
        {"a": [(1.0, 9.0, -30.5), *speech([12, 14, 20, 30], db=speech_db + 0.2)]},
        {"a": [word(t) for t in (12.0, 14.0, 20.0, 30.0)]})
    assert sl.calibrate([head("a")], just_above)["a"].threshold is not None
