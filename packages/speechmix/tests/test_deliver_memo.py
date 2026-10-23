"""The writing run of the mastering loop applies the curve the last measuring
run already computed, instead of computing and measuring the same thing again.

``program_deliver`` ends with one writing run at the lift the loop settled on.
That run is the last measuring run again: same inputs, same lift, same curve.
Writing from the measurement's curve saves the whole second computation and
must leave the file exactly as a full recomputation would.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf
from test_stems import RATE, _job

from speechmix import programme, stems

CHUNK, MARGIN = 2.0, 0.5
SETTINGS = SimpleNamespace(target_lufs=-16.0, program_peak_db=-1.0)


@pytest.fixture(autouse=True)
def short_chunks(monkeypatch):
    """Several pieces in a few seconds of audio, so the piece edges are crossed."""
    monkeypatch.setattr(programme, "CEILING_CHUNK", CHUNK)
    monkeypatch.setattr(programme, "CEILING_MARGIN", MARGIN)


def _jobs(tmp_path, seconds=9.0):
    # Quiet, so the loop has to lift it (a pass or two) and the limiter has work.
    return [_job(tmp_path, "a", seconds, 0.0, 0.05, 1), _job(tmp_path, "b", seconds, 0.0, 0.04, 2)]


def _deliver(tmp_path, caplog, seconds=9.0, settings=SETTINGS, jobs=None):
    """Returns (result, written audio per job, how often the curve was computed,
    how many measuring runs there were, the pass log)."""
    jobs = jobs or _jobs(tmp_path, seconds)
    calls = []
    real = programme.shared_gain

    def counting(blocks, rate, ceiling_db=-1.0):
        calls.append(1)
        return real(blocks, rate, ceiling_db)

    result = stems.StemResult()
    with caplog.at_level(logging.DEBUG, logger="speechmix"):
        programme.shared_gain = counting
        try:
            stems.program_deliver(jobs, result, {}, {}, settings)
        finally:
            programme.shared_gain = real
    steps = [r.getMessage() for r in caplog.records if r.getMessage().startswith("mastering pass")]
    measured = sum(1 for s in steps if "(measure," in s)
    written = {j["key"]: sf.read(j["target"], dtype="float64")[0] for j in jobs}
    return result, written, len(calls), measured, steps


def _pieces(seconds):
    return -(-int(seconds * RATE) // int(CHUNK * RATE))


def test_the_writing_run_does_not_compute_the_curve_again(tmp_path, caplog):
    _, _, computed, measured, steps = _deliver(tmp_path, caplog)
    assert measured >= 2, steps  # the loop did more than the first look
    assert steps[-1].startswith("mastering pass (write,")
    assert computed == measured * _pieces(9.0)


def test_what_is_written_is_what_a_full_recomputation_writes(tmp_path, caplog, monkeypatch):
    memo_dir, full_dir = tmp_path / "memo", tmp_path / "full"
    memo_dir.mkdir()
    full_dir.mkdir()
    got, audio, *_ = _deliver(memo_dir, caplog)
    caplog.clear()
    monkeypatch.setattr(stems, "GAIN_MEMO_BYTES", 0)  # nothing fits: the old way
    want, expected, computed, measured, _ = _deliver(full_dir, caplog)
    assert computed == (measured + 1) * _pieces(9.0)  # the old way did compute it again
    for key in audio:
        assert np.array_equal(audio[key], expected[key]), key
    for field in ("program_lufs", "program_boost", "program_limit_cost", "program_range",
                  "program_short_term_max", "program_momentary_max"):
        assert getattr(got, field) == getattr(want, field), field


def test_a_curve_that_does_not_fit_the_budget_is_computed_again_not_guessed(
    tmp_path, caplog, monkeypatch
):
    monkeypatch.setattr(stems, "GAIN_MEMO_BYTES", 200)
    _, _, computed, measured, steps = _deliver(tmp_path, caplog)
    assert steps[-1].startswith("mastering pass (write,")
    assert computed == (measured + 1) * _pieces(9.0)


def test_the_memo_keeps_only_what_differs_from_one(monkeypatch):
    memo = stems.GainMemo(1 << 20)
    gain = np.ones(10_000)
    gain[300:340] = np.linspace(0.9, 0.5, 40)
    gain[9000] = 0.123456789
    memo.put(("a",), 0, gain)
    assert memo.bytes < 40 * 8 + 8 + 10_000 // 8 + 64
    assert np.array_equal(memo.get(("a",), 0), gain)
    assert memo.get(("a",), 0).dtype == gain.dtype


def test_the_memo_gives_up_whole_when_it_overflows():
    memo = stems.GainMemo(100)
    memo.put(("a",), 0, np.linspace(0.5, 0.99, 5_000))
    assert memo.broken and not memo.complete(("a",), [0])



def _quiet_then_loud(tmp_path):
    """Four quiet seconds then loud ones: the quiet part gets the floor lift."""
    jobs = _jobs(tmp_path)
    for job in jobs:
        audio, _ = sf.read(job["target"], dtype="float32")
        audio[: 4 * RATE] *= 0.05
        sf.write(job["target"], audio, RATE, subtype="FLOAT")
    return jobs


def test_a_slow_ride_is_written_the_same_either_way(tmp_path, caplog, monkeypatch, capsys):
    """The lift is a curve over time that is multiplied onto the music-free
    speech before the shared curve: the replay must apply it to the same samples."""
    ridden = SimpleNamespace(target_lufs=-16.0, program_peak_db=-1.0, program_lift_db=8.0)
    (tmp_path / "memo").mkdir()
    (tmp_path / "full").mkdir()
    got, audio, computed, measured, _ = _deliver(
        tmp_path / "memo", caplog, settings=ridden, jobs=_quiet_then_loud(tmp_path / "memo"))
    assert "pohjan nosto" in capsys.readouterr().out  # the ride was really in use
    assert computed == measured * _pieces(9.0)
    caplog.clear()
    monkeypatch.setattr(stems, "GAIN_MEMO_BYTES", 0)
    want, expected, *_ = _deliver(
        tmp_path / "full", caplog, settings=ridden, jobs=_quiet_then_loud(tmp_path / "full"))
    for key in audio:
        assert np.array_equal(audio[key], expected[key]), key
    assert got.program_lufs == want.program_lufs


def test_the_budget_is_a_share_of_the_free_memory_and_no_more_than_the_cap(monkeypatch):
    import psutil

    monkeypatch.setattr(psutil, "virtual_memory", lambda: SimpleNamespace(available=4000))
    assert stems._gain_memo().limit == int(4000 * stems.GAIN_MEMO_SHARE)
    monkeypatch.setattr(psutil, "virtual_memory", lambda: SimpleNamespace(available=1 << 60))
    assert stems._gain_memo().limit == stems.GAIN_MEMO_BYTES
