"""``--txt``: kappaleteksti jokaisesta äänitiedostosta sanatiedoston viereen."""

from __future__ import annotations

import json

import pytest

from colabtranscribe import __main__ as cli
from colabtranscribe import parakeet, transcript
from nhsx.read import Word
from podcastmagic.nhsx.write import paragraphs


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


def test_a_failed_run_removes_a_stale_txt(local, monkeypatch, tmp_path):
    audio = tmp_path / "jakso.wav"
    audio.write_bytes(b"data")
    out = tmp_path / "out"
    out.mkdir()
    (out / "jakso.txt").write_text("old transcript", encoding="utf-8")
    monkeypatch.setattr(parakeet, "is_available", lambda: (False, "ei muistia"))
    assert cli.main(_args(audio, out, "--txt")) == 1
    assert not (out / "jakso.txt").exists()


def test_txt_needs_the_audio_mode(capsys):
    assert cli.main(["--txt"]) == 1
    assert "--txt" in capsys.readouterr().err


def test_an_unwritable_txt_fails_the_run_and_the_last_event_is_an_error(
    local, tmp_path, capsys
):
    audio = tmp_path / "jakso.wav"
    audio.write_bytes(b"data")
    out = tmp_path / "out"
    (out / "jakso.txt").mkdir(parents=True)  # kohde on hakemisto: kirjoitus epäonnistuu
    assert cli.main(_args(audio, out, "--txt", "--events")) == 1
    lines = [
        json.loads(line.split(" ", 1)[1])
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("@@kuulas ")
    ]
    assert lines[-1]["event"] == "error"
    assert lines[-1]["reason"] == "txt_failed"
    assert "done" not in [line["event"] for line in lines]


def test_two_files_with_the_same_stem_are_refused_before_anything_is_written(
    local, tmp_path, capsys
):
    """Sama nimi kirjoittaisi sekä sanatiedoston että .txt:n toisen päälle."""
    one, two = tmp_path / "a" / "jakso.wav", tmp_path / "b" / "jakso.mp3"
    for path in (one, two):
        path.parent.mkdir()
        path.write_bytes(b"data")
    out = tmp_path / "out"
    args = ["--audio", str(one), "--audio", str(two), "--json", str(out), "--txt"]
    assert cli.main([*args, "--backend", "parakeet"]) == 1
    assert "sama nimi" in capsys.readouterr().err
    assert not out.exists()


def test_paragraph_boundaries_match_podcast_magic():
    words = [
        ("Yksi", 0.0, 0.5),
        ("kaksi", 1.7, 2.0),
        ("kolme", 2.1, 2.4),
    ]
    source = [Word(text, start, end - start) for text, start, end in words]
    expected = "\n\n".join(
        f"[{int(group[0].start) // 60:02d}:{int(group[0].start) % 60:02d}] "
        + " ".join(word.text for word in group)
        for group in paragraphs(source)
    ) + "\n"
    assert transcript.paragraph_text(_doc(*words)) == expected


def test_done_event_waits_for_both_files(local, tmp_path, capsys):
    audio = tmp_path / "jakso.wav"
    audio.write_bytes(b"data")
    out = tmp_path / "out"
    assert cli.main(_args(audio, out, "--txt", "--events")) == 0
    lines = [
        json.loads(line.split(" ", 1)[1])
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("@@kuulas ")
    ]
    assert lines[-1]["event"] == "done"
    assert lines[-1]["files"] == [str(out / "jakso.words.json")]
    assert (out / "jakso.txt").read_text(encoding="utf-8") == "[00:00] Moi maailma\n"
