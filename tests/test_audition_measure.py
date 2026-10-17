"""Audition-mittaus: onko Mix lineaarinen, ja kuinka pitkä esiaika riittää.

Mittaus ajetaan oikealla dxRevivellä käyttäjän koneella, joten täällä todistetaan
vain että mittari mittaa oikein: tunnetulla lineaarisella liitännäisellä nollaus
onnistuu, tunnetulla epälineaarisella ei, viive korjataan pois ja esiaika löytyy
sieltä missä tunnettu muisti on asettunut.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from scipy import signal as sp

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "audition_measure", ROOT / "scripts" / "ab" / "audition_measure.py"
)
am = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(am)

RATE = 16000
DELAY = 37  # väärin ilmoitettu viive, näytteinä


def _speechlike(seconds=12.0, seed=1):
    """Kohinaa jonka verhokäyrä vaihtelee: korrelaatio löytää viiveen."""
    rng = np.random.default_rng(seed)
    n = int(seconds * RATE)
    t = np.arange(n) / RATE
    envelope = 0.15 + 0.12 * np.abs(np.sin(2 * np.pi * 1.7 * t)) ** 3
    return (rng.standard_normal((1, n)) * envelope).astype(np.float32)


class FakePlugin:
    """Dry/wet-liitännäinen jolla on viive ja jonka Mix-käyrä on valittavissa."""

    def __init__(self, curve=lambda m: m, delay=DELAY):
        self.parameters = {"mix": object()}
        self.mix = 0.0
        self.curve = curve
        self.delay = delay
        self.calls = 0
        self.mix_when_run = []

    def process(self, audio, rate, reset=True):
        self.calls += 1
        self.mix_when_run.append(self.mix)
        wet = np.tanh(3.0 * audio) / 3.0 * 2.0
        m = self.curve(self.mix)
        out = (1.0 - m) * audio + m * wet
        shifted = np.zeros_like(out)
        shifted[:, self.delay :] = out[:, : out.shape[1] - self.delay]
        return shifted.astype(np.float32)


class SlowGain:
    """Muistillinen: hidas verhokäyrä alkaa nollasta, joten alku riippuu esiajasta."""

    def __init__(self, tau=0.3):
        self.parameters = {}
        self.a = float(np.exp(-1.0 / (tau * RATE)))

    def process(self, audio, rate, reset=True):
        env = sp.lfilter([1 - self.a], [1, -self.a], np.abs(audio), axis=1)
        return (audio / (env + 0.05)).astype(np.float32)


def _renders(plugin, audio, mixes, start=4.0, end=8.0, preroll=2.0):
    plugin.mix = 1.0
    full, lag = am.render_window(plugin, audio, RATE, start, end, preroll)
    out = {1.0: full}
    for m in mixes:
        plugin.mix = m
        out[m], _ = am.render_window(plugin, audio, RATE, start, end, preroll, lag=lag)
    plugin.mix = 0.0
    dry, _ = am.render_window(plugin, audio, RATE, start, end, preroll, lag=lag)
    return dry, out


def test_a_render_is_the_window_with_the_latency_taken_out():
    audio = _speechlike()
    dry, _ = _renders(FakePlugin(), audio, [])
    window = audio[:, int(4.0 * RATE) : int(8.0 * RATE)]
    assert dry.shape == window.shape
    assert np.allclose(dry, window, atol=1e-6)


def test_the_latency_is_found_and_reported():
    audio = _speechlike()
    _, lag = am.render_window(FakePlugin(), audio, RATE, 4.0, 8.0, 2.0)
    assert lag == DELAY


def test_a_linear_mix_nulls_against_the_blend():
    audio = _speechlike()
    dry, renders = _renders(FakePlugin(), audio, [0.5])
    residual = am.linear_mix_residual_db(dry, renders[1.0], renders[0.5], 0.5)
    assert residual < am.LINEAR_DB
    assert am.is_linear(residual)


def test_a_nonlinear_mix_does_not_null():
    audio = _speechlike()
    dry, renders = _renders(FakePlugin(curve=lambda m: m**2), audio, [0.5])
    residual = am.linear_mix_residual_db(dry, renders[1.0], renders[0.5], 0.5)
    assert residual > -30.0
    assert not am.is_linear(residual)


def test_the_null_is_measured_against_the_partial_render_not_the_blend():
    """Nolla-vertailun nimittäjä on osittainen ajo: 0 dB = ei mitään yhteistä."""
    zeros = np.zeros((1, 1000), np.float32)
    ones = np.ones((1, 1000), np.float32)
    assert am.residual_db(ones, zeros) == pytest.approx(0.0, abs=1e-6)
    assert am.residual_db(ones, ones) < -120.0


def test_the_preroll_is_the_shortest_one_that_stopped_changing_the_result():
    audio = _speechlike()
    plugin = SlowGain()
    renders = {
        p: am.render_window(plugin, audio, RATE, 6.0, 8.0, p)[0]
        for p in (0.0, 0.5, 4.0, 6.0)
    }
    assert am.settled_preroll(renders) == 4.0
    assert am.residual_db(renders[6.0], renders[0.5]) > am.LINEAR_DB


def test_no_preroll_settles_when_every_one_still_differs():
    audio = _speechlike()
    plugin = SlowGain(tau=3.0)
    renders = {
        p: am.render_window(plugin, audio, RATE, 6.0, 8.0, p)[0] for p in (0.0, 0.5, 1.0)
    }
    assert am.settled_preroll(renders) is None


def test_each_value_gets_its_own_instance_and_comes_back_in_order():
    audio = _speechlike()
    plugins = [FakePlugin() for _ in range(3)]
    variants = [{"mix": 0.25}, {"mix": 0.5}, {"mix": 1.0}]
    renders, seconds = am.render_variants(
        plugins, variants, audio, RATE, 4.0, 8.0, 2.0, workers=2
    )
    assert seconds > 0
    assert [p.calls for p in plugins] == [1, 1, 1]
    assert [p.mix_when_run for p in plugins] == [[0.25], [0.5], [1.0]]
    assert len(renders) == 3
    assert not np.allclose(renders[0], renders[2])


def test_an_unknown_parameter_name_is_an_error_not_a_silent_default():
    audio = _speechlike()
    with pytest.raises(ValueError, match="mixx"):
        am.render_variants(
            [FakePlugin()], [{"mixx": 0.5}], audio, RATE, 4.0, 8.0, 2.0, workers=1
        )


def test_a_window_that_starts_before_the_preroll_is_refused():
    audio = _speechlike()
    with pytest.raises(ValueError, match="preroll"):
        am.render_window(FakePlugin(), audio, RATE, 1.0, 5.0, 2.0)


def test_the_report_says_which_way_it_went_and_carries_the_numbers():
    text = am.format_linearity({0.5: -71.234, 0.25: -12.5})
    assert "-71.2" in text and "-12.5" in text
    assert "linear" in text.lower() and "not" in text.lower()


class NoisyPlugin(FakePlugin):
    """Ei toistettava: jokainen ajo lisää eri kohinaa, kuten generatiivinen malli."""

    def process(self, audio, rate, reset=True):
        out = super().process(audio, rate, reset=reset)
        noise = np.random.default_rng().standard_normal(out.shape) * 0.02
        return (out + noise).astype(np.float32)


def test_a_repeatable_plugin_repeats_to_the_noise_floor():
    audio = _speechlike()
    residual = am.repeat_residual_db(FakePlugin(), audio, RATE, 4.0, 8.0, 2.0)
    assert residual < -100.0


def test_a_plugin_that_does_not_repeat_shows_it():
    audio = _speechlike()
    residual = am.repeat_residual_db(NoisyPlugin(), audio, RATE, 4.0, 8.0, 2.0)
    assert residual > -30.0


def test_a_repeatable_plugin_keeps_the_linearity_verdict():
    text = am.format_linearity({0.5: -13.4}, control=-100.0)
    assert "Not linear" in text
    assert "Inconclusive" not in text


def test_without_a_repeatable_plugin_the_linearity_verdict_is_inconclusive():
    residuals = {0.25: -15.0, 0.5: -13.4, 0.75: -16.9}
    text = am.format_linearity(residuals, control=-14.0)
    assert "Inconclusive" in text
    assert "Not linear" not in text
    assert "-14.0" in text  # kontrolli näkyy taulukossa ja lauseessa


def test_the_preroll_limit_rises_with_the_repeat_noise():
    rng = np.random.default_rng(7)
    reference = rng.standard_normal((1, 8000)).astype(np.float32)

    def off_by(db):
        return reference + 10 ** (db / 20) * rng.standard_normal(reference.shape).astype(
            np.float32
        ) * float(np.sqrt(np.mean(reference**2)))

    renders = {0.0: off_by(-20.0), 4.0: off_by(-20.0), 8.0: reference}
    assert am.settled_preroll(renders) is None  # -20 dB ei ole -60 dB
    assert am.settled_preroll(renders, floor_db=-19.0) == 0.0  # kohinan sisällä


def test_the_preroll_report_names_the_repeat_noise():
    text = am.format_preroll({0.0: -19.2, 4.0: -26.2}, None, control=-19.0)
    assert "-19.0" in text and "repeat" in text.lower()


class EqualPower(FakePlugin):
    """Mix on tasavirtainen ristiinhäivytys: cos/sin, ei (1-m)/m."""

    def process(self, audio, rate, reset=True):
        self.calls += 1
        wet = np.tanh(3.0 * audio) / 3.0 * 2.0
        a, b = np.cos(self.mix * np.pi / 2), np.sin(self.mix * np.pi / 2)
        out = a * audio + b * wet
        shifted = np.zeros_like(out)
        shifted[:, self.delay :] = out[:, : out.shape[1] - self.delay]
        return shifted.astype(np.float32)


class DrivenWet(FakePlugin):
    """Märkä osa riippuu Mixistä (vääristymä kasvaa): ei kahden osan summa."""

    def process(self, audio, rate, reset=True):
        self.calls += 1
        wet = np.tanh((1.0 + 8.0 * self.mix) * audio) / 3.0
        out = (1.0 - self.mix) * audio + self.mix * wet
        shifted = np.zeros_like(out)
        shifted[:, self.delay :] = out[:, : out.shape[1] - self.delay]
        return shifted.astype(np.float32)


class MixDependentDelay(FakePlugin):
    """Kokonaisviive riippuu Mixistä: 30 näytettä kuivana, 40 märkänä."""

    def process(self, audio, rate, reset=True):
        self.delay = int(30 + 10 * self.mix)
        return super().process(audio, rate, reset=reset)


def _fit(plugin, mix):
    audio = _speechlike()
    plugin.mix = 0.0
    dry, lag = am.render_window(plugin, audio, RATE, 4.0, 8.0, 2.0)
    plugin.mix = 1.0
    full, _ = am.render_window(plugin, audio, RATE, 4.0, 8.0, 2.0, lag=lag)
    plugin.mix = mix
    partial, _ = am.render_window(plugin, audio, RATE, 4.0, 8.0, 2.0, lag=lag)
    return am.fit_blend(dry, full, partial)


def test_the_fit_recovers_a_linear_law():
    a, b, residual = _fit(FakePlugin(), 0.25)
    assert (a, b) == (pytest.approx(0.75, abs=1e-3), pytest.approx(0.25, abs=1e-3))
    assert residual < -100.0


def test_the_fit_recovers_a_squared_law_a_plain_blend_cannot_see():
    a, b, residual = _fit(FakePlugin(curve=lambda m: m**2), 0.5)
    assert (a, b) == (pytest.approx(0.75, abs=1e-3), pytest.approx(0.25, abs=1e-3))
    assert residual < -100.0


def test_the_fit_recovers_an_equal_power_law():
    a, b, residual = _fit(EqualPower(), 0.5)
    assert a == pytest.approx(np.cos(np.pi / 4), abs=1e-3)
    assert b == pytest.approx(np.sin(np.pi / 4), abs=1e-3)
    assert residual < -100.0


def test_the_fit_does_not_explain_a_wet_part_that_changes_with_mix():
    _, _, residual = _fit(DrivenWet(), 0.5)
    assert residual > -30.0


def test_every_render_reports_its_own_delay_when_the_delay_follows_the_mix():
    audio = _speechlike()
    plugins = [MixDependentDelay() for _ in range(3)]
    variants = [{"mix": 0.0}, {"mix": 0.5}, {"mix": 1.0}]
    renders, lags, _seconds = am.render_variants_full(
        plugins, variants, audio, RATE, 4.0, 8.0, 2.0, workers=2
    )
    assert lags == [30, 35, 40]
    # Jokainen on viivekorjattu omalla viiveellään: kuiva on ikkuna sellaisenaan.
    window = audio[:, int(4.0 * RATE) : int(8.0 * RATE)]
    assert np.allclose(renders[0], window, atol=1e-6)


def test_a_verdict_beyond_the_repeat_noise_is_not_inconclusive():
    residuals = {0.25: -15.0, 0.5: -13.4, 0.75: -16.9}
    text = am.format_linearity(residuals, control=-38.3)
    assert "beyond the repeat noise" in text.lower()
    assert "Not linear" in text
    assert "Inconclusive" not in text


def test_the_blend_report_gives_weights_per_level_and_a_verdict():
    fits = {0.25: (0.80, 0.20, -50.0), 0.5: (0.60, 0.40, -49.0)}
    text = am.format_blend_fit(fits, control=-38.0)
    assert "0.80" in text and "0.40" in text and "-50.0" in text
    assert "two-component" in text.lower()
    bad = am.format_blend_fit({0.5: (0.6, 0.4, -14.0)}, control=-38.0)
    assert "not" in bad.lower() and "two-component" in bad.lower()


class PercentFake(FakePlugin):
    """Mix prosentteina kuten dxRevivessa: 25 tarkoittaa 0,25."""

    def process(self, audio, rate, reset=True):
        real = self.mix
        self.mix = real / 100.0
        try:
            return super().process(audio, rate, reset=reset)
        finally:
            self.mix = real


def test_main_runs_end_to_end_and_prints_every_section(tmp_path, monkeypatch, capsys):
    audio = _speechlike(seconds=40.0)
    wav = tmp_path / "jakso.wav"
    sf.write(wav, audio[0], RATE)
    monkeypatch.setattr(
        am,
        "_load_instances",
        lambda path, state, count: [PercentFake() for _ in range(count)],
    )
    monkeypatch.setattr(am, "_mix_param_default", lambda path: "mix")
    code = am.main(
        [
            str(wav),
            "--plugin",
            "x.vst3",
            "--start",
            "20",
            "--seconds",
            "4",
            "--preroll",
            "4",
            "--prerolls",
            "0,2,4",
            "--workers",
            "1,2",
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    for heading in (
        "A0: is Mix a linear dry/wet blend?",
        "Mix weights",
        "Delay per render",
        "A1: preroll",
        "A1: time",
    ):
        assert heading in out
    # Lineaarinen valeliitännäinen: 25 % = 0,75 kuivaa ja 0,25 märkää, ja viive 37.
    assert "| 0.25 | 0.75 | 0.25 |" in out
    assert "| 37 |" in out or "| 0 % (dry) | 37 |" in out
    assert "Linear:" in out or "Not linear" not in out


def test_only_a0_stops_before_the_preroll_and_the_clock(tmp_path, monkeypatch, capsys):
    wav = tmp_path / "jakso.wav"
    sf.write(wav, _speechlike(seconds=40.0)[0], RATE)
    monkeypatch.setattr(
        am,
        "_load_instances",
        lambda path, state, count: [PercentFake() for _ in range(count)],
    )
    monkeypatch.setattr(am, "_mix_param_default", lambda path: "mix")
    code = am.main(
        [
            str(wav),
            "--plugin",
            "x.vst3",
            "--start",
            "20",
            "--seconds",
            "4",
            "--preroll",
            "4",
            "--values",
            "10,20,30,40,50,60,70,80,90",
            "--only-a0",
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "A0: is Mix a linear dry/wet blend?" in out
    assert "| 0.9 |" in out
    assert "A1: preroll" not in out and "A1: time" not in out
