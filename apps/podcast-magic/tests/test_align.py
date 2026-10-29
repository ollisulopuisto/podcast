"""Kohdistus: Whisperin sanat pakotetaan ääneen, ja sanojen alut korjataan.

Neuroverkko (torchaudion MMS_FA) ei ole tässä testattavana: kohdistin annetaan
parametrina. Täällä todistetaan kaikki sen ympärillä: tekstin siistiminen,
ryhmittely tauoista, ajan siirto takaisin koko äänen kelloon, hylkäyssäännöt,
korjattujen sanojen muoto, välimuisti ja torchin kytkentä valekirjastoilla.
"""

from __future__ import annotations

import json
import sys

import numpy as np
import pytest

from podcastmagic.transcribe import align
from podcastmagic.transcribe.options import Options

RATE = 16000


def fake_align(chunk, words):
    """Sana i alkaa 0,5 + 0,5 * i s ikkunan alusta: ensimmäinen osuu Whisperin
    leimaan kun täyte on oletus (0,5 s), seuraavat noin puolen sekunnin välein."""
    return [(0.5 + 0.5 * i, 0.55 + 0.5 * i) for i in range(len(words))]


def _word(text, start, end):
    return {"word": text, "start": start, "end": end}


def _segment(words):
    return {"start": words[0]["start"], "end": words[-1]["end"], "words": words}


def _audio(seconds=20):
    return np.zeros(seconds * RATE, dtype=np.float32)


# --- Korjatut sanat -----------------------------------------------------------


def _row(word, start, end, ctc_start=None, ctc_end=None):
    return {
        "word": word,
        "start": start,
        "end": end,
        "ctc_start": ctc_start,
        "ctc_end": ctc_end,
    }


def test_an_aligned_word_takes_the_aligned_start_and_the_longer_end():
    """Alku on kohdistimen (mitattu), loppua ei ole mitattu: pidempi kahdesta on varovainen
    valinta, koska vaimennus käyttää sanojen välejä äänen paikkana."""
    [word] = align.refined_words([_row(" Niin,", 2.0, 2.4, 2.3, 2.55)])
    assert word.text == "Niin," and word.start == pytest.approx(2.3)
    assert word.length == pytest.approx(2.55 - 2.3)
    [word] = align.refined_words([_row("niin", 2.0, 2.6, 2.3, 2.4)])
    assert word.length == pytest.approx(2.6 - 2.3)


def test_a_word_moved_past_its_old_end_takes_the_aligned_end():
    [word] = align.refined_words([_row("niin", 5.0, 5.3, 7.5, 7.7)])
    assert word.start == pytest.approx(7.5) and word.length == pytest.approx(0.2)


def test_a_word_that_was_not_aligned_keeps_whispers_time():
    [word] = align.refined_words([_row("niin", 1.0, 1.4)])
    assert word.start == pytest.approx(1.0) and word.length == pytest.approx(0.4)


def test_a_blank_word_is_dropped_and_a_zero_length_one_gets_the_floor():
    words = align.refined_words([_row("  ", 1.0, 1.2), _row("niin", 2.0, 2.0)])
    assert [w.text for w in words] == ["niin"]
    assert words[0].length == pytest.approx(0.02)


def test_the_summary_counts_aligned_words_and_the_median_shift():
    rows = [
        _row("a", 1.0, 1.2, 1.1, 1.3),
        _row("b", 2.0, 2.2, 2.3, 2.5),
        _row("c", 3.0, 3.2),
        _row("...", 4.0, 4.1),
    ]
    summary = align.summarize(rows, ["c at 3.00 s: rejected"])
    assert summary["words"] == 4 and summary["aligned"] == 2
    assert summary["median_shift_ms"] == pytest.approx(200.0)
    assert summary["rejected"] == ["c at 3.00 s: rejected"]


def test_a_summary_with_nothing_aligned_has_no_median():
    summary = align.summarize([_row("a", 1.0, 1.2)], [])
    assert summary["aligned"] == 0 and summary["median_shift_ms"] is None


# --- Välimuisti ---------------------------------------------------------------


def _raw():
    return {"segments": [_segment([_word("yksi", 1.0, 1.2), _word("kaksi", 1.3, 1.6)])]}


def test_the_cache_name_carries_the_whisper_fingerprint_and_the_alignment_version(
    tmp_path,
):
    path = align.cache_path(tmp_path, "/x/jakso.wav", Options())
    assert path.parent == tmp_path
    assert path.name == f"jakso.{Options().fingerprint()}.align-{align.VERSION}.json"


def test_the_aligner_is_not_loaded_when_the_alignment_is_cached(tmp_path):
    cache = tmp_path / "a.json"
    calls = []

    def factory():
        calls.append(1)
        return fake_align

    first = align.refine(_raw(), _audio(), factory, cache)
    assert cache.is_file() and calls == [1]
    second = align.refine(
        _raw(), _audio(), lambda: pytest.fail("loaded the aligner"), cache
    )
    assert [(w.text, w.start, w.length) for w in second[0]] == [
        (w.text, w.start, w.length) for w in first[0]
    ]
    assert second[1]["aligned"] == first[1]["aligned"] == 2


def test_segment_alignment_can_place_late_words_without_inventing_seed_times(tmp_path):
    raw = {"segments": [{"start": 1.0, "end": 10.0, "text": "yksi kaksi kolme"}]}
    cache = tmp_path / "segment-align.json"
    seen = []

    def fake_segment_aligner(chunk, words):
        seen.append((len(chunk), words))
        return [(0.4, 0.7), (4.0, 4.4), (7.2, 7.8)]

    words, summary = align.refine_segments(raw, _audio(), lambda: fake_segment_aligner, cache)

    assert [word.text for word in words] == ["yksi", "kaksi", "kolme"]
    assert [word.start for word in words] == pytest.approx([0.9, 4.5, 7.7])
    assert [word.length for word in words] == pytest.approx([0.3, 0.4, 0.6])
    assert summary["aligned"] == 3 and seen[0][1] == ["yksi", "kaksi", "kolme"]
    assert cache.is_file()


def test_the_audio_is_decoded_only_when_the_alignment_is_not_cached(tmp_path):
    """Tunnin ääni on 115 MB int16:na: välimuistiosuma ei saa purkaa sitä turhaan."""
    cache = tmp_path / "a.json"
    decoded = []

    def decode():
        decoded.append(1)
        return _audio()

    align.refine(_raw(), decode, lambda: fake_align, cache)
    assert decoded == [1]
    align.refine(_raw(), decode, lambda: pytest.fail("loaded"), cache)
    assert decoded == [1]


def test_a_cache_made_from_other_words_is_ignored(tmp_path):
    cache = tmp_path / "a.json"
    align.refine(_raw(), _audio(), lambda: fake_align, cache)
    other = {"segments": [_segment([_word("kolme", 1.0, 1.2), _word("neljä", 1.3, 1.6)])]}
    calls = []

    def factory():
        calls.append(1)
        return fake_align

    words, _ = align.refine(other, _audio(), factory, cache)
    assert calls == [1] and [w.text for w in words] == ["kolme", "neljä"]


@pytest.mark.parametrize(
    "damage", ["not json", json.dumps({"version": "old", "rows": []})]
)
def test_a_damaged_or_old_cache_is_recomputed(tmp_path, damage):
    cache = tmp_path / "a.json"
    cache.write_text(damage, encoding="utf-8")
    calls = []

    def factory():
        calls.append(1)
        return fake_align

    words, summary = align.refine(_raw(), _audio(), factory, cache)
    assert calls == [1] and summary["aligned"] == 2 and len(words) == 2


def test_a_cache_from_another_alignment_version_is_ignored_even_if_the_words_match(
    tmp_path,
):
    """Sääntö tai malli vaihtuu → versio vaihtuu → vanha tulos ei kelpaa uuden alla."""
    cache = tmp_path / "a.json"
    align.refine(_raw(), _audio(), lambda: fake_align, cache)
    data = json.loads(cache.read_text(encoding="utf-8"))
    data["version"] = "ctc0"
    cache.write_text(json.dumps(data), encoding="utf-8")
    calls = []

    def factory():
        calls.append(1)
        return fake_align

    align.refine(_raw(), _audio(), factory, cache)
    assert calls == [1]


def test_a_cache_that_cannot_be_written_is_reported_not_fatal(tmp_path):
    words, summary = align.refine(
        _raw(), _audio(), lambda: fake_align, tmp_path / "ei-ole-kansiota" / "a.json"
    )
    assert len(words) == 2 and summary["aligned"] == 2
    assert summary["cache_error"]


def test_refine_without_a_cache_path_just_aligns():
    words, summary = align.refine(_raw(), _audio(), lambda: fake_align, None)
    assert len(words) == 2 and summary["aligned"] == 2


def test_a_result_without_words_gives_no_words_and_does_not_load_the_aligner():
    words, summary = align.refine(
        {"segments": []}, _audio(), lambda: pytest.fail("loaded"), None
    )
    assert words == [] and summary["words"] == 0




def test_a_missing_library_says_how_to_install_it(monkeypatch):
    monkeypatch.setitem(sys.modules, "torchaudio", None)
    with pytest.raises(align.AlignerUnavailable) as caught:
        align.make_aligner()
    assert align.INSTALL in str(caught.value)


def test_availability_names_the_missing_part_and_the_install_command(monkeypatch):
    monkeypatch.setattr(align, "_installed", lambda name: name != "torchaudio")
    status = align.availability()
    assert status["available"] is False
    assert "torchaudio" in status["reason"] and status["install"] == align.INSTALL
    monkeypatch.setattr(align, "_installed", lambda name: True)
    assert align.availability()["available"] is True
