"""The de-clicker's threshold is a rate, not a multiplier.

A de-clicker calibrated by "local reference x N" corrected 2 % of all samples,
550-640 corrections per second, altering the signal -10 dB relative to itself.
It passed every test, because the tests asked whether a planted click was
removed and never how many were found.  These tests ask how many.
"""

import numpy as np
import pytest
from scipy import signal as sp_signal

from speechmix import declick
from speechmix.declick import DEFAULT_MAX_PER_MINUTE

from material import speech_like


def _plant_click(audio, rate, at_sec, seed=0):
    """Plant a lip smack in the nearest pause, which is where they happen."""
    rng = np.random.default_rng(seed)
    length = int(0.0015 * rate)
    click = sp_signal.sosfilt(
        sp_signal.butter(4, 4000, "hp", fs=rate, output="sos"), rng.normal(0, 1, length * 4)
    )[:length]
    click *= 0.3 / np.max(np.abs(click))

    window = int(0.05 * rate)
    wanted = int(at_sec * rate)
    search = np.arange(wanted - rate, wanted + rate, window)
    quiet = min(search, key=lambda i: np.max(np.abs(audio[i : i + window])))
    start = int(quiet + window // 2)
    audio[start : start + length] += click * np.hanning(length)
    return start, length


def test_correction_rate_stays_inside_the_budget(rate):
    """The failure that started this: 550-640 corrections *per second*."""
    audio = speech_like(120, rate, seed=11)
    _, report = declick(audio, rate)

    assert report.per_minute <= DEFAULT_MAX_PER_MINUTE + 1e-9
    # The old detector ran at 550-640 per second.  Nothing near that can be a
    # lip smack: a person makes a few a minute.
    assert report.corrections / (audio.size / rate) < 1.0


def test_the_signal_is_barely_altered(rate):
    """The old de-clicker moved the whole signal -10 dB relative to itself."""
    audio = speech_like(60, rate, seed=12)
    for i, at in enumerate([7.0, 19.0, 33.0]):
        _plant_click(audio, rate, at, seed=i)

    out, report = declick(audio, rate)
    residual = out - audio
    alteration_db = 20 * np.log10(
        np.sqrt(np.mean(residual**2)) / np.sqrt(np.mean(audio**2))
    )
    assert alteration_db < -25.0
    assert report.alteration_db == pytest.approx(alteration_db, abs=0.01)
    assert report.sample_fraction < 0.001  # the old one was 2 % of all samples


def test_planted_clicks_are_found_and_reduced(rate):
    audio = speech_like(60, rate, seed=13)
    marks = [_plant_click(audio, rate, at, seed=i) for i, at in enumerate([5.0, 21.0, 44.0])]

    out, report = declick(audio, rate)
    assert report.applied
    assert report.corrections >= len(marks)

    sos = sp_signal.butter(4, 4000, "hp", fs=rate, output="sos")
    before_hf = sp_signal.sosfiltfilt(sos, audio)
    after_hf = sp_signal.sosfiltfilt(sos, out)
    for start, length in marks:
        window = slice(start, start + length)
        reduction_db = 20 * np.log10(
            np.sqrt(np.mean(after_hf[window] ** 2)) / np.sqrt(np.mean(before_hf[window] ** 2))
        )
        assert reduction_db < -6.0


def test_material_without_clicks_is_left_alone(rate):
    """Correct nothing if the artefact never occurs."""
    audio = speech_like(60, rate, seed=14)
    out, report = declick(audio, rate)
    assert report.corrections == 0
    np.testing.assert_array_equal(out, audio)


def test_a_detector_that_never_fits_the_budget_corrects_nothing(rate):
    """The ceiling: raise the threshold until the findings fit, or do nothing.

    Whatever a detector is finding six hundred times a minute, it is not a lip
    smack, and the honest answer is to touch nothing.
    """
    rng = np.random.default_rng(15)
    crackle = rng.normal(0, 10 ** (-70 / 20), 60 * rate)
    spike = sp_signal.sosfilt(
        sp_signal.butter(4, 4000, "hp", fs=rate, output="sos"), rng.normal(0, 1, 400)
    )[200:216]
    spike *= 0.5 / np.max(np.abs(spike))
    # Ten strong high-frequency transients a second: vinyl crackle, or a bad
    # digital transfer.  Every one of them clears any threshold the detector
    # can reach, so no threshold makes the findings fit a lip smack's rate.
    for i in range(0, crackle.size - spike.size, rate // 10):
        crackle[i : i + spike.size] += spike

    out, report = declick(crackle, rate, max_per_minute=1.0)
    assert not report.applied
    assert "not a lip smack" in report.reason
    np.testing.assert_array_equal(out, crackle)


def test_sample_count_never_changes(rate):
    audio = speech_like(20, rate, seed=16)
    _plant_click(audio, rate, 3.0)
    out, _ = declick(audio, rate)
    assert out.size == audio.size
