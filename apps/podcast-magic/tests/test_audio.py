"""Äänen purku ei anna istunnosta tullutta polkua ffmpegin komentoriville."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from podcastmagic import audio


def test_decode_pcm_uses_stdin_as_the_only_ffmpeg_input(tmp_path, monkeypatch):
    source = tmp_path / "audio with spaces.wav"
    source.write_bytes(b"fake audio")
    seen = {}

    def run(command, **kwargs):
        seen["command"] = command
        seen["stdin"] = kwargs.get("stdin")
        return SimpleNamespace(stdout=b"\x01\x00", stderr=b"")

    monkeypatch.setattr(audio, "get_binary_path", lambda _name: "/bin/ffmpeg")
    monkeypatch.setattr(audio.subprocess, "run", run)

    audio.decode_pcm(source)

    command = seen["command"]
    assert command[command.index("-i") + 1] == "-"
    assert str(source) not in command
    assert Path(seen["stdin"].name).resolve() == source.resolve()
    assert command[command.index("-protocol_whitelist") + 1] == "pipe"


def test_decode_pcm_rejects_empty_and_null_byte_paths():
    with pytest.raises(audio.DecodeError, match="epäkelpo tiedostopolku"):
        audio.decode_pcm("")
    with pytest.raises(audio.DecodeError, match="epäkelpo tiedostopolku"):
        audio.decode_pcm("audio\0.wav")


def test_decode_pcm_rejects_unsupported_audio_extension(tmp_path):
    evil = tmp_path / "not_audio.exe"
    evil.write_bytes(b"MZ...")
    with pytest.raises(audio.DecodeError, match="ei tuettu äänitiedosto"):
        audio.decode_pcm(evil)


def test_decode_pcm_rejects_missing_file(tmp_path):
    missing = tmp_path / "puuttuu.wav"
    with pytest.raises(audio.DecodeError, match="tiedostoa ei löydy"):
        audio.decode_pcm(missing)

