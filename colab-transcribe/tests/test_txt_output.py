"""``--txt``: kappaleteksti jokaisesta äänitiedostosta sanatiedoston viereen."""

from __future__ import annotations

import json

import pytest

from colabtranscribe import __main__ as cli
from colabtranscribe import parakeet, transcript


def _doc(*words):
    return {
        "version": 1,
        "language": "fi",
        "words": [{"w": w, "s": s, "e": e} for w, s, e in words],
    }


def test_words_in_one_breath_make_one_paragraph_with_a_timestamp():
    doc = _doc(("Moi", 0.0, 0.4), ("maailma", 0.5, 0.9))
    assert transcript.paragraph_text(doc) == "[00:00] Moi maailma\n"


def test_a_pause_of_1_2_seconds_starts_a_new_paragraph():
    doc = _doc(("Yksi", 0.0, 0.5), ("kaksi", 1.7, 2.0), ("kolme", 2.1, 2.4))
    assert transcript.paragraph_text(doc) == "[00:00] Yksi\n\n[00:01] kaksi kolme\n"


def test_a_pause_just_under_the_limit_keeps_the_paragraph():
    doc = _doc(("Yksi", 0.0, 0.5), ("kaksi", 1.6, 2.0))
    assert transcript.paragraph_text(doc) == "[00:00] Yksi kaksi\n"


def test_a_paragraph_is_cut_at_80_words():
    words = [(f"s{i}", i * 0.1, i * 0.1 + 0.05) for i in range(81)]
    text = transcript.paragraph_text(_doc(*words))
    first, second = text.strip().split("\n\n")
    assert len(first.split()) == 1 + 80  # aikaleima + 80 sanaa
    assert second.endswith("s80")


def test_the_timestamp_is_minutes_and_seconds():
    doc = _doc(("Myöhään", 3725.0, 3725.5))
    assert transcript.paragraph_text(doc) == "[62:05] Myöhään\n"


def test_no_words_gives_an_empty_text():
    assert transcript.paragraph_text(_doc()) == ""


def test_malformed_word_entries_are_skipped():
    doc = {
        "words": [
            {"w": "ok", "s": 0.0, "e": 0.2},
            {"s": 1},
            "x",
            {"w": " ", "s": 2, "e": 3},
        ]
    }
    assert transcript.paragraph_text(doc) == "[00:00] ok\n"


@pytest.fixture
def local(monkeypatch):
    raw = {
        "text": "Moi maailma",
        "segments": [
            {
                "words": [
                    {"word": "Moi", "start": 0.1, "end": 0.4},
                    {"word": "maailma", "start": 0.5, "end": 0.95},
                ]
            }
        ],
    }
    monkeypatch.setattr(parakeet, "is_available", lambda: (True, ""))
    monkeypatch.setattr(parakeet, "transcribe_file", lambda _path, **_: raw)


def _args(audio, out, *extra):
    return ["--audio", str(audio), "--json", str(out), "--backend", "parakeet", *extra]


def test_the_flag_writes_a_txt_next_to_each_words_file(local, tmp_path):
    audio = tmp_path / "jakso.wav"
    audio.write_bytes(b"data")
    out = tmp_path / "out"
    assert cli.main(_args(audio, out, "--txt")) == 0
    assert (out / "jakso.txt").read_text(encoding="utf-8") == "[00:00] Moi maailma\n"
    assert json.loads((out / "jakso.words.json").read_text(encoding="utf-8"))["words"]


def test_without_the_flag_no_txt_is_written(local, tmp_path):
    audio = tmp_path / "jakso.wav"
    audio.write_bytes(b"data")
    out = tmp_path / "out"
    assert cli.main(_args(audio, out)) == 0
    assert not (out / "jakso.txt").exists()


def test_a_failed_run_writes_no_txt(local, monkeypatch, tmp_path):
    audio = tmp_path / "jakso.wav"
    audio.write_bytes(b"data")
    out = tmp_path / "out"
    monkeypatch.setattr(parakeet, "is_available", lambda: (False, "ei muistia"))
    assert cli.main(_args(audio, out, "--txt")) == 1
    assert not (out / "jakso.txt").exists()


def test_txt_needs_the_audio_mode(capsys):
    assert cli.main(["--txt"]) == 1
    assert "--txt" in capsys.readouterr().err
