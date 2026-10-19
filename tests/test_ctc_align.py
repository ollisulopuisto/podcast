"""Pakotettu kohdistus: Whisperin sanat kohdistetaan ääneen ja verrataan käsin merkittyihin.

Neuroverkko (torchaudion MMS_FA) ei ole tässä testattavana: kohdistin annetaan
parametrina, ja täällä todistetaan kaikki sen ympärillä: tekstin siistiminen,
segmenttien ikkunointi, ajan siirto takaisin koko äänen aika-akselille,
epäonnistumisen käsittely ja vertailu merkintöihin.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "ctc_align", ROOT / "scripts" / "ab" / "ctc_align.py"
)
ca = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ca)

RATE = 16000


def fake_align(chunk, words):
    """Sana i alkaa 0,5 + 0,5 * i sekuntia ikkunan alusta: ensimmäinen osuu Whisperin
    leimaan, kun täyte on oletus (0,5 s), ja seuraavat noin puolen sekunnin välein."""
    return [(0.5 + 0.5 * i, 0.55 + 0.5 * i) for i in range(len(words))]


def _segment(words, start, end):
    return {"start": start, "end": end, "words": words}


def _word(text, start, end):
    return {"word": text, "start": start, "end": end}


# --- Tekstin siistiminen -------------------------------------------------------


# --- Ikkunointi ja ajan siirto -------------------------------------------------


def test_every_rejected_word_is_printed_not_only_the_first_few(tmp_path, capsys):
    words = [_word(f"sana{i}", 1.0 + 2 * i, 1.4 + 2 * i) for i in range(12)]
    (tmp_path / "olli.json").write_text(
        json.dumps({"segments": [_segment([w], w["start"], w["end"]) for w in words]}),
        encoding="utf-8",
    )
    sf.write(tmp_path / "olli.wav", np.zeros(30 * 16000, dtype=np.float32), 16000)

    def far(chunk, w):
        return [(4.2, 4.4)] * len(w)

    ca.main([str(tmp_path / "olli.json"), str(tmp_path / "olli.wav")], aligner=far)
    printed = capsys.readouterr().out
    assert printed.count("rejected") == 12


def test_words_without_a_start_time_are_left_out_of_the_transcript():
    audio = np.zeros(5 * RATE, dtype=np.float32)
    data = {
        "segments": [_segment([_word("niin", 1.0, 1.2), {"word": "ei aikaa"}], 1.0, 1.2)]
    }
    assert [r["word"] for r in ca.align_transcript(data, audio, fake_align)] == ["niin"]


def test_a_file_without_words_is_refused():
    with pytest.raises(SystemExit):
        ca.segments_of({"segments": [{"text": "ei sanoja"}]})


def test_audio_is_resampled_to_sixteen_kilohertz():
    x = np.zeros(48000 * 2, dtype=np.float32)
    assert len(ca.resample(x, 48000)) == 32000
    assert len(ca.resample(x[:44100], 44100)) == 16000
    y = np.ones(100, dtype=np.float32)
    assert ca.resample(y, 16000) is y


# --- Merkinnät ja vertailu -------------------------------------------------------


MARKS = """TAUON JÄLKEEN
9.000 Niin, 0:08,882
48.760 Kyllä. 0:49,023
228.120 Joo. XX
SISÄLLÄ
10.820 paradoksi. 10.880
epäselvä rivi
"""


def test_marks_are_read_in_any_of_the_time_forms_and_unfilled_rows_are_skipped():
    marks = ca.parse_marks(MARKS)
    assert [(m["group"], m["word"]) for m in marks] == [
        ("tauon jälkeen", "Niin,"),
        ("tauon jälkeen", "Kyllä."),
        ("sisällä", "paradoksi."),
    ]
    assert marks[0]["whisper"] == pytest.approx(9.0)
    assert marks[0]["mine"] == pytest.approx(8.882)
    assert marks[1]["mine"] == pytest.approx(49.023)
    assert marks[2]["mine"] == pytest.approx(10.88)


def test_time_forms():
    assert ca.seconds("0:08,882") == pytest.approx(8.882)
    assert ca.seconds("1:03.497") == pytest.approx(63.497)
    assert ca.seconds("1:02:03,5") == pytest.approx(3723.5)
    assert ca.seconds("12.5") == pytest.approx(12.5)
    assert ca.seconds("12,5") == pytest.approx(12.5)
    with pytest.raises(ValueError):
        ca.seconds("XX")


def _rows():
    return [
        {"word": "Niin,", "start": 9.0, "end": 9.3, "ctc_start": 8.9, "ctc_end": 9.2},
        {
            "word": "Kyllä.",
            "start": 48.76,
            "end": 49.1,
            "ctc_start": 49.01,
            "ctc_end": 49.3,
        },
        {
            "word": "paradoksi.",
            "start": 10.82,
            "end": 11.2,
            "ctc_start": None,
            "ctc_end": None,
        },
    ]


def test_each_mark_is_matched_to_the_word_with_the_same_whisper_start():
    marks = ca.parse_marks(MARKS)
    table = ca.compare(marks, _rows())
    assert [t["word"] for t in table] == ["Niin,", "Kyllä.", "paradoksi."]
    # ero = oma - arvio: plus tarkoittaa, että arvio on liian aikaisin.
    assert table[0]["whisper_error"] == pytest.approx(-0.118)
    assert table[0]["ctc_error"] == pytest.approx(8.882 - 8.9)
    assert table[1]["ctc_error"] == pytest.approx(49.023 - 49.01)
    # Sana, jota ei kohdistettu, ei saa nollaa vaan tyhjän.
    assert table[2]["ctc_error"] is None
    assert table[2]["whisper_error"] == pytest.approx(0.06)


def test_a_mark_with_no_word_at_its_whisper_time_is_reported_not_dropped():
    marks = [{"group": "sisällä", "word": "x", "whisper": 500.0, "mine": 500.1}]
    table = ca.compare(marks, _rows())
    assert table[0]["matched"] is False
    assert table[0]["whisper_error"] is None


def test_the_summary_counts_hits_within_thirty_milliseconds_per_group():
    marks = ca.parse_marks(MARKS)
    summary = ca.summarize(ca.compare(marks, _rows()))
    after = summary["tauon jälkeen"]
    assert after["n"] == 2
    assert after["whisper_hits"] == 0
    assert after["ctc_hits"] == 2
    assert after["ctc_median"] == pytest.approx(np.median([8.882 - 8.9, 49.023 - 49.01]))
    inside = summary["sisällä"]
    assert inside["n"] == 1 and inside["ctc_n"] == 0 and inside["ctc_median"] is None


def test_the_report_names_the_clock_and_the_sign_convention():
    marks = ca.parse_marks(MARKS)
    text = ca.format_report(ca.compare(marks, _rows()))
    assert "ero = oma - arvio" in text
    assert "Niin," in text and "tauon jälkeen" in text


# --- Komentorivi ---------------------------------------------------------------


def _inputs(tmp_path):
    words = [_word("Niin,", 1.0, 1.4), _word("kyllä", 2.0, 2.4)]
    (tmp_path / "olli.json").write_text(
        json.dumps({"segments": [_segment(words, 1.0, 2.4)]}), encoding="utf-8"
    )
    sf.write(tmp_path / "olli.wav", np.zeros(5 * 48000, dtype=np.float32), 48000)
    (tmp_path / "merkinnat.txt").write_text(
        "TAUON JÄLKEEN\n1.000 Niin, 0:01,040\n", encoding="utf-8"
    )
    return tmp_path / "olli.json", tmp_path / "olli.wav"


def test_the_command_line_writes_a_csv_and_prints_the_comparison(tmp_path, capsys):
    transcript, audio = _inputs(tmp_path)
    out = tmp_path / "ctc.csv"
    code = ca.main(
        [
            str(transcript),
            str(audio),
            "--marks",
            str(tmp_path / "merkinnat.txt"),
            "--csv",
            str(out),
        ],
        aligner=fake_align,
    )
    assert code == 0
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "word,whisper_start,whisper_end,ctc_start,ctc_end"
    assert len(lines) == 3
    printed = capsys.readouterr().out
    assert "Niin" in printed and "ero = oma - arvio" in printed


def test_without_the_neural_aligner_installed_the_error_says_how_to_run_it(
    tmp_path, monkeypatch, capsys
):
    transcript, audio = _inputs(tmp_path)

    def missing():
        raise ca.core.AlignerUnavailable("torchaudio puuttuu")

    monkeypatch.setattr(ca.core, "make_aligner", missing)
    with pytest.raises(SystemExit) as caught:
        ca.main([str(transcript), str(audio)])
    assert caught.value.code not in (0, None)
    assert "uv run" in capsys.readouterr().out
