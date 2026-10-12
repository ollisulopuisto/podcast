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
