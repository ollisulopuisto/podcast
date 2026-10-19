"""Kohdistus: Whisperin sanat pakotetaan ääneen, ja sanojen alut korjataan.

Neuroverkko (torchaudion MMS_FA) ei ole tässä testattavana: kohdistin annetaan
parametrina. Täällä todistetaan kaikki sen ympärillä: tekstin siistiminen,
ryhmittely tauoista, ajan siirto takaisin koko äänen kelloon, hylkäyssäännöt,
korjattujen sanojen muoto, komentorivi ja torchin kytkentä valekirjastoilla.
"""

import json
import sys
import types

import numpy as np
import pytest

import wordalign as align

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


def test_the_caller_can_give_its_own_install_hint(monkeypatch):
    monkeypatch.setitem(sys.modules, "torchaudio", None)
    with pytest.raises(align.AlignerUnavailable, match="käytä uv:tä"):
        align.make_aligner("käytä uv:tä")


# --- Korjatut sanat -------------------------------------------------------------


def _row(word, start, end, ctc_start=None, ctc_end=None):
    return {
        "word": word,
        "start": start,
        "end": end,
        "ctc_start": ctc_start,
        "ctc_end": ctc_end,
    }


def test_a_refined_word_takes_the_aligned_start_and_the_longer_end():
    [word] = align.refined([_row(" Niin,", 2.0, 2.4, 2.3, 2.55)])
    assert word == {"word": "Niin,", "start": 2.3, "end": 2.55}
    [word] = align.refined([_row("niin", 2.0, 2.6, 2.3, 2.4)])
    assert (word["start"], word["end"]) == (2.3, 2.6)


def test_a_refined_word_that_was_not_aligned_keeps_whispers_time():
    [word] = align.refined([_row("niin", 1.0, 1.4)])
    assert (word["start"], word["end"]) == (1.0, 1.4)


def test_a_blank_word_is_not_refined():
    assert align.refined([_row("  ", 1.0, 1.2), _row("niin", 2.0, 2.0)]) == [
        {"word": "niin", "start": 2.0, "end": 2.0}
    ]


def test_the_summary_counts_aligned_words_and_the_median_shift():
    rows = [
        _row("a", 1.0, 1.2, 1.1, 1.3),
        _row("b", 2.0, 2.2, 2.3, 2.4),
        _row("c", 3.0, 3.2),
    ]
    summary = align.summarize(rows, ["c at 3.00 s: rejected"])
    assert summary["words"] == 3 and summary["aligned"] == 2
    assert summary["median_shift_ms"] == pytest.approx(200.0)
    assert summary["rejected"] == ["c at 3.00 s: rejected"]


def test_a_summary_with_nothing_aligned_has_no_median():
    assert align.summarize([_row("a", 1.0, 1.2)], [])["median_shift_ms"] is None


# --- Äänen purku ------------------------------------------------------------------


def _wav(path, seconds=1.0, rate=48000, channels=2):
    import wave

    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        t = np.arange(int(seconds * rate)) / rate
        tone = (np.sin(2 * np.pi * 440 * t) * 8000).astype("<i2")
        handle.writeframes(np.repeat(tone, channels).tobytes())


def test_decoding_gives_sixteen_kilohertz_float_mono(tmp_path):
    _wav(tmp_path / "a.wav")
    samples = align.decode(str(tmp_path / "a.wav"))
    assert samples.dtype == np.float32
    assert len(samples) == 16000
    assert 0.1 < float(np.abs(samples).max()) < 0.5  # 8000 / 32768 = 0.24


# --- Työt ja komentorivi ------------------------------------------------------------


def _jobs(tmp_path, names=("a", "b")):
    jobs = []
    for name in names:
        raw = tmp_path / f"{name}.json"
        raw.write_text(
            json.dumps(
                {
                    "segments": [
                        _segment([_word("niin", 1.0, 1.4), _word("joo", 1.6, 2.0)])
                    ]
                }
            ),
            encoding="utf-8",
        )
        jobs.append(
            {
                "audio": f"{name}.wav",
                "raw": str(raw),
                "out": str(tmp_path / f"{name}.rows.json"),
            }
        )
    (tmp_path / "jobs.json").write_text(json.dumps(jobs), encoding="utf-8")
    return jobs


def test_every_job_writes_its_rows_and_rejections(tmp_path):
    jobs = _jobs(tmp_path)
    audio = _audio(5)
    align.run_jobs(jobs, fake_align, decode_audio=lambda path: audio, log=lambda _: None)
    for job in jobs:
        data = json.loads(open(job["out"], encoding="utf-8").read())
        assert data["version"] == align.VERSION
        assert [r["word"] for r in data["rows"]] == ["niin", "joo"]
        assert data["rows"][0]["ctc_start"] is not None
        assert data["rejected"] == []


def test_each_job_is_announced_with_its_position(tmp_path):
    seen = []
    align.run_jobs(
        _jobs(tmp_path), fake_align, decode_audio=lambda path: _audio(5), log=seen.append
    )
    assert seen[0].startswith("[kohdistus (1/2)]") and seen[1].startswith(
        "[kohdistus (2/2)]"
    )


def test_each_audio_file_is_decoded_once(tmp_path):
    decoded = []

    def decode(path):
        decoded.append(path)
        return _audio(5)

    align.run_jobs(_jobs(tmp_path), fake_align, decode_audio=decode, log=lambda _: None)
    assert decoded == ["a.wav", "b.wav"]


def test_the_command_line_runs_the_jobs_file(tmp_path, monkeypatch):
    jobs = _jobs(tmp_path)
    monkeypatch.setattr(align, "decode", lambda path: _audio(5))
    assert align.main([str(tmp_path / "jobs.json")], aligner=fake_align) == 0
    assert (tmp_path / "a.rows.json").is_file() and (tmp_path / "b.rows.json").is_file()
    assert jobs


def test_check_loads_the_aligner_and_says_so(capsys):
    assert align.main(["--check"], aligner=fake_align) == 0
    assert "toimii" in capsys.readouterr().out


def test_check_fails_with_the_reason_when_the_aligner_cannot_start(monkeypatch, capsys):
    def broken(install=align.INSTALL):
        raise align.AlignerUnavailable("torch puuttuu")

    monkeypatch.setattr(align, "make_aligner", broken)
    assert align.main(["--check"]) == 1
    assert "torch puuttuu" in capsys.readouterr().err


def test_the_command_line_wants_a_job_or_a_check():
    with pytest.raises(SystemExit):
        align.main([], aligner=fake_align)


# --- Kirjasto on yksi tiedosto ------------------------------------------------------


def test_the_library_imports_only_the_standard_library_and_numpy():
    """Colab lataa tämän tiedoston sellaisenaan: muu tuonti kaataa sen tuontiin,
    eikä mikään paikallinen ajo huomaa. torch tuodaan vasta funktion sisällä."""
    import ast
    import sys
    from pathlib import Path

    tree = ast.parse(Path(align.__file__).read_text(encoding="utf-8"))
    top_level = {
        (a.name if isinstance(n, ast.Import) else n.module).split(".")[0]
        for n in tree.body
        if isinstance(n, ast.Import | ast.ImportFrom)
        for a in (n.names if isinstance(n, ast.Import) else [n])
    }
    assert top_level <= set(sys.stdlib_module_names) | {"numpy"}, top_level


def test_a_rejected_word_reaches_the_jobs_output_with_its_reason(tmp_path):
    jobs = _jobs(tmp_path, names=("a",))

    def far(chunk, words):
        return [(5.0 + i, 5.1 + i) for i in range(len(words))]

    align.run_jobs(jobs, far, decode_audio=lambda path: _audio(12), log=lambda _: None)
    data = json.loads(open(jobs[0]["out"], encoding="utf-8").read())
    assert [r["ctc_start"] for r in data["rows"]] == [None, None]
    assert len(data["rejected"]) == 2 and "rejected" in data["rejected"][0]


def test_the_version_changes_only_on_purpose():
    """``ctc1`` on myös välimuistin nimessä ja ``timing: "ctc-v1"`` kuulaksen
    tiedostossa. Jos sääntö tai malli vaihtuu, numero vaihtuu tahallaan ja
    colab-transcriben ``ALIGN_TIMING`` seuraa (sen testi vertaa näitä)."""
    assert align.VERSION == "ctc1"
