"""Ajertuman korjaus: jakson loppu hiljenee alkua kohti.

RX:n mittaus jakson summasta (2026-11): integroitu -17,6 kun tavoite on
-16, ja ensimmäiset ~10 min soivat loppua kuumempana. Tasainen nosto osuu
tavoitteeseen vain keskiarvona ja jättää lopun hiljaiseksi. Korjaus on
käsin tehty faderiliu'u: se odottaa viiveensä, koska alku kuullaan
viitetasona, ja nousee sitten hitaasti kohti loppua, enintään mitatun
ajertuman verran. Puheportti pitää musiikin ja tauot poissa trendistä.
"""

from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf

from speechmix import programme, stems
from speechmix.meter import IntegratedMeter

RATE = 48000


def _series(db_start, db_end, minutes=60, step=0.1):
    """Tunnin ohjelman lyhytaikainen äänekkyyssarja, alusta loppuun liu'unna."""
    n = int(minutes * 60 / step)
    return np.linspace(db_start, db_end, n)


def test_a_flat_program_means_no_lift():
    lift = programme.drift_lift(_series(-20.0, -20.0), 0.1)
    assert np.all(lift == 0.0)


def test_a_fading_program_is_lifted_toward_the_end():
    lift = programme.drift_lift(_series(-18.0, -20.0), 0.1)
    assert np.all(lift >= 0.0)
    assert lift[-1] == pytest.approx(2.0, abs=0.05)


def test_the_lift_waits_for_its_delay():
    lift = programme.drift_lift(_series(-18.0, -20.0), 0.1, delay_sec=600)
    assert np.all(lift[: int(600 / 0.1)] == 0.0)
    assert lift[-1] > 1.9


def test_the_lift_is_capped():
    # 20 dB:n ajertumaa ei ole oikeassa ohjelmassa; raja pitää korjauksen
    # korjauksena eikä anna virhemittauksen kirjoittaa faderia loputtomiin.
    lift = programme.drift_lift(_series(-10.0, -30.0), 0.1, max_db=3.0)
    assert lift.max() == pytest.approx(3.0, abs=0.05)


def test_a_rising_program_is_not_cut():
    lift = programme.drift_lift(_series(-24.0, -18.0), 0.1)
    assert np.all(lift == 0.0)


def test_a_small_drift_is_left_alone():
    lift = programme.drift_lift(_series(-18.0, -18.3), 0.1)
    assert np.all(lift == 0.0)


def test_the_ramp_moves_too_slowly_to_hear():
    # 2 dB tunnin aikana: yhdellä 0,1 s askelella liike on mitätön.
    lift = programme.drift_lift(_series(-18.0, -20.0), 0.1)
    assert np.diff(lift).max() < 0.01


def test_only_speech_steps_count():
    # Kuuma musiikki-intro ei ole ajertumaa: puhe pysyy samana alusta loppuun.
    values = _series(-18.0, -18.0)
    intro = int(60 / 0.1)
    values[:intro] = -6.0
    speech = np.ones(values.size)
    speech[:intro] = 0.0
    lift = programme.drift_lift(values, 0.1, speech=speech)
    assert np.all(lift == 0.0)


def test_silence_does_not_poison_the_trend():
    values = _series(-18.0, -20.0)
    values[int(30 / 0.1):int(120 / 0.1)] = -np.inf  # puhetauko
    lift = programme.drift_lift(values, 0.1)
    assert lift[-1] == pytest.approx(2.0, abs=0.05)


def test_short_term_speech_tracks_the_short_term_windows():
    meter = IntegratedMeter(RATE)
    t = np.arange(RATE * 60) / RATE
    tone = (0.1 * np.sin(2 * np.pi * 220 * t))[None, :]
    speech = np.zeros(t.size)
    speech[: RATE * 30] = 1.0
    meter.add(tone, speech=speech)
    values, spoken = meter.short_term(), meter.short_term_speech()
    assert values.shape == spoken.shape
    assert spoken[0] > 0.9
    assert spoken[-1] < 0.1


def _fading_job(tmp_path, seconds=90.0, fade_db=-6.0):
    """Stem, jonka taso liukuu ``fade_db`` verran alas jakson aikana."""
    from speechmix.timeline import Span, Track

    rng = np.random.default_rng(1)
    n = int(seconds * RATE)
    fade = np.linspace(1.0, 10 ** (fade_db / 20), n)
    audio = rng.normal(0, 0.05, n) * fade
    target = tmp_path / "puhe [mix].wav"
    sf.write(str(target), audio, RATE)
    return {
        "key": "puhe", "name": "puhe", "speaker": "puhe", "speech": True,
        "source": str(target), "target": str(target), "bit_depth": 32,
        "track": Track(str(target), "puhe", [Span(0.0, seconds, 0.0)]),
    }


def _rms_db(audio):
    return 20 * np.log10(np.sqrt(np.mean(audio**2)))


def _end_minus_start_db(audio, seconds=10.0):
    n = int(seconds * RATE)
    return _rms_db(audio[-n:]) - _rms_db(audio[:n])


@pytest.mark.parametrize("drift,expected_gain", [(True, 1.5), (False, 0.5)])
def test_mastering_lifts_a_fading_program_toward_the_end(
        tmp_path, drift, expected_gain):
    """Ajertuvan jakson loppu nousee alkua kohti; kytkettävissä pois."""
    settings = SimpleNamespace(
        target_lufs=-16.0, program_peak_db=-1.0,
        program_drift=drift, program_drift_delay_sec=10.0,
        program_drift_min_ramp_sec=30.0)
    job = _fading_job(tmp_path)
    before, _ = sf.read(job["target"], dtype="float64")
    stems.program_deliver([job], stems.StemResult(), {}, {}, settings)
    after, _ = sf.read(job["target"], dtype="float64")
    gained = _end_minus_start_db(after) - _end_minus_start_db(before)
    assert gained > expected_gain if drift else gained < expected_gain


def test_an_episode_ending_just_after_the_delay_gets_no_fast_ramp():
    # 301 s jakso: viiveen (300 s) jälkeen jää sekunti, eikä koko korjausta
    # saa puristaa siihen — liuku on aina hidas tai se jää tekemättä.
    values = _series(-18.0, -22.0, minutes=301 / 60)
    lift = programme.drift_lift(values, 0.1)
    assert np.diff(lift).max() < 0.01
    assert lift[-1] < 0.5


def test_an_episode_shorter_than_the_delay_is_not_touched():
    values = _series(-18.0, -22.0, minutes=4)
    assert np.all(programme.drift_lift(values, 0.1) == 0.0)


def _fading_named_job(tmp_path, name, seconds, fade_db=-6.0, seed=1):
    from speechmix.timeline import Span, Track

    rng = np.random.default_rng(seed)
    n = int(seconds * RATE)
    fade = np.linspace(1.0, 10 ** (fade_db / 20), n)
    audio = rng.normal(0, 0.05, n) * fade
    target = tmp_path / f"{name} [mix].wav"
    sf.write(str(target), audio, RATE)
    return {
        "key": name, "name": name, "speaker": name, "speech": True,
        "source": str(target), "target": str(target), "bit_depth": 32,
        "track": Track(str(target), name, [Span(0.0, seconds, 0.0)]),
    }


def test_the_lift_reaches_files_when_stems_differ_in_length(tmp_path):
    """Aikajanapolku (eri pituiset päällekkäiset mikit) kirjoittaa vedon."""
    settings = SimpleNamespace(
        target_lufs=-16.0, program_peak_db=-1.0,
        program_drift=True, program_drift_delay_sec=10.0,
        program_drift_min_ramp_sec=30.0)
    jobs = [_fading_named_job(tmp_path, "isanta", 90.0, seed=1),
            _fading_named_job(tmp_path, "vieras", 80.0, seed=2)]
    before = [sf.read(j["target"], dtype="float64")[0] for j in jobs]
    stems.program_deliver(jobs, stems.StemResult(), {}, {}, settings)
    for job, old in zip(jobs, before):
        new, _ = sf.read(job["target"], dtype="float64")
        gained = _end_minus_start_db(new) - _end_minus_start_db(old)
        assert gained > 1.5, f"{job['key']}: veto ei päätynyt tiedostoon"


def test_the_lift_survives_an_active_short_term_ceiling(tmp_path):
    """Lyhytaikainen katto alkua kohden ei saa syödä lopun korjausta.

    Ilman pohjakäyrän säilytystä silmukka korvaa vedon pelkällä
    alasvedolla: integroitu jää tavoitteesta, koska lopun nostoa ei enää
    ole ja tasainen nosto osuu kattoonsa (+12 dB) ennen tavoitetta.
    """
    settings = SimpleNamespace(
        target_lufs=-16.0, program_peak_db=-1.0, program_short_term_db=-20.0,
        program_drift=True, program_drift_delay_sec=10.0,
        program_drift_min_ramp_sec=30.0)
    job = _fading_job(tmp_path)
    result = stems.StemResult()
    stems.program_deliver([job], result, {}, {}, settings)
    assert result.program_lufs == pytest.approx(-16.0, abs=0.5)


def test_a_repeated_source_range_is_ridden_once_not_compounded(tmp_path):
    """Sama lähdealue kahdessa sijoituksessa: veto poltetaan tiedostoon kerran.

    Kahden sijoituksen eri vahvistusta ei voi kirjoittaa samaan tiedostoon;
    varhaisin ohjelman sijoitus voittaa. Ilman suojaa jokainen span loisi
    oman kertojansa ja 6 dB:n veto kasisi 12 dB:ksi.
    """
    from pedalboard.io import AudioFile

    from speechmix.timeline import Span, Track

    rng = np.random.default_rng(5)
    audio = rng.normal(0, 0.05, 30 * RATE)
    target = tmp_path / "leike [mix].wav"
    sf.write(str(target), audio, RATE)
    job = {"key": "leike", "speech": True, "target": str(target),
           "bit_depth": 32,
           "track": Track(str(target), "leike",
                          [Span(0.0, 10.0, 0.0), Span(20.0, 30.0, 0.0)])}
    ride = np.zeros(40)  # 1 askel = 1 s: alkuohjelma 0 dB, loppu +6 dB
    ride[20:] = 6.0
    with AudioFile(str(target)) as handle:
        stems._write_with_gain(job, handle, RATE, [], 1.0, ride, 1.0)
    written, _ = sf.read(str(target) + ".ceil.tmp.wav", dtype="float64")
    gained = _rms_db(written[: 10 * RATE]) - _rms_db(audio[: 10 * RATE])
    assert gained == pytest.approx(0.0, abs=0.3)
