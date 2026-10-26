"""Testit paikalliselle Parakeet MLX -litterointitaustalle (--backend parakeet).

Varmistaa valitsimet, kuivasuunnitelman, sanamuunnokset, Kuulas-sopimuksen
toteutumisen sekä edistymis- ja tapahtumatulosteet ilman Colab-kutsuja.
"""

from __future__ import annotations

import json

import pytest

from colabtranscribe import __main__ as cli
from colabtranscribe import parakeet
from colabtranscribe.options import BACKENDS, RunOptions


def test_backend_choices_contain_colab_and_parakeet():
    assert "colab" in BACKENDS
    assert "parakeet" in BACKENDS
    assert "orukeet" in BACKENDS


def test_default_backend_is_colab():
    options = RunOptions()
    assert options.backend == "colab"


def test_unknown_backend_is_rejected():
    with pytest.raises(ValueError, match="backend"):
        RunOptions(source="audio", backend="whispercpp")


def test_parakeet_backend_rejects_non_audio_source():
    with pytest.raises(ValueError, match="vain pelkän äänen tilaa"):
        RunOptions(source="tracks", backend="parakeet")


def test_empty_parakeet_model_is_rejected():
    with pytest.raises(ValueError, match="parakeet_model"):
        RunOptions(source="audio", backend="parakeet", parakeet_model="")


def test_orukeet_backend_dry_run_prints_local_commands(tmp_path, capsys):
    audio = tmp_path / "haastattelu.wav"
    audio.write_bytes(b"data")
    out = tmp_path / "sanat"

    code = cli.main(
        [
            "--audio",
            str(audio),
            "--json",
            str(out),
            "--backend",
            "orukeet",
            "--dry-run",
        ]
    )

    assert code == 0
    stdout = capsys.readouterr().out
    assert "parakeet-mlx" in stdout
    assert "haastattelu.wav" in stdout
    assert "haastattelu.words.json" in stdout
    assert "colab new" not in stdout


def test_parakeet_backend_dry_run_prints_local_commands(tmp_path, capsys):
    audio = tmp_path / "haastattelu.wav"
    audio.write_bytes(b"data")
    out = tmp_path / "sanat"

    code = cli.main(
        [
            "--audio",
            str(audio),
            "--json",
            str(out),
            "--backend",
            "parakeet",
            "--dry-run",
        ]
    )

    assert code == 0
    stdout = capsys.readouterr().out
    assert "parakeet-mlx" in stdout
    assert "haastattelu.wav" in stdout
    assert "haastattelu.words.json" in stdout
    # Ei Colab-komentoja kuivasuunnitelmassa
    assert "colab new" not in stdout
    assert "colab upload" not in stdout
    assert "pipeline.py" not in stdout


def test_parakeet_is_available_returns_boolean_and_message():
    available, msg = parakeet.is_available()
    assert isinstance(available, bool)
    assert isinstance(msg, str)
    if not available:
        assert msg  # jos ei käytettävissä, syy on aina kerrottava


def test_parakeet_is_available_rejects_non_darwin(monkeypatch):
    monkeypatch.setattr(parakeet.platform, "system", lambda: "Linux")
    available, msg = parakeet.is_available()
    assert available is False
    assert "macOS" in msg


def test_parakeet_is_available_rejects_non_arm64(monkeypatch):
    monkeypatch.setattr(parakeet.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(parakeet.platform, "machine", lambda: "x86_64")
    available, msg = parakeet.is_available()
    assert available is False
    assert "arm64" in msg


def test_parakeet_transcribe_file_mapping(monkeypatch, tmp_path):
    class FakeToken:
        def __init__(self, text, start, end):
            self.text = text
            self.start = start
            self.end = end

    class FakeSentence:
        def __init__(self, tokens):
            self.tokens = tokens

    class FakeResult:
        def __init__(self):
            self.text = "Tervehdys kaikille"
            self.sentences = [
                FakeSentence(
                    [
                        FakeToken(" Terve", 0.12, 0.40),
                        FakeToken("hdys", 0.40, 0.65),
                        FakeToken(" kaikille", 0.70, 1.25),
                        FakeToken(",", 1.25, 1.30),
                    ]
                )
            ]

    class FakeModel:
        def transcribe(self, _path):
            return FakeResult()

    import sys
    from types import ModuleType

    fake_module = ModuleType("parakeet_mlx")
    fake_module.from_pretrained = lambda _name: FakeModel()
    monkeypatch.setitem(sys.modules, "parakeet_mlx", fake_module)

    dummy_wav = tmp_path / "test.wav"
    dummy_wav.write_bytes(b"RIFFdummyWAVE")

    raw = parakeet.transcribe_file(dummy_wav)
    assert raw["text"] == "Tervehdys kaikille"
    assert len(raw["segments"]) == 1
    words = raw["segments"][0]["words"]
    assert words == [
        {"word": "Tervehdys", "start": 0.12, "end": 0.65},
        {"word": "kaikille,", "start": 0.70, "end": 1.30},
    ]


def test_run_audio_mode_parakeet_writes_words_json(monkeypatch, tmp_path, capsys):
    audio = tmp_path / "jakso.wav"
    audio.write_bytes(b"data")
    out = tmp_path / "sanat"

    fake_raw = {
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
    monkeypatch.setattr(parakeet, "transcribe_file", lambda _path, **_: fake_raw)

    code = cli.main(
        [
            "--audio",
            str(audio),
            "--json",
            str(out),
            "--backend",
            "parakeet",
            "--language",
            "fi",
        ]
    )

    assert code == 0
    words_file = out / "jakso.words.json"
    assert words_file.is_file()

    doc = json.loads(words_file.read_text(encoding="utf-8"))
    assert doc == {
        "version": 1,
        "timing": "parakeet",
        "language": "fi",
        "rejected": 0,
        "words": [
            {"w": "Moi", "s": 0.1, "e": 0.4},
            {"w": "maailma", "s": 0.5, "e": 0.95},
        ],
    }

    stdout = capsys.readouterr().out
    assert "Valmiit sanatiedostot (1):" in stdout
    assert "jakso.words.json" in stdout


def test_parakeet_backend_progress_and_events(monkeypatch, tmp_path, capsys):
    audio = tmp_path / "puhe.wav"
    audio.write_bytes(b"data")
    out = tmp_path / "out"

    fake_raw = {
        "text": "Koe",
        "segments": [{"words": [{"word": "Koe", "start": 0.0, "end": 0.5}]}],
    }

    monkeypatch.setattr(parakeet, "is_available", lambda: (True, ""))
    monkeypatch.setattr(parakeet, "transcribe_file", lambda _path, **_: fake_raw)

    code = cli.main(
        [
            "--audio",
            str(audio),
            "--json",
            str(out),
            "--backend",
            "parakeet",
            "--progress",
            "--events",
        ]
    )

    assert code == 0
    lines = capsys.readouterr().out.splitlines()

    # Progress-rivit ovat muotoa PROGRESS <0-100> <viesti>
    progress_lines = [line for line in lines if line.startswith("PROGRESS ")]
    assert len(progress_lines) >= 2
    assert progress_lines[-1] == "PROGRESS 100 Valmis."

    # Kuulas-tapahtumat ovat muotoa @@kuulas <json>
    event_lines = [
        json.loads(line.removeprefix("@@kuulas "))
        for line in lines
        if line.startswith("@@kuulas ")
    ]
    event_types = [e.get("event") for e in event_lines]
    assert "session" in event_types
    assert "stage" in event_types
    assert "done" in event_types
    session_ev = next(e for e in event_lines if e.get("event") == "session")
    assert session_ev.get("backend") == "parakeet"
    assert session_ev.get("state") == "local"


def test_parakeet_backend_missing_audio_fails(tmp_path, capsys):
    code = cli.main(
        [
            "--audio",
            str(tmp_path / "puuttuu.wav"),
            "--json",
            str(tmp_path / "out"),
            "--backend",
            "parakeet",
        ]
    )
    assert code == 1
    err = capsys.readouterr().err + capsys.readouterr().out
    assert "puuttuu.wav" in err or code == 1


def test_parakeet_backend_unavailable_fails_cleanly(monkeypatch, tmp_path, capsys):
    audio = tmp_path / "puhe.wav"
    audio.write_bytes(b"data")
    out = tmp_path / "out"

    monkeypatch.setattr(
        parakeet, "is_available", lambda: (False, "parakeet-mlx ei ole asennettu")
    )

    code = cli.main(
        [
            "--audio",
            str(audio),
            "--json",
            str(out),
            "--backend",
            "parakeet",
        ]
    )

    assert code == 1
    stdout = capsys.readouterr().out
    assert "parakeet-mlx ei ole asennettu" in stdout
