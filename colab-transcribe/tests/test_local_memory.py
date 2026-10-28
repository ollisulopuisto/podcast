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

