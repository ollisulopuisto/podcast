from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from types import ModuleType

from colabtranscribe import orukeet
from colabtranscribe.options import RunOptions


def test_orukeet_transcribes_with_native_runtime_and_ctc_alignment(
    monkeypatch, tmp_path
):
    receipt = tmp_path / "installation.json"
    receipt.write_text(
        json.dumps({"model": "model.onnx", "runtime": "metal", "device": "mps"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(orukeet, "_receipt_path", lambda: receipt)

    class Engine:
        def __init__(self, model, runtime, device):
            assert (model, runtime, device) == ("model.onnx", "metal", "mps")

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def transcribe(self, path):
            assert path.endswith(".wav")
            return {
                "text": "Moi maailma",
                "language": "fi",
                "segments": [
                    {"start": 0.2, "end": 1.0, "text": "Moi maailma"}
                ],
            }

    fake_package = ModuleType("orukeet")
    fake_package.Orukeet = Engine
    monkeypatch.setitem(sys.modules, "orukeet", fake_package)

    @contextmanager
    def fake_wav_file(_path):
        yield tmp_path / "converted.wav"

    monkeypatch.setattr(orukeet, "_wav_file", fake_wav_file)

    monkeypatch.setattr(orukeet, "_decode", lambda _path: "audio")
    monkeypatch.setattr(orukeet, "_aligner", lambda: "aligner")
    monkeypatch.setattr(
        orukeet,
        "_align_segments",
        lambda segments, _audio, _aligner, errors: [
            {"word": "Moi", "start": 0.25, "end": 0.48},
            {"word": "maailma", "start": 0.51, "end": 0.92},
        ],
    )

    result = orukeet.transcribe_file(tmp_path / "puhe.wav")

    assert result == {
        "text": "Moi maailma",
        "language": "fi",
        "segments": [
            {
                "words": [
                    {"word": "Moi", "start": 0.25, "end": 0.48},
                    {"word": "maailma", "start": 0.51, "end": 0.92},
                ]
            }
        ],
        "alignment_errors": [],
    }


def test_orukeet_writes_ctc_timed_words(monkeypatch, tmp_path):
    audio = tmp_path / "puhe.wav"
    audio.write_bytes(b"audio")
    options = RunOptions(source="audio", backend="orukeet", output_dir=str(tmp_path / "out"))
    monkeypatch.setattr(orukeet, "is_available", lambda: (True, ""))
    monkeypatch.setattr(
        orukeet,
        "transcribe_file",
        lambda _path: {
            "text": "Moi maailma",
            "segments": [
                {
                    "words": [
                        {"word": "Moi", "start": 0.25, "end": 0.48},
                        {"word": "maailma", "start": 0.51, "end": 0.92},
                    ]
                }
            ],
        },
    )

    assert orukeet.run_audio_mode_orukeet(
        options, [str(audio)], False, lambda _message: None
    ) == 0
    result = json.loads((tmp_path / "out" / "puhe.words.json").read_text())
    assert result["timing"] == "orukeet-ctc"
    assert result["words"] == [
        {"w": "Moi", "s": 0.25, "e": 0.48},
        {"w": "maailma", "s": 0.51, "e": 0.92},
    ]
