"""Tiedostojen tekniset tiedot. Puuttuva tiedosto ei ole virhe."""

import os

from conftest import needs_ffmpeg

from autoraffkat import probe


def test_missing_file_gives_nothing(tmp_path):
    assert probe.info(str(tmp_path / "ei-ole.wav")) == {}
    assert probe.info("") == {}


def test_fps_is_read_as_a_fraction():
    assert probe._fps("25/1") == 25.0
    assert probe._fps("30000/1001") == 30000 / 1001
    assert probe._fps("0/0") is None
    assert probe._fps(None) is None


@needs_ffmpeg
def test_audio_facts(fixture_dir):
    path = fixture_dir / "MIC_A.wav"
    if not path.exists():
        import pytest

        pytest.skip("fixturen mediaa ei ole")
    facts = probe.info(str(path))
    assert facts["audio"]["channels"] == 1
    assert facts["audio"]["rate"] == 48000
    assert facts["size"] == os.path.getsize(path)
    assert facts["duration"] > 0


@needs_ffmpeg
def test_result_is_cached(fixture_dir):
    """Tila haetaan sekunnin välein; joka haku ei saa ajaa ffprobea."""
    path = fixture_dir / "MIC_A.wav"
    if not path.exists():
        import pytest

        pytest.skip("fixturen mediaa ei ole")
    first = probe.info(str(path))
    assert probe.info(str(path)) is first

def test_loudness_rejects_an_infinite_measurement(tmp_path, monkeypatch):
    """Hiljainen tiedosto: loudnorm raportoi -inf LUFS, mikä ei ole taso
    vaan mittauksen puute. Paluun on oltava None, jotta tasonsovitin ei
    muutu äärettömäksi vahvistukseksi."""
    import subprocess

    from autoraffkat import probe

    media = tmp_path / "hiljainen.wav"
    media.write_bytes(b"wav")

    class Done:
        returncode = 0
        stdout = ""
        stderr = '[Parsed_loudnorm_0]\n{\n\t"input_i" : "-inf"\n}\n'

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Done())
    monkeypatch.setattr(probe, "get_binary_path", lambda name: "/usr/bin/ffmpeg")
    monkeypatch.setattr(probe, "_cache", {})

    assert probe.loudness(str(media)) is None
