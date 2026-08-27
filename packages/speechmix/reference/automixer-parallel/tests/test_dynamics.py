"""Compression comes in small amounts several times -- and every stage must fire.

One of the three stages never fired.  Its threshold was written
``leveler_threshold + 4.0`` -- four decibels *above* the second stage -- and it
runs after the second, which has already pulled everything below its own
threshold.  Measured on three minutes of real speech, that stage's gain moved
0.00 dB at every target from -14 to -18 LUFS.  The chain promised three stages
and ran two.

And: the peak attack must be longer than a pitch period.  Two milliseconds
modulates the waveform of a 110 Hz voice instead of its level, which is
harmonic distortion by definition.
"""

import numpy as np
import pyloudnorm as pyln
import pytest
from scipy import signal as sp_signal

from speechmix import compress, multiband_compress, speech_dynamics
from speechmix.dynamics import MAX_GR_DB, PEAK_ATTACK_MS, WORKING_LEVEL_LUFS

from material import speech_like


def _at_working_level(audio, rate):
    """Thresholds are absolute and applied *after* normalisation."""
    loudness = pyln.Meter(rate).integrated_loudness(audio)
    return audio * 10 ** ((WORKING_LEVEL_LUFS - loudness) / 20)


def _thd_db(signal, rate, f0):
    window = np.hanning(signal.size)
    spectrum = np.abs(np.fft.rfft(signal * window))
    freqs = np.fft.rfftfreq(signal.size, 1 / rate)

    def energy(centre):
        return np.sum(spectrum[(freqs > centre - 3) & (freqs < centre + 3)] ** 2)

    return 10 * np.log10(sum(energy(f0 * k) for k in range(2, 11)) / energy(f0))


def test_every_stage_fires(rate, varied_speech):
    """The test the chain never had.  A stage that moves 0.00 dB is not running."""
    audio = _at_working_level(varied_speech, rate)
    _, report = speech_dynamics(audio, rate)

    assert len(report.stages) == 3
    assert report.silent_stages == [], "\n".join(str(s) for s in report.stages)
    for stage in report.stages:
        assert stage.fired, str(stage)


def test_the_stage_that_never_fired(rate, varied_speech):
    """The sign of one constant, reproduced.

    Stage 3 with its threshold four decibels *above* stage 2 sees nothing:
    stage 2 has already pulled everything below its own threshold.
    """
    audio = _at_working_level(varied_speech, rate)

    levelled, _ = compress(audio, rate, threshold_db=-24.0, ratio=1.5, attack_ms=60.0)
    _, wrong_way = compress(levelled, rate, threshold_db=-24.0 + 4.0, ratio=1.25, attack_ms=120.0)
    _, right_way = compress(levelled, rate, threshold_db=-24.0 - 4.0, ratio=1.25, attack_ms=120.0)

    assert right_way.fired
    # Measured on real speech, the stage written the wrong way round moved
    # 0.00 dB at every target from -14 to -18 LUFS.  On this fixture it is not
    # quite zero, but it is a rounding error next to the stage that works.
    assert wrong_way.max_gr_db < right_way.max_gr_db / 10.0


def test_the_fixture_itself_must_have_uneven_bursts(rate, varied_speech):
    """The note the test fixture had to learn.

    A signal whose every burst is equally loud sits entirely below every
    absolute threshold, and the test then passes while measuring nothing.
    """
    audio = _at_working_level(varied_speech, rate)
    block = int(0.4 * rate)
    blocks = audio[: (audio.size // block) * block].reshape(-1, block)
    levels = 20 * np.log10(np.sqrt(np.mean(blocks**2, axis=1)) + 1e-12)
    speaking = levels > np.percentile(levels, 50)
    assert np.std(levels[speaking]) > 2.0

    flat = np.sign(audio) * np.mean(np.abs(audio))
    _, flat_report = speech_dynamics(_at_working_level(flat, rate), rate)
    assert flat_report.silent_stages, "a flat fixture must be visibly useless, not silently so"


def test_each_stage_is_bounded(rate, varied_speech):
    """Three small amounts, not one large one: 5 dB is the cap per stage."""
    loud = _at_working_level(varied_speech, rate) * 8.0
    _, report = speech_dynamics(loud, rate)
    for stage in report.stages:
        assert stage.max_gr_db <= MAX_GR_DB + 1e-6, str(stage)


def test_no_makeup_gain(rate, varied_speech):
    """Downward only.  Makeup gain would raise the noise floor between words."""
    audio = _at_working_level(varied_speech, rate)
    out, _ = speech_dynamics(audio, rate)
    assert np.max(np.abs(out)) <= np.max(np.abs(audio)) + 1e-9
    assert np.sqrt(np.mean(out**2)) <= np.sqrt(np.mean(audio**2)) + 1e-9


def test_a_plosive_does_not_pull_the_sibilance_down(rate):
    """Why the first stage is multiband."""
    n = 3 * rate
    t = np.arange(n) / rate
    sibilance = 0.05 * np.sin(2 * np.pi * 7000 * t)
    plosive = np.zeros(n)
    burst = slice(rate, rate + int(0.08 * rate))
    plosive[burst] = 0.9 * np.sin(2 * np.pi * 90 * t[burst]) * np.hanning(burst.stop - burst.start)
    audio = sibilance + plosive

    wide, _ = compress(audio, rate, threshold_db=-25.0, ratio=3.0, attack_ms=PEAK_ATTACK_MS)
    banded, _ = multiband_compress(audio, rate, threshold_db=-25.0, ratio=3.0)

    def sibilance_level(x):
        spectrum = np.abs(np.fft.rfft(x[burst]))
        freqs = np.fft.rfftfreq(x[burst].size, 1 / rate)
        return np.sum(spectrum[(freqs > 6500) & (freqs < 7500)] ** 2)

    assert sibilance_level(banded) > sibilance_level(wide) * 1.5


def test_one_ratio_and_one_limit_across_the_bands(rate, varied_speech):
    """Differing amounts per band move the tone with the programme.

    With everything below the threshold the multiband stage is a true no-op:
    the zero-phase subtraction crossover sums back to the input exactly, so a
    quiet passage comes out unchanged rather than merely similar.
    """
    audio = _at_working_level(varied_speech, rate) * 0.001
    out, report = multiband_compress(audio, rate, threshold_db=-20.0, ratio=2.5)
    assert not report.fired
    np.testing.assert_allclose(out, audio, atol=1e-12)


@pytest.mark.parametrize("f0", [110.0, 80.0])
def test_the_attack_must_be_longer_than_a_pitch_period(rate, f0):
    """Measured on a sine at 110 Hz / -6 dBFS: 2 ms -> -30.9 dB THD,
    10 ms -> -32.9, 40 ms -> -36.1.  15 ms is longer than a pitch period for
    every speaking voice; 2 ms modulates the waveform instead of the level.
    """
    t = np.arange(3 * rate) / rate
    sine = 0.5 * np.sin(2 * np.pi * f0 * t)

    fast, _ = compress(sine, rate, threshold_db=-12.0, ratio=4.0, attack_ms=2.0)
    proper, _ = compress(sine, rate, threshold_db=-12.0, ratio=4.0, attack_ms=PEAK_ATTACK_MS)
    slow, _ = compress(sine, rate, threshold_db=-12.0, ratio=4.0, attack_ms=40.0)

    assert _thd_db(fast, rate, f0) > _thd_db(proper, rate, f0) + 10.0
    assert _thd_db(slow, rate, f0) <= _thd_db(fast, rate, f0)
    assert PEAK_ATTACK_MS > 1000.0 / 67.0, "15 ms must exceed a pitch period at 67 Hz"


def test_deessing_happens_before_the_compressors(rate):
    """One sibilant otherwise drives the gain of a whole sentence.

    A restoration plug-in adds +4...+5.7 dB above 3 kHz, so this is not a
    hypothetical: the loudest thing in the sentence becomes the "s", and the
    compressor's release then carries that gain reduction across the words
    after it.
    """
    from speechmix import deess

    n = 4 * rate
    t = np.arange(n) / rate
    body = 0.03 * np.sin(2 * np.pi * 150 * t)          # quiet: below the threshold
    ess = np.zeros(n)
    hiss = slice(int(1.0 * rate), int(1.15 * rate))
    noise = sp_signal.sosfilt(
        sp_signal.butter(4, [5000, 9000], "bp", fs=rate, output="sos"),
        np.random.default_rng(3).normal(0, 1, hiss.stop - hiss.start),
    )
    ess[hiss] = 0.5 * noise / np.max(np.abs(noise))     # loud: well over it
    audio = body + ess

    tamed, deess_report = deess(audio, rate, threshold_db=-25.0)
    assert deess_report.fired

    without, report_without = compress(
        audio, rate, threshold_db=-25.0, ratio=3.0, release_ms=400.0
    )
    with_deess, report_with = compress(
        tamed, rate, threshold_db=-25.0, ratio=3.0, release_ms=400.0
    )

    # The words after the sibilant: without de-essing they are still being
    # held down by it.
    after = slice(int(1.2 * rate), int(1.6 * rate))
    assert np.sqrt(np.mean(with_deess[after] ** 2)) > np.sqrt(np.mean(without[after] ** 2)) * 1.2
    assert report_with.max_gr_db < report_without.max_gr_db
