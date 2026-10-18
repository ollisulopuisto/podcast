"""floormatch-ajuri: yhteiset tauot, oma puhetaso ja raportti.

``speechmix.floormatch`` on toisen tekemä ja vain käyttäjän koneella, joten ajuri saa
moduulin parametrina ja täällä sen tilalla on valemoduuli, jolla on sama rajapinta
(``room_tone``, ``excess_curves``, ``apply``, ``N_FFT``). Testit todistavat ajurin
oman osuuden: mihin jaksoihin se huoneäänen mittaa, mikä on kunkin mikin oma puhetaso
ja mitä se tulostaa ja kirjoittaa.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "floormatch_try", ROOT / "scripts" / "ab" / "floormatch_try.py"
)
ft = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ft)

RATE = 16000


def _voice(speaking, seconds=60.0, seed=1, hiss=1e-4, level=0.1):
    """Mikki, joka puhuu annetuissa sekunneissa; muulloin vain lattiakohinaa."""
    rng = np.random.default_rng(seed)
    n = int(seconds * RATE)
    spectrum = np.fft.rfft(rng.standard_normal(n))
    freqs = np.fft.rfftfreq(n, 1 / RATE)
    spectrum /= np.sqrt(np.maximum(freqs, 50.0))
    speech = np.fft.irfft(spectrum, n)
    speech /= np.sqrt(np.mean(speech**2))
    gate = np.zeros(n)
    for a, b in speaking:
        gate[int(a * RATE) : int(b * RATE)] = 1.0
    return (level * speech * gate + rng.standard_normal(n) * hiss).astype(np.float32)


#: A puhuu 5–15 s ja 35–45 s, B 20–30 s ja 50–58 s; yhteiset tauot ovat siinä välissä.
A = [(5.0, 15.0), (35.0, 45.0)]
B = [(20.0, 30.0), (50.0, 58.0)]


class FakeFloor:
    """Sama rajapinta kuin ``speechmix.floormatch``:ssa; muistaa kutsunsa."""

    N_FFT = 256

    def __init__(self):
        self.calls = {"room_tone": [], "excess_curves": [], "apply": []}

    def room_tone(self, x, rate, spans, trim_s=0.2):
        self.calls["room_tone"].append(list(spans))
        return np.ones(self.N_FFT // 2 + 1) if spans else None

    def excess_curves(self, tones, speech_db, rate):
        self.calls["excess_curves"].append((set(tones), dict(speech_db)))
        out = {name: np.zeros(self.N_FFT // 2 + 1) for name in tones}
        first = sorted(tones)[0]
        out[first] = np.full(self.N_FFT // 2 + 1, 6.0)
        return out

    def apply(self, audio, rate, tone, excess_db):
        self.calls["apply"].append(float(np.max(excess_db)))
        return (audio * 0.5).astype(np.float32) if excess_db.max() > 0 else audio


def _tracks():
    return {"A": _voice(A, seed=1), "B": _voice(B, seed=2)}


def test_pauses_are_only_where_nobody_speaks():
    masks = ft.frame_masks(_tracks(), RATE)
    spans = ft.common_pauses(masks)
    assert spans, "there are pauses between the two speakers"
    speaking = A + B
    for start, end in spans:
        assert end - start >= ft.MIN_PAUSE_S
        for a, b in speaking:
            assert end <= a or start >= b, (start, end, a, b)


def test_a_pause_is_pulled_in_from_the_speech_around_it():
    spans = ft.common_pauses(ft.frame_masks(_tracks(), RATE))
    # A päättyy 15 s ja B alkaa 20 s: väli 15-20 s, vartiovälit sisään.
    inside = [s for s in spans if s[0] >= 14.0 and s[1] <= 21.0]
    assert inside
    start, end = inside[0]
    # Kiinteät luvut, ei vakiota: A päättyy 15 s ja B alkaa 20 s, ja puheen
    # molemmille puolille jää vähintään 0,25 s vartiovälin verran.
    assert start >= 15.25 and end <= 19.75


def test_the_own_speech_level_comes_from_the_mic_s_own_solo_speech():
    tracks = _tracks()
    masks = ft.frame_masks(tracks, RATE)
    loud = ft.own_speech_level_db(tracks["A"], masks, "A", RATE)
    quiet_tracks = {"A": _voice(A, seed=1, level=0.05), "B": tracks["B"]}
    quiet = ft.own_speech_level_db(
        quiet_tracks["A"], ft.frame_masks(quiet_tracks, RATE), "A", RATE
    )
    assert loud - quiet == pytest.approx(6.0, abs=0.7)  # puolet = -6 dB


def test_a_run_passes_the_pauses_and_levels_to_floormatch_and_reports(tmp_path):
    floor = FakeFloor()
    result = ft.run(floor, _tracks(), RATE, tmp_path)
    assert {row["name"] for row in result["rows"]} == {"A", "B"}
    assert len(floor.calls["room_tone"]) == 2  # kerran per mikki
    names, speech = floor.calls["excess_curves"][0]
    assert names == {"A", "B"}
    assert all(isinstance(v, float) for v in speech.values())
    text = ft.format_report(result)
    assert "| A |" in text and "| B |" in text
    assert "excess" in text.lower()


def test_apply_runs_for_every_mic_and_the_wavs_are_written(tmp_path):
    floor = FakeFloor()
    ft.run(floor, _tracks(), RATE, tmp_path)
    assert len(floor.calls["apply"]) == 2
    for name in ("A", "B"):
        assert (tmp_path / f"{name}.original.wav").exists()
        assert (tmp_path / f"{name}.matched.wav").exists()
    original, _ = sf.read(tmp_path / "A.original.wav")
    matched, _ = sf.read(tmp_path / "A.matched.wav")
    assert matched.shape == original.shape


def test_a_mic_without_a_room_tone_profile_is_left_out_not_guessed(tmp_path):
    class NoProfileFirst(FakeFloor):
        def room_tone(self, x, rate, spans, trim_s=0.2):
            first = not self.calls["room_tone"]
            result = super().room_tone(x, rate, spans, trim_s)
            return None if first else result

    result = ft.run(NoProfileFirst(), _tracks(), RATE, tmp_path)
    assert result["skipped"] == ["A"]
    text = ft.format_report(result)
    assert "no room tone" in text and "A" in text


def test_one_track_is_an_error_since_the_method_compares_mics(tmp_path):
    with pytest.raises(ValueError, match="two"):
        ft.run(FakeFloor(), {"A": _voice(A)}, RATE, tmp_path)


def test_main_reads_name_equals_path_and_prints_a_report(tmp_path, monkeypatch, capsys):
    paths = []
    for name, track in _tracks().items():
        path = tmp_path / f"{name}.wav"
        sf.write(path, track, RATE)
        paths.append(f"{name}={path}")
    monkeypatch.setattr(ft, "_import_floormatch", lambda: FakeFloor())
    code = ft.main(
        [
            "--track", paths[0], "--track", paths[1],
            "--start", "0", "--seconds", "60", "--out", str(tmp_path / "out"),
        ]
    )  # fmt: skip
    out = capsys.readouterr().out
    assert code == 0
    assert "| A |" in out and "compare.py" in out
    assert (tmp_path / "out" / "A.matched.wav").exists()


def test_the_own_level_prefers_frames_where_no_other_mic_speaks():
    """Päällekkäisessä puheessa mikki kuulee toisen vuotoa: oma taso otetaan yksinpuheesta."""
    own = _voice([(5.0, 15.0)], seed=1, level=0.1)
    leak = _voice([(20.0, 30.0)], seed=7, level=0.3)  # B puhuu silloin, A kuulee kovemmin
    tracks = {"A": own + leak, "B": _voice(B, seed=2)}
    masks = ft.frame_masks(tracks, RATE)
    level = ft.own_speech_level_db(tracks["A"], masks, "A", RATE)
    # Yksinpuhe on 0,1 = -20 dB; kaikista omista kehyksistä keskiarvo olisi noin -13 dB.
    assert level == pytest.approx(-20.0, abs=1.5)
