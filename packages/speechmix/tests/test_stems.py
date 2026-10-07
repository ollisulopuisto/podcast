"""Stemit levyltä ohjelmaksi paloittain.

``sum_to_file`` on autoraffkatin videorenderin äänisumma, siirretty
kirjastoon jotta automixer voi kirjoittaa koko jakson ilman että se on
muistissa. Stereolähde (musiikki) säilyy stereona.
"""

from __future__ import annotations

import numpy as np
import soundfile as sf

from speechmix import stems

RATE = 48000


def test_sum_keeps_stereo_music_and_pans_mono_speech(tmp_path):
    n = RATE * 3
    left = np.full(n, 0.2, dtype=np.float32)
    right = np.full(n, -0.1, dtype=np.float32)
    sf.write(tmp_path / "music.wav", np.stack([left, right], axis=1), RATE)
    sf.write(tmp_path / "voice.wav", np.full(n, 0.3, dtype=np.float32), RATE)
    out = tmp_path / "mix.wav"
    stems.sum_to_file(
        [
            stems.Source(str(tmp_path / "music.wav"), [(0.0, 3.0, 0.0)], stereo=True),
            stems.Source(str(tmp_path / "voice.wav"), [(1.0, 2.0, 0.0)], pan=-100),
        ],
        0.0, 3.0, str(out), rate=RATE, block=0.7,
    )
    mix, rate = sf.read(out, always_2d=True)
    assert rate == RATE and mix.shape == (n, 2)
    # Musiikki: vasen ja oikea omina, ei keskiarvona.
    assert np.allclose(mix[int(0.5 * RATE)], [0.2, -0.1], atol=1e-4)
    # Puhe täysin vasemmalla: vasen +0,3, oikea ei mitään.
    assert np.allclose(mix[int(1.5 * RATE)], [0.5, -0.1], atol=1e-4)


def test_meter_reads_stereo_as_the_standard_does():
    """BS.1770: kanavien tehot summataan. Kaksoismono on 3 dB monoa
    kovempi, ja pyloudnorm lukee saman. Keskiarvo kanavista luki monon
    lukeman stereolle, ja automixerin miksaus jäi tavoitteen yli 3,7 dB."""
    import pyloudnorm as pyln

    from speechmix.meter import IntegratedMeter

    rng = np.random.default_rng(1)
    mono = rng.normal(0, 0.05, RATE * 10)
    stereo = np.stack([mono, rng.normal(0, 0.03, RATE * 10)])
    meter = IntegratedMeter(RATE)
    for i in range(0, stereo.shape[1], RATE):
        meter.add(stereo[:, i:i + RATE])
    want = pyln.Meter(RATE).integrated_loudness(stereo.T)
    assert abs(meter.value() - want) < 0.1


def _noise(path, seconds, level, seed):
    rng = np.random.default_rng(seed)
    x = rng.normal(0, level, int(seconds * RATE)).astype(np.float32)
    sf.write(path, x, RATE, subtype="FLOAT")


def _job(tmp_path, name, seconds, start, level, seed):
    from speechmix.timeline import Span, Track

    target = tmp_path / f"{name} [mix].wav"
    _noise(target, seconds, level, seed)
    return {
        "key": name, "name": name, "speaker": name, "speech": True,
        "source": str(target), "target": str(target), "bit_depth": 32,
        "track": Track(str(target), name, [Span(start, start + seconds, 0.0)]),
    }


def _programme(jobs, seconds):
    """Stemit aikajanalle kuten isäntä ne soittaa (mono, ei panorointia)."""
    out = np.zeros(int(seconds * RATE))
    for job in jobs:
        x, _ = sf.read(job["target"])
        span = job["track"].spans[0]
        a = int(round(span.programme_start * RATE))
        out[a:a + len(x)] += x
    return out


def test_mics_of_different_length_are_mastered_on_the_timeline(tmp_path):
    """pp 56: kaksi eri tallentimen mikkiä, eri pituus. Katto ryhmitteli
    stemit tarkan sijainnin ja pituuden mukaan, kumpikin jäi yksin, eikä
    mitään masteroitu: «masterointi: 0.0 LUFS · nan» (2026-10-07)."""
    from types import SimpleNamespace

    import pyloudnorm as pyln

    jobs = [_job(tmp_path, "a", 10.0, 0.0, 0.25, 1),
            _job(tmp_path, "b", 8.0, 2.0, 0.25, 2)]
    result = stems.StemResult()
    settings = SimpleNamespace(target_lufs=-16.0, program_peak_db=-1.0)
    stems.program_deliver(jobs, result, {}, {}, settings)
    assert result.program_lufs != 0.0
    programme = _programme(jobs, 10.0)
    assert abs(pyln.Meter(RATE).integrated_loudness(programme) - -16.0) < 0.6
    from scipy import signal
    peak = 20 * np.log10(np.abs(signal.resample_poly(programme, 4, 1)).max())
    assert peak <= -1.0 + 0.2, peak


def test_a_single_mic_is_mastered_too(tmp_path):
    from types import SimpleNamespace

    import pyloudnorm as pyln

    jobs = [_job(tmp_path, "a", 10.0, 0.0, 0.06, 3)]   # ~ −23 LUFS, kuten ketjun stemi
    result = stems.StemResult()
    stems.program_deliver(jobs, result, {}, {},
                          SimpleNamespace(target_lufs=-16.0, program_peak_db=-1.0))
    programme = _programme(jobs, 10.0)
    assert abs(pyln.Meter(RATE).integrated_loudness(programme) - -16.0) < 0.6


def test_nothing_to_master_is_said(tmp_path):
    from types import SimpleNamespace

    result = stems.StemResult()
    jobs = [{"key": "a", "speech": True, "target": str(tmp_path / "missing.wav")}]
    stems.program_deliver(jobs, result, {}, {},
                          SimpleNamespace(target_lufs=-16.0, program_peak_db=-1.0))
    assert any("master" in n.lower() for n in result.notes.get("a", []))


# --- Rinnakkaiset stemit ----------------------------------------------------

GB = 1 << 30


def test_two_stems_run_together_when_both_fit(monkeypatch):
    monkeypatch.delenv("SPEECHMIX_PARALLEL_STEMS", raising=False)
    size = GB // 4                       # 20 min mono float32 ≈ 0.23 GB
    need = 2 * stems.STEM_MEMORY_FACTOR * size + stems.MEMORY_RESERVE
    assert stems.parallel_count([size, size], available=need + GB) == 2
    assert stems.parallel_count([size, size], available=need - GB) == 1


def test_one_at_a_time_when_unsure(monkeypatch):
    """Tuntematon koko, yksi stemi tai pakotettu 1: ei rinnakkain. Arvio
    joka epäonnistuu ajaa niin kuin ennen eikä ota muistia sokkona."""
    monkeypatch.delenv("SPEECHMIX_PARALLEL_STEMS", raising=False)
    plenty = 512 * GB
    assert stems.parallel_count([GB // 4, None], available=plenty) == 1
    assert stems.parallel_count([GB // 4], available=plenty) == 1
    assert stems.parallel_count([GB // 4] * 5, available=plenty) == stems.MAX_PARALLEL
    monkeypatch.setenv("SPEECHMIX_PARALLEL_STEMS", "1")
    assert stems.parallel_count([GB // 4] * 2, available=plenty) == 1


def test_stems_overlap_and_results_come_back(monkeypatch):
    import threading

    meet = threading.Barrier(2, timeout=5)

    def work(job):
        meet.wait()                     # aikakatkaisu jos ajetaan peräkkäin
        if job == "b":
            raise ValueError("rikki")
        return job.upper()

    got = {job: (value, error) for job, value, error
           in stems.run_parallel(["a", "b"], work, 2)}
    assert got["a"] == ("A", None)
    assert isinstance(got["b"][1], ValueError)


def test_one_worker_keeps_the_order_and_the_thread():
    import threading

    seen = []
    out = list(stems.run_parallel(
        ["a", "b", "c"], lambda job: seen.append(threading.current_thread()) or job, 1
    ))
    assert [job for job, _v, _e in out] == ["a", "b", "c"]
    assert set(seen) == {threading.main_thread()}


def test_stem_size_reads_the_header(tmp_path):
    path = tmp_path / "x.wav"
    sf.write(path, np.zeros((RATE, 2), dtype=np.float32), RATE)
    assert stems.stem_size(str(path)) == RATE * 2 * 4
    assert stems.stem_size(str(tmp_path / "missing.wav")) is None


def test_parallel_work_sees_the_callers_context():
    """autoraffkatin kieli on ``ContextVar``: rinnakkaisen stemin virhe
    olisi muuten väärällä kielellä."""
    import contextvars

    lang = contextvars.ContextVar("lang", default="en")
    lang.set("fi")
    got = [value for _job, value, _e in stems.run_parallel(
        ["a", "b"], lambda _job: lang.get(), 2)]
    assert got == ["fi", "fi"]


def test_a_stem_holds_few_copies_of_its_track(tmp_path, monkeypatch):
    """Stemin huippu raidan kerrannaisena. Mitattu 20 min oikeaa puhetta
    de-clickin kanssa: 9,0 × float32-raita ennen, 6,0 kun raita luovutetaan
    ketjulle, ketju sekoittaa ja kompressoi paikallaan ja rajoittimen
    kierrokset mittaavat ilman raidan mittaista monoa."""
    import sys
    import tracemalloc
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent))
    from test_chain import _spiky

    from autoraffkat.model import AudioSettings

    audio = _spiky(seconds=180.0)[0]
    sf.write(tmp_path / "mic.wav", audio, RATE, subtype="FLOAT")
    sf.write(tmp_path / "warm.wav", audio[: RATE * 5], RATE, subtype="FLOAT")
    settings = AudioSettings()
    settings.declick = True

    def job(name):
        return {"key": name, "name": name, "speaker": name,
                "source": str(tmp_path / f"{name}.wav"),
                "target": str(tmp_path / f"{name} out.wav"),
                "target_lufs": -16.0, "gain_db": 0.0, "speech": True, "mono": True}

    # Vakiokokoiset palat (de-click minuutti, GPU 2^21 näytettä) pienemmiksi:
    # kolmen minuutin raidalla ne näyttäisivät raidan kerrannaisilta.
    from speechmix import chain

    monkeypatch.setattr(chain, "_DECLICK_CHUNK", 5 * RATE)
    monkeypatch.setattr(chain, "_GPU_CHUNK", 1 << 17)
    stems.process_stem(job("warm"), settings, None)
    tracemalloc.start()
    stems.process_stem(job("mic"), settings, None)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert peak < 7.0 * audio.nbytes, peak / audio.nbytes
