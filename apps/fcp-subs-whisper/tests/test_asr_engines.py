import sys
import types

from fcp_subs_whisper.main import transcribe_orukeet, transcribe_parakeet_ultra


def test_parakeet_ultra_returns_segment_timestamps(monkeypatch):
    calls = {}

    class Model:
        def transcribe(self, **kwargs):
            calls.update(kwargs)
            return {"segments": [{"start": 1.0, "end": 2.0, "text": "Hei"}]}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

    monkeypatch.setitem(sys.modules, "moondream", types.SimpleNamespace(
        photon=lambda model: (calls.update(model=model) or Model())
    ))
    assert transcribe_parakeet_ultra("audio.wav") == [
        {"start": 1.0, "end": 2.0, "text": "Hei"}
    ]
    assert calls["model"] == "moondream/parakeet-ultra"
    assert calls["timestamps"] == "segment"


def test_orukeet_uses_installation_receipt_and_segment_timestamps(monkeypatch, tmp_path):
    import json

    receipt = tmp_path / "installation.json"
    receipt.write_text(json.dumps({"model": "m", "runtime": "r", "device": "cpu"}))
    monkeypatch.setenv("ORUKEET_INSTALLATION", str(receipt))
    calls = {}

    class Model:
        def __init__(self, model, runtime, device):
            calls.update(model=model, runtime=runtime, device=device)

        def transcribe(self, path):
            calls["path"] = path
            return {"segments": [{"start": 1.0, "end": 2.0, "text": "Hei"}]}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

    monkeypatch.setitem(sys.modules, "orukeet", types.SimpleNamespace(Orukeet=Model))
    assert transcribe_orukeet("audio.wav") == [
        {"start": 1.0, "end": 2.0, "text": "Hei"}
    ]
    assert calls["model"] == "m" and calls["device"] == "cpu"
