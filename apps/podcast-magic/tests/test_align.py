"""Kohdistus: Whisperin sanat pakotetaan ääneen, ja sanojen alut korjataan.

Neuroverkko (torchaudion MMS_FA) ei ole tässä testattavana: kohdistin annetaan
parametrina. Täällä todistetaan kaikki sen ympärillä: tekstin siistiminen,
ryhmittely tauoista, ajan siirto takaisin koko äänen kelloon, hylkäyssäännöt,
korjattujen sanojen muoto, välimuisti ja torchin kytkentä valekirjastoilla.
"""

from __future__ import annotations

import json
import sys
import types

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


# --- Tekstin siistiminen -------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (" Niin,", "niin"),
        ("Kysytäänpäs", "kysytaanpas"),
        ("tekoälyllä.", "tekoalylla"),
        ("työ", "tyo"),
        ("Åland", "aland"),
        ("don't", "don't"),
        ("don’t", "don't"),
        ("...", ""),
        ("2026", ""),
        ("  ", ""),
    ],
)
def test_words_are_romanised_to_what_the_model_knows(text, expected):
    assert align.normalise_word(text) == expected


# --- Ryhmittely ---------------------------------------------------------------


def test_groups_follow_the_segments_and_skip_words_without_a_start():
    raw = {"segments": [{"words": [_word("a", 1.0, 1.2), {"word": "ei aikaa"}]}]}
    groups = align.groups_of(raw)
    assert [[w["word"] for w in g] for g in groups] == [["a"]]


def test_a_flat_word_list_is_split_at_long_gaps():
    raw = {"words": [_word("a", 1.0, 1.2), _word("b", 1.3, 1.5), _word("c", 6.0, 6.2)]}
    assert [[w["word"] for w in g] for g in align.groups_of(raw)] == [["a", "b"], ["c"]]


def test_a_result_without_words_has_no_groups():
    assert align.groups_of({"segments": [{"text": "ei sanoja"}]}) == []


def test_a_pause_shorter_than_half_a_second_keeps_the_words_in_one_group():
    """Rajat kirjaimellisina: 0,4 s on puheen sisäinen tauko, 0,6 s ei ole."""
    assert len(align.split_at_pauses([[_word("a", 1.0, 1.2), _word("b", 1.6, 2.0)]])) == 1
    assert len(align.split_at_pauses([[_word("a", 1.0, 1.2), _word("b", 1.8, 2.0)]])) == 2


def test_the_window_is_the_group_with_padding_clipped_to_the_audio():
    words = [_word("a", 2.0, 2.5), _word("b", 2.5, 3.0)]
    assert align.window(words, 10.0, pad=0.5) == (1.5, 3.5)
    assert align.window(words, 3.2, pad=0.5) == (1.5, 3.2)
    assert align.window([_word("a", 0.2, 0.4)], 10.0, pad=0.5) == (0.0, 0.9)


# --- Kohdistus ----------------------------------------------------------------


def test_aligned_times_are_moved_back_to_the_whole_audio_clock():
    out = align.align_words(
        [_word(" Niin,", 2.0, 2.4), _word("kyllä", 2.5, 3.0)], _audio(), fake_align
    )
    assert out[0]["ctc_start"] == pytest.approx(2.0)
    assert out[0]["ctc_end"] == pytest.approx(2.05)
    assert out[1]["ctc_start"] == pytest.approx(2.5)
    assert out[1]["word"] == "kyllä" and out[1]["start"] == 2.5


def test_the_aligner_gets_the_padded_chunk_and_the_cleaned_words():
    seen = {}

    def spy(chunk, words):
        seen["samples"], seen["words"] = len(chunk), list(words)
        return [(0.5, 0.6)] * len(words)

    align.align_words([_word("Niin,", 2.0, 2.4), _word("Äiti!", 2.5, 3.0)], _audio(), spy)
    assert seen["words"] == ["niin", "aiti"]
    assert abs(seen["samples"] - 2 * RATE) <= 1


def test_a_word_without_letters_is_skipped_and_gets_no_time():
    seen = []

    def spy(chunk, words):
        seen.extend(words)
        return [(0.5 + 0.4 * i, 0.6 + 0.4 * i) for i in range(len(words))]

    out = align.align_words(
        [_word("niin", 2.0, 2.2), _word("...", 2.2, 2.3), _word("joo", 2.4, 2.6)],
        _audio(),
        spy,
    )
    assert seen == ["niin", "joo"]
    assert out[1]["ctc_start"] is None
    assert out[0]["ctc_start"] is not None and out[2]["ctc_start"] is not None


def test_a_failing_aligner_gives_no_times_and_a_recorded_error_not_a_crash():
    def broken(chunk, words):
        raise RuntimeError("trellis too large")

    errors = []
    out = align.align_words([_word("niin", 2.0, 2.2)], _audio(), broken, errors=errors)
    assert out[0]["ctc_start"] is None
    assert len(errors) == 1 and "trellis too large" in errors[0]


def test_an_aligner_that_returns_the_wrong_number_of_spans_is_a_recorded_error():
    errors = []
    out = align.align_words(
        [_word("niin", 2.0, 2.2), _word("joo", 2.4, 2.6)],
        _audio(),
        lambda chunk, words: [(0.0, 0.1)],
        errors=errors,
    )
    assert [r["ctc_start"] for r in out] == [None, None]
    assert len(errors) == 1 and "spans" in errors[0]


def _shifted(shift_s):
    """Kohdistin sanoo sanan alkavan ``shift_s`` Whisperin leimasta (5,0 s); ikkuna alkaa 4,5 s."""
    errors = []
    out = align.align_words(
        [_word("niin", 5.0, 5.3)],
        _audio(),
        lambda chunk, w: [(0.5 + shift_s, 0.7 + shift_s)],
        pad=0.5,
        errors=errors,
    )
    return out[0], errors


def test_a_late_shift_is_accepted_up_to_what_was_observed():
    """Mitattu käsin kuunnellen: Whisper oli 1,0, 1,4, 1,5 ja 2,5 s liian aikaisin ja
    kohdistin osui 34 ms:n sisään. Suuri siirto *myöhemmäksi* on korjaus."""
    word, errors = _shifted(2.5)
    assert word["ctc_start"] == pytest.approx(7.5)
    assert errors == []


def test_a_late_shift_beyond_the_limit_is_rejected_with_both_times_in_the_message():
    word, errors = _shifted(3.5)
    assert word["ctc_start"] is None and word["ctc_end"] is None
    assert len(errors) == 1 and "niin" in errors[0]
    assert "5.00" in errors[0] and "aligner said" in errors[0]


def test_an_early_shift_is_accepted_only_a_little():
    """Mitattu: kohdistin siirsi sanan 2,4 s aikaisemmaksi ja oli väärässä; Whisper ei
    ole koskaan ollut yli 0,12 s myöhässä."""
    word, errors = _shifted(-0.25)
    assert word["ctc_start"] is not None and errors == []
    word, errors = _shifted(-0.35)
    assert word["ctc_start"] is None and len(errors) == 1


def test_the_early_limit_is_below_the_padding_or_it_could_never_fire():
    assert align.MAX_EARLY_S < align.PAD_S


def test_a_pause_splits_the_group_so_foreign_sound_is_not_aligned_as_a_word():
    """Mitattu: segmentissä oli 2,9 s tauko, jossa kuului toisen mikin ääntä, ja
    kohdistin sijoitti tauon jälkeisen sanan sinne, 2,7 s liian aikaisin."""
    calls = []

    def spy(chunk, words):
        calls.append(list(words))
        return fake_align(chunk, words)

    raw = {
        "segments": [
            _segment(
                [
                    _word("kyllä", 1.0, 1.4),
                    _word("niin", 1.5, 1.8),
                    _word("mitäs", 4.7, 5.0),
                ]
            )
        ]
    }
    align.align_raw(raw, _audio(), spy)
    assert calls == [["kylla", "niin"], ["mitas"]]


def test_every_group_is_aligned_in_order():
    raw = {
        "segments": [
            _segment([_word("yksi", 1.0, 1.2), _word("kaksi", 1.3, 1.6)]),
            _segment([_word("kolme", 8.0, 8.4)]),
        ]
    }
    rows = align.align_raw(raw, _audio(), fake_align)
    assert [r["word"] for r in rows] == ["yksi", "kaksi", "kolme"]
    assert rows[2]["ctc_start"] == pytest.approx(8.0)


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


# --- Torchin kytkentä ---------------------------------------------------------


class _Spans(list):
    pass


def _fake_libraries(monkeypatch, frames=50, spans=((5, 10),)):
    """Valekirjastot: kaikki muu kuin neuroverkko on oikeaa koodia."""

    class Tensor:
        def __init__(self, array):
            self.array = array

        def __getitem__(self, index):
            return Tensor(self.array[index])

        def size(self, axis):
            return self.array.shape[axis]

    torch = types.ModuleType("torch")
    torch.from_numpy = lambda array: Tensor(array)

    class _Mode:
        def __enter__(self):
            return None

        def __exit__(self, *exc):
            return False

    torch.inference_mode = lambda: _Mode()

    class Span:
        def __init__(self, start, end):
            self.start, self.end = start, end

    class Bundle:
        sample_rate = RATE

        def get_model(self, with_star=True):
            assert with_star is False

            class Model:
                def eval(self):
                    return self

                def __call__(self, waveform):
                    class Emission:
                        shape = (1, frames, 28)

                        def __getitem__(self, i):
                            return self

                        def size(self, axis):
                            return frames

                    return Emission(), None

            return Model()

        def get_tokenizer(self):
            return lambda words: [[1, 2] for _ in words]

        def get_aligner(self):
            return lambda emission, tokens: [
                [Span(a, b)] for a, b in spans[: len(tokens)]
            ]

    torchaudio = types.ModuleType("torchaudio")
    torchaudio.pipelines = types.SimpleNamespace(MMS_FA=Bundle())
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "torchaudio", torchaudio)


def test_the_torchaudio_aligner_turns_frames_into_seconds(monkeypatch):
    _fake_libraries(monkeypatch, frames=50, spans=((5, 10),))
    aligner = align.make_aligner()
    # Yksi sekunti ääntä, 50 kehystä: 20 ms kehystä kohti.
    assert aligner(np.zeros(RATE, dtype=np.float32), ["niin"]) == [
        (pytest.approx(0.1), pytest.approx(0.2))
    ]


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
