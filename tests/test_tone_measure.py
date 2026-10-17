"""Sävymittari: kuinka paljon puhujien sävy eroaa, ja kuinka paljon sama puhuja.

Oikeat jaksot ovat vain käyttäjän koneella, joten täällä todistetaan että mittari
mittaa oikein tunnetulla aineistolla: kahden äänen tunnettu 3 dB:n kaltevuusero
luetaan 3 dB:ksi, kohinan peittämä kaista raportoidaan mittaamattomana eikä
nollana, ja taso ei vaikuta tulokseen.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "tone_measure", ROOT / "scripts" / "ab" / "tone_measure.py"
)
tm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tm)

RATE = 32000


def _voice(seconds=20.0, seed=1, floor_db=-80.0, lowpass_hz=None):
    """Puhemainen: purskeita, joiden välissä vain lattiakohina.

    Purskeen spektri laskee 1/f:n mukaan, kuten puheen, jotta jokaisella
    mitattavalla kaistalla on selvä taso kohinan yläpuolella.
    """
    rng = np.random.default_rng(seed)
    n = int(seconds * RATE)
    spectrum = np.fft.rfft(rng.standard_normal(n))
    freqs = np.fft.rfftfreq(n, 1 / RATE)
    spectrum /= np.sqrt(np.maximum(freqs, 50.0))
    if lowpass_hz:
        spectrum[freqs > lowpass_hz] = 0.0
    speech = np.fft.irfft(spectrum, n)
    speech /= np.sqrt(np.mean(speech**2))
    t = np.arange(n) / RATE
    gate = ((t % 1.0) < 0.6).astype(np.float64)  # 0,6 s puhetta, 0,4 s taukoa
    floor = rng.standard_normal(n) * 10 ** (floor_db / 20)
    return (0.1 * speech * gate + floor).astype(np.float32)


def _tilt(audio, above_hz, gain_db):
    """Kaikki ``above_hz``:n yläpuolella ``gain_db`` verran: tunnettu ero."""
    spectrum = np.fft.rfft(audio.astype(np.float64))
    freqs = np.fft.rfftfreq(audio.size, 1 / RATE)
    spectrum[freqs >= above_hz] *= 10 ** (gain_db / 20)
    return np.fft.irfft(spectrum, audio.size).astype(np.float32)


def test_a_known_tilt_reads_as_that_tilt():
    a = _voice()
    b = _tilt(a, 2000.0, 3.0)
    la, lb = tm.band_levels(a, RATE), tm.band_levels(b, RATE)
    assert lb["presence"] - la["presence"] == pytest.approx(3.0, abs=0.4)
    assert lb["air"] - la["air"] == pytest.approx(3.0, abs=0.4)
    assert lb["body"] - la["body"] == pytest.approx(0.0, abs=0.4)
    assert lb["low"] - la["low"] == pytest.approx(0.0, abs=0.4)


def test_levels_are_relative_so_gain_does_not_move_them():
    a = _voice()
    loud = (a * 10 ** (6 / 20)).astype(np.float32)
    la, lb = tm.band_levels(a, RATE), tm.band_levels(loud, RATE)
    for band in tm.BANDS:
        assert lb[band] == pytest.approx(la[band], abs=0.1)


def test_a_band_under_the_noise_is_unmeasured_not_zero():
    # Puhe vain 3 kHz:iin asti ja lattia -50 dB: ilmakaista on pelkkää kohinaa.
    track = _voice(floor_db=-50.0, lowpass_hz=3000.0)
    levels = tm.band_levels(track, RATE)
    assert levels["air"] is None
    assert levels["body"] is not None


def test_silence_has_no_speech_and_nothing_measured():
    silence = (np.random.default_rng(3).standard_normal(RATE * 5) * 1e-4).astype(
        np.float32
    )
    levels = tm.band_levels(silence, RATE)
    assert all(v is None for v in levels.values())


def _hum_voice(hum: bool, seconds=20.0, seed=5):
    """Puhetta, hiljaisuutta ja 250 Hz:n hurinaa, joka on juuri puhekynnyksen alla.

    Hurina on tasoltaan lattian yläpuolella 10 dB eli kynnyksen (12 dB)
    alapuolella, joten se ei ole puhetta, mutta se on rungon kaistalla yhtä
    voimakas kuin puhe. Puhekehyksistä lasketun spektrin pitää olla sama
    hurinan kanssa ja ilman.
    """
    rng = np.random.default_rng(seed)
    n = int(seconds * RATE)
    spectrum = np.fft.rfft(rng.standard_normal(n))
    freqs = np.fft.rfftfreq(n, 1 / RATE)
    spectrum /= np.sqrt(np.maximum(freqs, 50.0))
    speech = np.fft.irfft(spectrum, n)
    speech /= np.sqrt(np.mean(speech**2))
    t = np.arange(n) / RATE
    phase = t % 1.0
    out = 1.8e-3 * speech * (phase < 0.35)  # -55 dBFS, 25 dB lattian yläpuolella
    out += rng.standard_normal(n) * 1e-4  # lattia -80 dBFS
    if hum:
        rms = 1e-4 * 10 ** (10 / 20)
        out += (phase >= 0.60) * rms * np.sqrt(2) * np.sin(2 * np.pi * 250.0 * t)
    return out.astype(np.float32)


def test_the_spectrum_comes_from_speech_frames_only():
    clean = tm.band_levels(_hum_voice(hum=False), RATE)
    hummed = tm.band_levels(_hum_voice(hum=True), RATE)
    assert clean["body"] is not None and hummed["body"] is not None
    assert hummed["body"] == pytest.approx(clean["body"], abs=0.3)


def test_the_speech_mask_follows_the_bursts():
    track = _voice()
    mask = tm.speech_mask(track, RATE)
    # Gridin tasoitus (0,1 s dB-alueella) levittää purskeen reunoja, joten
    # reunat saavat heilua; sisäosan pitää olla oikein: purskeen keskellä
    # kaikki kehykset ovat puhetta ja tauon keskellä yksikään ei ole.
    size, hop = int(tm.FRAME_SEC * RATE), int(tm.HOP_SEC * RATE)
    centre = (np.arange(mask.size) * hop + size / 2) / RATE % 1.0
    assert mask[(centre > 0.1) & (centre < 0.5)].all()
    assert not mask[(centre > 0.7) & (centre < 0.9)].any()
    assert 0.55 < mask.mean() < 0.75


def test_spread_between_speakers_is_per_band_and_skips_the_unmeasured():
    episodes = {
        "e1": {
            "A": {"low": 0.0, "body": 1.0, "presence": 2.0, "air": None},
            "B": {"low": 0.5, "body": 4.0, "presence": 2.0, "air": 3.0},
        },
    }
    spread = tm.between_speakers(episodes)
    assert spread["low"] == pytest.approx(0.5)
    assert spread["body"] == pytest.approx(3.0)
    assert spread["presence"] == pytest.approx(0.0)
    assert spread["air"] is None  # vain yksi mitattu puhuja


def test_spread_of_one_speaker_across_episodes():
    episodes = {
        "e1": {"A": {"low": 0.0, "body": 0.0, "presence": 0.0, "air": 0.0}},
        "e2": {"A": {"low": 1.0, "body": 4.0, "presence": 0.0, "air": None}},
        "e3": {"A": {"low": 0.0, "body": 2.0, "presence": 0.0, "air": 5.0}},
    }
    spread = tm.same_speaker(episodes)
    assert spread["low"] == pytest.approx(1.0)
    assert spread["body"] == pytest.approx(4.0)
    assert spread["air"] == pytest.approx(5.0)


def test_the_verdict_follows_the_rules_written_before_the_numbers():
    between = {"low": 1.0, "body": 3.0, "presence": 3.0, "air": None}
    same = {"low": 0.5, "body": 1.0, "presence": 6.0, "air": 2.0}
    verdict = tm.verdicts(between, same)
    assert verdict["low"].startswith("skip")  # alle 2 dB puhujien välillä
    assert verdict["body"] == "correct toward a common target"
    assert verdict["presence"].startswith(
        "per-show profile"
    )  # sama puhuja heiluu enemmän
    assert verdict["air"] == "not enough data"


def test_the_report_runs_end_to_end_on_files(tmp_path):
    a = _voice(seed=1)
    b = _tilt(_voice(seed=2), 2000.0, 3.0)
    paths = []
    for name, audio in (("a1", a), ("b1", b), ("a2", _tilt(a, 2000.0, 1.0))):
        path = tmp_path / f"{name}.wav"
        sf.write(path, audio, RATE)
        paths.append(path)
    manifest = tmp_path / "tracks.json"
    manifest.write_text(
        json.dumps(
            [
                {"episode": "e1", "speaker": "A", "file": str(paths[0])},
                {"episode": "e1", "speaker": "B", "file": str(paths[1])},
                {"episode": "e2", "speaker": "A", "file": str(paths[2])},
            ]
        ),
        encoding="utf-8",
    )
    text = tm.report(manifest)
    assert "between speakers" in text and "same speaker" in text
    assert "presence" in text and "dB" in text
