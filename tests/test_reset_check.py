"""Reset-koe: onko liitännäisen tulos satunnainen, tilallinen vai toistettava.

Kolme erilaista valeliitännäistä: toistettava (ei muistia, ei kohinaa), satunnainen
(jokaisessa ajossa uusi kohina) ja tilallinen (edellisen kutsun häntä vuotaa seuraavaan,
vaikka ``reset=True``; vain ``reset()`` tyhjentää sen). Päätössääntö on kirjoitettu
ennen oikeaa liitännäistä: kokeen pitää erottaa nämä kolme.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "reset_check", ROOT / "scripts" / "ab" / "reset_check.py"
)
rc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rc)

RATE = 16000


def _speechlike(seconds=120.0, seed=1):
    rng = np.random.default_rng(seed)
    n = int(seconds * RATE)
    t = np.arange(n) / RATE
    envelope = 0.15 + 0.12 * np.abs(np.sin(2 * np.pi * 1.7 * t)) ** 3
    return (rng.standard_normal((1, n)) * envelope).astype(np.float32)


class Steady:
    parameters = {"mix": object()}
    mix = 1.0

    def process(self, audio, rate, reset=True):
        return (np.tanh(3.0 * audio) / 3.0).astype(np.float32)


class Random(Steady):
    def process(self, audio, rate, reset=True):
        out = super().process(audio, rate, reset=reset)
        return (out + np.random.default_rng().standard_normal(out.shape) * 0.02).astype(
            np.float32
        )


class Carry(Steady):
    """Edellisen kutsun häntä vuotaa alkuun; ``reset=True`` ei tyhjennä sitä."""

    def __init__(self):
        self.tail = None

    def reset(self):
        self.tail = None

    def process(self, audio, rate, reset=True):
        out = super().process(audio, rate, reset=reset).copy()
        if self.tail is not None:
            n = min(RATE, out.shape[1])
            out[:, :n] += self.tail[:, :n] * np.linspace(1.0, 0.0, n, dtype=np.float32)
        self.tail = out[:, -RATE:].copy() * 4.0
        return out


def _run(factory):
    audio = _speechlike()
    plugins = [factory() for _ in range(3)]
    return rc.reset_experiment(plugins, audio, RATE, 30.0, 34.0, 0.0, 80.0, 84.0)


def test_a_steady_plugin_is_deterministic():
    result = _run(Steady)
    assert rc.diagnose(result).startswith("deterministic")


def test_a_random_plugin_is_stochastic_whatever_the_history():
    result = _run(Random)
    assert rc.diagnose(result).startswith("stochastic")


def test_a_stateful_plugin_is_carry_over_and_a_reset_cures_it():
    result = _run(Carry)
    assert rc.diagnose(result).startswith("carry-over")
    assert result["after_other"] > -30.0  # muun äänen jälkeen vuoto näkyy
    assert result["after_reset"] < -60.0  # reset() palauttaa kylmän alun


def test_the_experiment_only_needs_three_plugin_instances():
    audio = _speechlike()
    assert (
        len(
            rc.reset_experiment(
                [Steady() for _ in range(3)], audio, RATE, 30.0, 34.0, 8.0, 80.0, 84.0
            )["fresh"]
        )
        == 3
    )


def test_main_prints_the_tables_and_the_diagnosis(tmp_path, monkeypatch, capsys):
    wav = tmp_path / "jakso.wav"
    sf.write(wav, _speechlike(seconds=120.0)[0], RATE)
    monkeypatch.setattr(
        rc,
        "_load",
        lambda path, state, count, param, mix: [Random() for _ in range(count)],
    )
    monkeypatch.setattr(rc, "_mix_param_default", lambda path: "mix")
    code = rc.main(
        [
            str(wav),
            "--plugin",
            "x.vst3",
            "--start",
            "30",
            "--seconds",
            "4",
            "--preroll",
            "8",
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    for text in ("Fresh instances", "Same instance", "After other audio", "stochastic"):
        assert text in out


def test_a_long_preroll_hides_a_short_carry_over():
    """Siksi koe ajetaan esiajalla 0: 8 s esiaika leikkaisi vuodon pois."""
    audio = _speechlike()
    plugins = [Carry() for _ in range(3)]
    result = rc.reset_experiment(plugins, audio, RATE, 30.0, 34.0, 8.0, 80.0, 84.0)
    assert rc.diagnose(result).startswith("deterministic")


def test_levels_that_differ_without_the_carry_over_margin_are_mixed():
    result = {
        "fresh": [-30.0, -30.0, -30.0],
        "repeated": [-35.0, -35.0, -35.0],
        "after_other": -24.0,
        "after_reset": None,
    }
    assert rc.diagnose(result).startswith("mixed")
