"""Kahden tallennetun tilan vertailu äänestä: onko niiden malli sama.

Ikkuna voi näyttää Studio 2:ta vaikka tila sisältää Studion (tai päinvastoin),
joten ratkaisu tehdään äänestä: renderöi sama ikkuna molemmilla tiloilla ja
vertaa, ja vertaa tulosta liitännäisen omaan toistokohinaan. Mittari todistetaan
valeliitännäisillä, joiden «malli» on kiinteä sävy- ja kyllästysero.
"""

from __future__ import annotations

import base64
import importlib.util
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "state_compare", ROOT / "scripts" / "ab" / "state_compare.py"
)
sc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sc)

RATE = 16000


def _speechlike(seconds=30.0, seed=1):
    rng = np.random.default_rng(seed)
    n = int(seconds * RATE)
    t = np.arange(n) / RATE
    envelope = 0.15 + 0.12 * np.abs(np.sin(2 * np.pi * 1.7 * t)) ** 3
    return (rng.standard_normal((1, n)) * envelope).astype(np.float32)


class Model:
    """Valeliitännäinen, jonka «malli» on kyllästyksen voimakkuus."""

    def __init__(self, drive, noise=0.0):
        self.parameters = {"mix": object()}
        self.mix = 1.0
        self.drive = drive
        self.noise = noise

    def process(self, audio, rate, reset=True):
        out = np.tanh(self.drive * audio) / self.drive
        if self.noise:
            out = out + np.random.default_rng().standard_normal(out.shape) * self.noise
        return out.astype(np.float32)


def test_two_states_with_the_same_model_are_the_same():
    audio = _speechlike()
    repeat, between = sc.compare_states(
        Model(3.0), Model(3.0), audio, RATE, 14.0, 18.0, 8.0
    )
    assert repeat < -100 and between < -100
    assert sc.verdict(repeat, between).startswith("same")


def test_two_states_with_different_models_differ_far_above_the_repeat_noise():
    audio = _speechlike()
    repeat, between = sc.compare_states(
        Model(3.0), Model(9.0), audio, RATE, 14.0, 18.0, 8.0
    )
    assert between > -40 and repeat < -100
    assert sc.verdict(repeat, between).startswith("different")


def test_a_difference_inside_the_repeat_noise_is_not_called_a_difference():
    audio = _speechlike()
    noisy = Model(3.0, noise=0.02)
    repeat, between = sc.compare_states(
        noisy, Model(3.0, noise=0.02), audio, RATE, 14.0, 18.0, 8.0
    )
    assert repeat > -30
    assert not sc.verdict(repeat, between).startswith("different")


def test_the_byte_difference_counts_and_places_the_changes():
    a = base64.b64encode(bytes(range(20))).decode()
    changed = bytearray(range(20))
    changed[5] = 99
    changed[6] = 98
    b = base64.b64encode(bytes(changed)).decode()
    la, lb, count, where = sc.byte_diff(a, b)
    assert (la, lb, count, where) == (20, 20, 2, [5, 6])


def test_main_reports_the_bytes_the_audio_and_the_verdict(tmp_path, monkeypatch, capsys):
    wav = tmp_path / "jakso.wav"
    sf.write(wav, _speechlike(seconds=40.0)[0], RATE)
    states = {}
    for name, payload in (("a", b"model-a-state"), ("b", b"model-b-state!")):
        path = tmp_path / f"tila-{name}.b64"
        path.write_text(base64.b64encode(payload).decode(), encoding="ascii")
        states[name] = path
    models = {"model-a-state": 3.0, "model-b-state!": 9.0}
    monkeypatch.setattr(
        sc,
        "_load",
        lambda path, state, param, mix: Model(models[base64.b64decode(state).decode()]),
    )
    monkeypatch.setattr(sc, "_mix_param_default", lambda path: "mix")
    code = sc.main(
        [
            str(wav),
            "--plugin",
            "x.vst3",
            "--state",
            str(states["a"]),
            "--state",
            str(states["b"]),
            "--start",
            "20",
            "--seconds",
            "4",
            "--preroll",
            "8",
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "different" in out
    assert "repeat" in out.lower()
    assert "13" in out and "14" in out  # tilojen pituudet tavuina


def test_a_longer_state_counts_its_extra_bytes_as_differences():
    a = base64.b64encode(bytes(10)).decode()
    longer = bytearray(13)
    longer[2] = 1
    b = base64.b64encode(bytes(longer)).decode()
    assert sc.byte_diff(a, b) == (10, 13, 1 + 3, [2])
