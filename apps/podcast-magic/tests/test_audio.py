"""Äänen purku ei anna istunnosta tullutta polkua ffmpegin komentoriville."""

import math
import struct
import subprocess
import wave
from pathlib import Path
from types import SimpleNamespace

import numpy as np
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
    assert command[command.index("-protocol_whitelist") + 1] == "pipe,fd"


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



# ---------------------------------------------------------------------------
# Oikea ffmpeg. Yllä oleva testi korvaa ``subprocess.run``in, joten se ei
# huomannut, että ``-protocol_whitelist pipe`` hylkäsi koko syötteen:
# ``-i -`` avautuu ffmpegissä ``fd``-protokollana (``Protocol 'fd' not on
# whitelist 'pipe'!``, ffmpeg 6.1.1), ja jokainen purku päättyi virheeseen.
# Ei ohitusta: ffmpeg on kummallakin CI-ajurilla, ja ohittunut testi on
# vihreä testi. Jos ffmpegiä ei ole, ``get_binary_path`` kaataa testin.
# ---------------------------------------------------------------------------


def _wav(path: Path, samples: list[int], rate: int = 16000) -> None:
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def test_decode_pcm_decodes_a_real_wav_exactly(tmp_path):
    samples = [int(8000 * math.sin(2 * math.pi * 440 * i / 16000)) for i in range(16000)]
    source = tmp_path / "ääni 1.wav"
    _wav(source, samples)

    decoded = audio.decode_pcm(source)

    assert decoded.dtype == np.int16
    assert np.array_equal(decoded, np.array(samples, dtype=np.int16))


def test_decode_pcm_decodes_an_m4a_whose_index_is_at_the_end(tmp_path):
    """Putkesta ei voi hakea taaksepäin, ja MP4:n hakemisto on usein lopussa."""
    wav = tmp_path / "lähde.wav"
    _wav(wav, [int(8000 * math.sin(2 * math.pi * 330 * i / 16000)) for i in range(48000)])
    source = tmp_path / "jakso.m4a"
    subprocess.run(
        [audio.get_binary_path("ffmpeg"), "-loglevel", "error", "-y", "-i", str(wav),
         "-c:a", "aac", "-f", "mp4", str(source)],
        check=True,
    )

    decoded = audio.decode_pcm(source)

    # AAC lisää alkuun ja loppuun täytettä: pituus on kolme sekuntia ± yksi ruutu (2048).
    assert abs(len(decoded) - 48000) <= 2048


def test_decode_pcm_does_not_follow_a_reference_inside_the_file(tmp_path):
    """Tiedoston sisältä viitattu toinen tiedosto ei saa purkautua mukaan.

    ``ffconcat``-skripti on tiedosto, joka käskee ffmpegiä lukemaan toisen. Polun
    kautta ffmpeg seuraisi viitettä (mitattu: 32000 tavua ``real.wav``ista);
    putken kautta se ei voi, ja se oli koko tämän suojan tarkoitus.
    """
    _wav(tmp_path / "real.wav", [1000] * 16000)
    evil = tmp_path / "evil.wav"
    evil.write_text("ffconcat version 1.0\nfile 'real.wav'\n", encoding="utf-8")

    with pytest.raises(audio.DecodeError):
        audio.decode_pcm(evil)
