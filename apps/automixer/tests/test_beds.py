"""`automixer-beds jakso.nhsx`: musiikkipohjien häivytykset uuteen istuntoon.

Päästä päähän: oikeat WAVit, oikea ffmpeg-verhokäyrä, ja tulos luetaan
takaisin samalla ``nhsx.mix.plan``illa jolla automixer sen soittaa.
"""

from __future__ import annotations

import numpy as np
import pyloudnorm as pyln
import soundfile as sf

from automixer import cli_beds
from nhsx import fades, read
from nhsx.mix import level_at, plan

RATE = 48000


def _speech(seconds, spans):
    x = np.zeros(int(seconds * RATE), dtype=np.float32)
    t = np.arange(x.size) / RATE
    for a, b in spans:
        sl = slice(int(a * RATE), int(b * RATE))
        x[sl] = 0.3 * np.sin(2 * np.pi * 180 * t[sl])
    rng = np.random.default_rng(1)
    return x + rng.normal(0, 1e-4, x.size).astype(np.float32)


def _music(seconds, level=0.1):
    rng = np.random.default_rng(2)
    return rng.normal(0, level, (int(seconds * RATE), 2)).astype(np.float32)


def _write(tmp_path, music_name="VIKIS MID BED.wav", region_extra="",
           spans=((0, 10), (25, 40))):
    sf.write(tmp_path / "olli.wav", _speech(45, spans), RATE)
    sf.write(tmp_path / music_name, _music(30), RATE)
    path = tmp_path / "jakso.nhsx"
    path.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<Session Samplerate="48000">
  <AudioPool Path="" Location="{tmp_path}">
    <File Id="1" Name="olli.wav"/>
    <File Id="2" Name="{music_name}" Channels="2"/>
  </AudioPool>
  <Tracks>
    <Track Name="Olli"><Region Ref="1" Length="45.000" IsMusic="False"/></Track>
    <Track Name="musa"><Region Ref="2" Start="02.000" Length="28.000" {region_extra}/></Track>
  </Tracks>
</Session>""", encoding="utf-8")
    return path


def _run(monkeypatch, path):
    monkeypatch.setattr(cli_beds, "CACHE_DIR", None)
    monkeypatch.setattr("sys.argv", ["automixer-beds", str(path)])
    cli_beds.main()


def _music_clip(path):
    return next(c for c in plan(read(path)).clips if c.speaker == "musa")


def test_bed_gets_the_measured_shape_in_a_new_session(tmp_path, monkeypatch):
    path = _write(tmp_path, region_extra='FadeIn="01.000" FadeOut="02.000"')
    before = path.read_bytes()
    _run(monkeypatch, path)

    assert path.read_bytes() == before
    out = tmp_path / "jakso beds.nhsx"
    clip = _music_clip(out)
    # Vanhat häivytykset pois: ne kertautuisivat uuden käyrän kanssa. Tilalle
    # vain lyhyt alun häivytys, joka peittää ensimmäisen luiskan.
    assert clip.fade_in == fades.START_FADE_IN_S and clip.fade_out == 0.0
    assert clip.ramps

    def db(timeline):
        return 20 * np.log10(max(level_at(clip.ramps, timeline - clip.start), 1e-9))

    # Puhe loppuu 10,0 s: pohja on hiljaa sitä ennen, tasanteella pian sen
    # jälkeen, ja tasanne on mitattu −18,7 LUFS:iin.
    assert db(2.5) < -60
    plateau = db(13.0)
    music = sf.read(tmp_path / "VIKIS MID BED.wav")[0]
    raw = pyln.Meter(RATE).integrated_loudness(music[int(10 * RATE):int(16 * RATE)])
    assert abs((raw + plateau) - cli_beds.PLATEAU_LUFS) < 0.6
    # Ja pois ennen kuin Olli jatkaa 25,0 s.
    assert db(24.5) < plateau - 30

    speech = next(c for c in plan(read(out)).clips if c.speaker == "Olli")
    assert speech.ramps == ()


def test_intro_bed_plays_under_the_cold_open(tmp_path, monkeypatch):
    path = _write(tmp_path, music_name="VIKIS INTRO BED.wav")
    _run(monkeypatch, path)
    clip = _music_clip(tmp_path / "jakso beds.nhsx")
    under = 20 * np.log10(level_at(clip.ramps, 5.0 - clip.start))
    plateau = 20 * np.log10(level_at(clip.ramps, 13.0 - clip.start))
    assert abs((under - plateau) - -12.0) < 1.0


def test_existing_output_is_not_overwritten(tmp_path, monkeypatch):
    path = _write(tmp_path)
    (tmp_path / "jakso beds.nhsx").write_text("previous run")
    _run(monkeypatch, path)
    assert (tmp_path / "jakso beds.nhsx").read_text() == "previous run"
    assert (tmp_path / "jakso beds v2.nhsx").exists()


def test_bed_without_a_pause_is_left_alone_and_said(tmp_path, monkeypatch, capsys):
    # Puhetta koko ajan, lauseiden välissä sekunnin taukoja. Puolet ajasta
    # taukoa, koska kynnys on raidan oman pohjan yllä (20. persentiili):
    # raita joka ei koskaan vaikene ei näytä pohjaansa.
    talk = [(a, a + 1.0) for a in np.arange(0, 45, 2.0)]
    path = _write(tmp_path, spans=talk)
    _run(monkeypatch, path)
    assert "no pause" in capsys.readouterr().out
    assert _music_clip(tmp_path / "jakso beds.nhsx").ramps == ()


def test_the_plateau_is_measured_with_the_shared_meter(tmp_path):
    from automixer import cli_beds
    from speechmix.meter import Meter

    rng = np.random.default_rng(4)
    music = (0.1 * rng.standard_normal((RATE * 8, 2))).astype(np.float32)
    sf.write(tmp_path / "bed.wav", music, RATE, subtype="FLOAT")
    curve = [(0.0, -60.0), (1.0, 0.0), (5.0, 0.0), (6.0, -60.0)]
    got = cli_beds._plateau_gain(str(tmp_path / "bed.wav"), 0.0, curve)
    want = cli_beds.PLATEAU_LUFS - Meter(RATE).integrated_loudness(music[RATE:5 * RATE])
    assert abs(got - want) < 1e-6
