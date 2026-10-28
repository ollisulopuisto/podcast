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
    from types import SimpleNamespace
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
