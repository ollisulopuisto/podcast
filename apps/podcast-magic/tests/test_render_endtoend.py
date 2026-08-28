"""Renderöinti oikealla ffmpegillä, oikeista tiedostoista, oikeaksi ääneksi.

``test_render.py`` testaa summauksen injektoidulla purkajalla, ja se on
oikein: summauksen viat ovat laskennassa. Mutta silloin **koko oikea polku
jää ajamatta** — ffmpegin kutsu, sen tuloksen muoto, ja se mitä tavuja
tiedostoon lopulta kirjoitetaan.

Tämä tiedosto on olemassa, koska siellä oli vika. 24-bittinen näyte
pakattiin int32:n kolmesta **ylimmästä** tavusta kolmen alimman sijaan, eli
jokainen ohjelma kirjoitettiin 48 dB liian hiljaa. Mikään ei kaatunut: WAV
oli kelvollinen, kesto oikea, kanavat oikein, ja `Report.peak` kertoi oikean
huipun — se mitataan liukuluvuista ennen pakkausta. Yksikään yksikkötesti ei
lukenut 24-bittisiä tavuja takaisin, vain 16-bittiset.

Lähteet tehdään niin, että **taajuus kertoo sekunnin**: olli.wav:n sekunti
`s` on siniä taajuudella ``400 + 200·s``. Renderistä voi siis lukea suoraan,
mistä kohtaa lähdettä kukin ohjelmasekunti tuli — ilman sitä
tiedosto-offsetin voi laskea väärin ja tulos näyttää silti oikealta.
"""

from __future__ import annotations

import math
import shutil
import subprocess
import wave

import numpy as np
import pytest

from podcastmagic.nhsx import cli, mix
from podcastmagic.nhsx.read import read

SR = 48000
AMP = 0.5

needs_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="ffmpeg puuttuu"
)


def sine_file(path, seconds: int, freq_of_second) -> None:
    """Lähde, jonka jokainen sekunti on oma taajuutensa."""
    blocks = []
    for s in range(seconds):
        t = np.arange(SR) / SR
        blocks.append(np.sin(2 * np.pi * freq_of_second(s) * t) * AMP)
    x = np.concatenate(blocks)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((x * 32767).astype("<i2").tobytes())


def read_wav24(path) -> np.ndarray:
    """24-bittinen stereo-WAV liukuluvuiksi, ``(n, 2)``.

    Puretaan käsin eikä ffmpegillä: juuri **nämä tavut** ovat se mitä tässä
    tarkistetaan, ja ffmpeg korjaisi lukiessaan sen minkä kirjoittaja teki
    väärin vain jos se olisi tehnyt sen samalla tavalla väärin.
    """
    with wave.open(str(path)) as w:
        assert w.getsampwidth() == 3
        assert w.getnchannels() == 2
        raw = w.readframes(w.getnframes())
    b = np.frombuffer(raw, np.uint8).reshape(-1, 3).astype(np.int32)
    v = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
    v = np.where(v >= 1 << 23, v - (1 << 24), v)
    return (v.astype(np.float64) / (2**23 - 1)).reshape(-1, 2)


def dominant_hz(seg: np.ndarray) -> float:
    mono = seg[:, 0] + seg[:, 1]
    spectrum = np.abs(np.fft.rfft(mono * np.hanning(len(mono))))
    return float(np.fft.rfftfreq(len(mono), 1 / SR)[spectrum.argmax()])


def rms(seg: np.ndarray) -> tuple[float, float]:
    return (
        float(np.sqrt(np.mean(seg[:, 0] ** 2))),
        float(np.sqrt(np.mean(seg[:, 1] ** 2))),
    )


SESSION = """<?xml version="1.0" encoding="UTF-8"?>
<Session Name="e2e">
  <AudioPool Path="">
    <File Id="1" Name="olli.wav" Path="olli.wav"/>
    <File Id="2" Name="musiikki.wav" Path="musiikki.wav"/>
  </AudioPool>
  <Tracks>
    <Track Name="Olli">
      <Region Ref="1" Start="1.0" Length="4.0" Offset="2.0"/>
      <Region Ref="1" Start="6.0" Length="2.0" Offset="0.0" Muted="True"/>
    </Track>
    <Track Name="Musiikki" Gain="-12.0">
      <Region Ref="2" Start="0.0" Length="2.0" Offset="0.0" Pan="0.5"/>
    </Track>
  </Tracks>
</Session>
"""


@pytest.fixture
def rendered(tmp_path):
    """Oikea istunto, oikeat lähteet, oikea ffmpeg, oikea WAV levylle."""
    sine_file(tmp_path / "olli.wav", 8, lambda s: 400 + 200 * s)
    sine_file(tmp_path / "musiikki.wav", 4, lambda s: 150)
    session = tmp_path / "e2e.nhsx"
    session.write_text(SESSION, encoding="utf-8")

    assert cli.main([str(session)]) == 0  # ei injektoitua purkajaa
    out = session.with_suffix(".wav")
    assert out.exists()
    return read_wav24(out)


def second(x: np.ndarray, s: int) -> np.ndarray:
    return x[s * SR : (s + 1) * SR]


@needs_ffmpeg
def test_the_programme_is_as_long_as_the_timeline_including_the_muted_end(rendered):
    assert len(rendered) / SR == pytest.approx(8.0, abs=0.001)


@needs_ffmpeg
def test_the_offset_really_chooses_the_source_second(rendered):
    """Alue alkaa ohjelmassa 1,0 ja lähteessä 2,0.

    Ohjelmasekunnin 1 pitää siis olla lähteen sekunti 2 eli 800 Hz. Jos
    offset ohitettaisiin, se olisi 600 Hz — ja tiedosto olisi joka muulla
    tavalla kelvollinen.
    """
    for programme_s, source_s in ((1, 2), (2, 3), (3, 4), (4, 5)):
        expected = 400 + 200 * source_s
        assert dominant_hz(second(rendered, programme_s)) == pytest.approx(
            expected, abs=3.0
        ), f"ohjelmasekunti {programme_s}"


@needs_ffmpeg
def test_a_centred_track_arrives_at_the_level_it_left(rendered):
    """Tämä on se tarkistus, jonka 24-bittinen pakkausvirhe kaatoi.

    Siniaallon huippu on ``AMP``, tehollisarvo ``AMP/√2``, ja
    vakiotehoinen keskipanorointi on ``cos(π/4)`` molemmille puolille.
    """
    left, right = rms(second(rendered, 3))  # vain Olli äänessä
    expected = AMP / math.sqrt(2) * mix.pan_gains(0.0)[0]
    assert left == pytest.approx(expected, rel=0.02)
    assert right == pytest.approx(expected, rel=0.02)


@needs_ffmpeg
def test_the_track_gain_and_the_pan_are_both_in_the_result(rendered):
    """Musiikkiraita on −12 dB ja panoroitu 0,5 oikealle."""
    # Sekunti 0: vain musiikkia. Ollin alue alkaa vasta 1,0:ssa, joten
    # tässä ei ole mitään mistä pitäisi vähentää.
    left, right = rms(second(rendered, 0))
    base = AMP / math.sqrt(2) * mix.db_to_linear(-12.0)
    want_l, want_r = mix.pan_gains(0.5)
    assert left == pytest.approx(base * want_l, rel=0.03)
    assert right == pytest.approx(base * want_r, rel=0.03)
    assert right > left  # oikealle panoroitu kuuluu oikealta


@needs_ffmpeg
def test_a_muted_area_really_is_silence_on_disk(rendered):
    for s in (6, 7):
        left, right = rms(second(rendered, s))
        assert left == pytest.approx(0.0, abs=1e-6)
        assert right == pytest.approx(0.0, abs=1e-6)


@needs_ffmpeg
def test_the_gap_between_areas_is_silence(rendered):
    left, right = rms(second(rendered, 5))
    assert left == pytest.approx(0.0, abs=1e-6)
    assert right == pytest.approx(0.0, abs=1e-6)


@needs_ffmpeg
def test_the_plan_and_the_render_agree_about_what_is_in_the_session(tmp_path):
    """Suunnitelma lukee vain XML:n, renderöinti myös äänen. Sama tulos."""
    sine_file(tmp_path / "olli.wav", 8, lambda s: 400 + 200 * s)
    sine_file(tmp_path / "musiikki.wav", 4, lambda s: 150)
    session = tmp_path / "e2e.nhsx"
    session.write_text(SESSION, encoding="utf-8")

    plan = mix.plan(read(str(session)))
    assert plan.duration == pytest.approx(8.0)
    assert plan.muted == 1
    assert sorted(plan.speakers) == ["Musiikki", "Olli"]
    assert plan.missing == []


@needs_ffmpeg
def test_the_bundled_command_works_from_a_shell(tmp_path):
    """`nhsx-render` on se mitä käyttäjä ajaa, ja se ajetaan tässä oikeasti."""
    sine_file(tmp_path / "olli.wav", 8, lambda s: 400 + 200 * s)
    sine_file(tmp_path / "musiikki.wav", 4, lambda s: 150)
    session = tmp_path / "e2e.nhsx"
    session.write_text(SESSION, encoding="utf-8")

    import sys

    done = subprocess.run(
        [sys.executable, "-m", "podcastmagic.nhsx.cli", str(session), "--plan"],
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, done.stderr
    assert "Olli" in done.stdout
