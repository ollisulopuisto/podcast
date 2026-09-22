"""Hindenburgin istunto automixerin syötteeksi.

Editointi tehdään Hindenburgissa, miksaus täällä. Tämä testaa sen rajan:
mitä istunnosta otetaan (leikkaukset, häivytykset, alueiden keskinäinen
taso) ja mitä ei (raidan fader, musiikin oma taso — se sovitetaan).
"""

from __future__ import annotations

import numpy as np
import pyloudnorm as pyln
import soundfile as sf

from automixer import session

RATE = 48000


def _tone(seconds, hz, level, channels=1):
    t = np.arange(int(seconds * RATE)) / RATE
    x = (level * np.sin(2 * np.pi * hz * t)).astype(np.float32)
    return x if channels == 1 else np.stack([x, x], axis=1)


def _write_session(tmp_path):
    sf.write(tmp_path / "olli.wav", _tone(20, 150, 0.3), RATE)
    sf.write(tmp_path / "tunnari.wav", _tone(6, 440, 0.05, channels=2), RATE)
    path = tmp_path / "jakso.nhsx"
    path.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<Session Samplerate="48000">
  <AudioPool Path="" Location="{tmp_path}">
    <File Id="1" Name="olli.wav"/>
    <File Id="2" Name="tunnari.wav" Channels="2"/>
  </AudioPool>
  <Tracks>
    <Track Name="olli" Volume="-10">
      <Region Ref="1" Start="02.000" Length="03.000" Offset="00.000" FadeIn="01.000"/>
      <Region Ref="1" Start="06.000" Length="03.000" Offset="05.000" ClipGain="-6"/>
      <Region Ref="1" Start="10.000" Length="03.000" Offset="10.000" Muted="True"/>
    </Track>
    <Track Name="musa" Volume="-17.5">
      <Region Ref="2" Start="14.000" Length="05.000" Offset="00.000" ClipGain="-20"/>
    </Track>
  </Tracks>
</Session>""", encoding="utf-8")
    return path


def _rms_db(x):
    return 20 * np.log10(np.sqrt(np.mean(np.square(x))) + 1e-12)


def test_edits_fades_and_clip_gain_come_from_the_session(tmp_path):
    loaded = session.load(_write_session(tmp_path), tmp_path / "work")
    speech = [t for t in loaded.tracks if t["type"] == "speech"]
    assert [t["name"] for t in speech] == ["olli"]
    audio, rate = sf.read(speech[0]["path"])
    assert rate == RATE and audio.ndim == 1


    def at(a, b):
        return audio[int(a * RATE):int(b * RATE)]

    # Leikkaukset: hiljaista alueiden välissä, mykistetty alue pois.
    assert np.abs(at(0, 1.9)).max() == 0.0
    assert np.abs(at(10, 13)).max() == 0.0
    # Häivytys hiljaisuudesta: alku hiljaa, sekunnin jälkeen täysi.
    assert _rms_db(at(2.0, 2.1)) < _rms_db(at(3.5, 4.5)) - 12
    # Alueiden keskinäinen taso säilyy (ClipGain -6), raidan fader ei.
    assert abs(_rms_db(at(3.5, 4.5)) - _rms_db(at(6.5, 8.5)) - 6.0) < 0.1
    assert abs(_rms_db(at(3.5, 4.5)) - _rms_db(_tone(1, 150, 0.3))) < 0.1


def test_music_is_found_and_its_level_is_matched_to_speech(tmp_path):
    loaded = session.load(_write_session(tmp_path), tmp_path / "work")
    music = [t for t in loaded.tracks if t["type"] == "music"]
    assert [t["name"] for t in music] == ["musa"]
    audio, _ = sf.read(music[0]["path"])
    assert audio.ndim == 2
    body = audio[int(14.5 * RATE):int(18.5 * RATE)]
    lufs = pyln.Meter(RATE).integrated_loudness(body)
    assert abs(lufs - session.MUSIC_LUFS) < 0.5


def test_the_cli_mixes_a_session_to_the_target(tmp_path, monkeypatch):
    """`automixer jakso.nhsx`: raidat istunnosta, musiikin taso jo
    sovitettu (ei uutta normalisointia -30:een eikä automaattista
    duckingia — häivytykset tehtiin Hindenburgissa), tulos istunnon
    viereen."""
    from automixer import cli_mix

    path = _write_session(tmp_path)
    seen = []
    original = cli_mix.Mixer

    class Spy(original):
        def __init__(self, config):
            seen.append(config)
            super().__init__(config)

    monkeypatch.setattr(cli_mix, "Mixer", Spy)
    monkeypatch.setattr("sys.argv", ["automixer", str(path)])
    cli_mix.main()

    music = seen[0]["buses"]["music"]
    assert music["level_lufs"] is None
    assert not music["carve_enabled"] and not music["duck_enabled"]
    out = tmp_path / "jakso automixer.wav"
    mix, rate = sf.read(out)
    lufs = pyln.Meter(rate).integrated_loudness(mix)
    assert abs(lufs - -16.0) < 0.6
    assert not (tmp_path / "work").exists()


def test_music_is_matched_to_the_speech_reference():
    from automixer import cli_mix

    assert session.MUSIC_LUFS == cli_mix.SPEECH_REFERENCE_LUFS
