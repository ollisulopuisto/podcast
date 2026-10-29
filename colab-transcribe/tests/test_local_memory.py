import sys

import pytest

from colabtranscribe import local_memory, parakeet


@pytest.mark.parametrize("memory,expected", [(None, False), (8*1024**3, False), (16*1024**3-1, False), (16*1024**3, True)])
def test_policy(monkeypatch, memory, expected):
    monkeypatch.setattr(local_memory, "physical_memory", lambda: memory)
    assert local_memory.eligible() is expected

@pytest.mark.parametrize("memory", [None, 8*1024**3])
def test_no_mlx_import_or_model_load_when_refused(monkeypatch, memory):
    monkeypatch.setattr(local_memory, "physical_memory", lambda: memory)
    monkeypatch.setitem(sys.modules, "parakeet_mlx", None)
    with pytest.raises(RuntimeError, match="Colab"):
        parakeet.transcribe_file("absent.wav")


def test_explicit_override_reaches_model_only_when_requested(monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace

    monkeypatch.setattr(parakeet, "local_inference_slot", nullcontext)
    monkeypatch.setattr(local_memory, "physical_memory", lambda: 8 * 1024**3)
    calls = []
    def load(name):
        calls.append(name)
        raise RuntimeError("fixture model reached")
    monkeypatch.setitem(sys.modules, "parakeet_mlx", SimpleNamespace(from_pretrained=load))
    with pytest.raises(RuntimeError, match="fixture model reached"):
        parakeet.transcribe_file("fixture.wav", allow_low_memory=True)
    assert len(calls) == 1

def test_override_not_read_from_environment(monkeypatch):
    from colabtranscribe import __main__ as cli
    monkeypatch.setenv("COLAB_TRANSCRIBE_ALLOW_LOW_MEMORY", "1")
    args = cli.build_parser().parse_args(["--audio", "fixture.wav"])
    assert args.allow_low_memory is False

@pytest.mark.parametrize("memory", [None, 8 * 1024**3])
def test_override_keeps_chunking_and_does_not_persist(monkeypatch, tmp_path, memory):
    from types import SimpleNamespace

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(local_memory, "physical_memory", lambda: memory)
    calls = []

    class Model:
        def transcribe(self, path, *, chunk_duration, overlap_duration):
            calls.append((path, chunk_duration, overlap_duration))
            return SimpleNamespace(text="", sentences=[])

    monkeypatch.setitem(sys.modules, "parakeet_mlx",
                        SimpleNamespace(from_pretrained=lambda _: Model()))
    parakeet.transcribe_file("fixture.wav", allow_low_memory=True)
    assert calls == [("fixture.wav", 120.0, 15.0)]
    with pytest.raises(RuntimeError, match="Colab"):
        parakeet.transcribe_file("fixture.wav")
    assert len(calls) == 1


def test_memory_override_cannot_bypass_concurrency(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from colabtranscribe.local_inference import local_inference_slot

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(local_memory, "physical_memory", lambda: 8 * 1024**3)
    loads = []
    monkeypatch.setitem(sys.modules, "parakeet_mlx",
                        SimpleNamespace(from_pretrained=lambda name: loads.append(name)))
    with local_inference_slot(), pytest.raises(RuntimeError, match="already running"):
        parakeet.transcribe_file("fixture.wav", allow_low_memory=True)
    assert loads == []
