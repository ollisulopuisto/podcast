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
    """`automixer jakso.nhsx`: istunto stemeinä levyllä (``stems_mix``),
    tulos istunnon viereen tavoitetasolla, työhakemisto siivottuna."""
    from automixer import cli_mix

    path = _write_session(tmp_path)
    monkeypatch.setattr("sys.argv", ["automixer", str(path)])
    cli_mix.main()

    out = tmp_path / "jakso automixer.wav"
    mix, rate = sf.read(out)
    lufs = pyln.Meter(rate).integrated_loudness(mix)
    assert abs(lufs - -16.0) < 0.6
    assert not list(tmp_path.glob("automixer-*"))


def test_music_is_matched_to_the_speech_reference():
    from automixer import cli_mix

    assert session.MUSIC_LUFS == cli_mix.SPEECH_REFERENCE_LUFS


def test_a_stereo_microphone_is_speech_when_hindenburg_says_so(tmp_path):
    """Stereona tallennettu mikki on puhetta, jos Hindenburg merkitsee sen
    alueet ``IsMusic="False"``. Pelkkä stereoarvaus teki siitä musiikkia:
    se ohitti puheketjun ja sai musiikin tason (vst s13e03, Olli)."""
    sf.write(tmp_path / "olli.wav", _tone(4, 150, 0.3, channels=2), RATE)
    path = tmp_path / "jakso.nhsx"
    path.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<Session Samplerate="48000">
  <AudioPool Path="" Location="{tmp_path}">
    <File Id="1" Name="olli.wav" Channels="2"/>
  </AudioPool>
  <Tracks>
    <Track Name="Olli">
      <Region Ref="1" Start="00.000" Length="04.000" IsMusic="False"/>
    </Track>
  </Tracks>
</Session>""", encoding="utf-8")
    loaded = session.load(path, tmp_path / "work")
    assert [(t["name"], t["type"]) for t in loaded.tracks] == [("Olli", "speech")]
    audio, _ = sf.read(loaded.tracks[0]["path"])
    assert audio.ndim == 1


def _write_faded_session(tmp_path):
    """A bed with automixer-beds' shape: held low, then a full plateau, then a
    fall. The plateau is 12 dB over the hold, so the whole-clip loudness is
    not the plateau's."""
    sf.write(tmp_path / "olli.wav", _tone(20, 150, 0.3), RATE)
    sf.write(tmp_path / "tunnari.wav", _tone(20, 440, 0.05, channels=2), RATE)
    path = tmp_path / "jakso.nhsx"
    path.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<Session Samplerate="48000">
  <AudioPool Path="" Location="{tmp_path}">
    <File Id="1" Name="olli.wav"/>
    <File Id="2" Name="tunnari.wav" Channels="2"/>
  </AudioPool>
  <Tracks>
    <Track Name="olli">
      <Region Ref="1" Start="00.000" Length="20.000" Offset="00.000"/>
    </Track>
    <Track Name="musa" Volume="-7.5">
      <Region Ref="2" Start="00.000" Length="20.000" Offset="00.000">
        <Fade Length="0.010" Gain="-12"/>
        <Fade Start="8.000" Length="1.000" Gain="-2"/>
        <Fade Start="14.000" Length="1.000" Gain="-30"/>
      </Region>
    </Track>
  </Tracks>
</Session>""", encoding="utf-8")
    return path


def test_a_faded_bed_is_matched_at_its_plateau_over_the_speech(tmp_path):
    """The bed's plateau, not its whole-clip loudness, sits at the speech
    reference plus the measured offset. vst s13e03: matching the whole raw clip
    to the speech level put the plateau 11 dB UNDER the processed speech
    (-26.9 vs -16.0 LUFS rendered), where the user's Hindenburg mix has it 7 dB
    OVER (+8.2, +7.1, +7.0 for INTRO, MID, END)."""
    loaded = session.load(_write_faded_session(tmp_path), tmp_path / "work")
    music = next(t for t in loaded.tracks if t["type"] == "music")
    audio, _ = sf.read(music["path"])
    plateau = audio[int(9.5 * RATE):int(13.5 * RATE)]
    lufs = pyln.Meter(RATE).integrated_loudness(plateau)
    assert abs(lufs - (session.MUSIC_LUFS + session.MUSIC_PLATEAU_OVER_SPEECH_DB)) < 0.5
    hold = audio[int(2 * RATE):int(6 * RATE)]
    assert abs(_rms_db(hold) - _rms_db(plateau) - (-12 - -2)) < 0.3


def _noise(seconds, level=0.1, channels=2, seed=2):
    rng = np.random.default_rng(seed)
    return (level * rng.standard_normal((int(seconds * RATE), channels))).astype(np.float32)


def test_beds_are_measured_with_the_shared_meter():
    """pyloudnorm luki 0,042 LU alakanttiin libebur128:aan verrattuna, ja
    ketju ja masterointi mittaavat jo speechmixin mittarilla. Pohjan taso
    sovitetaan samalla, ettei sama ääni mittaudu kahdella tavalla."""
    from speechmix.meter import Meter

    audio = _noise(6.0)
    env = np.ones(len(audio), dtype=np.float32)
    want = 10 ** ((session.MUSIC_LUFS - Meter(RATE).integrated_loudness(audio)) / 20)
    assert abs(session._music_scale(audio, env, RATE) - want) < 1e-9


def test_a_faded_bed_exports_its_duck_depth_from_the_plateau(tmp_path):
    """The carve follows the duck: 0 dB at the plateau, the hold's depth
    (−10 dB under the −2 dB plateau) while ducked."""
    loaded = session.load(_write_faded_session(tmp_path), tmp_path / "work")
    music = next(t for t in loaded.tracks if t["type"] == "music")
    curve = {round(t, 2): db for t, db in music["ducked"]}
    assert abs(curve[11.0]) < 0.1, curve[11.0]
    assert abs(curve[4.0] - -10.0) < 0.2, curve[4.0]
    assert all(db <= 0.0 for db in curve.values())
