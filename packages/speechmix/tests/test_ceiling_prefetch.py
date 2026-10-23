"""The next piece of the programme is prepared while this one is measured.

A pass over the programme does two kinds of work per 60 s piece: read, scale,
duck and compute the shared gain curve (mostly numpy and scipy, which release
the GIL), then measure and write it (the meter and the files, strictly in
order). The first kind for piece n + 1 does not depend on the second kind for
piece n, so it runs one piece ahead on a thread. The meter and the files still
see the pieces in order, and every number is computed as before.
"""

from __future__ import annotations

import threading

import numpy as np
import pytest
from test_deliver_memo import _deliver, _pieces, short_chunks  # noqa: F401

from speechmix import meter as meter_lib
from speechmix import programme, stems


def _watch(monkeypatch):
    """Which threads compute the curve and which measure; what the meter gets, in order."""
    seen = {"curve": set(), "meter": set(), "pieces": []}
    real_gain, real_add = programme.shared_gain, meter_lib.IntegratedMeter.add

    def gain(blocks, rate, ceiling_db=-1.0):
        seen["curve"].add(threading.get_ident())
        return real_gain(blocks, rate, ceiling_db)

    def add(self, block, speech=None):
        seen["meter"].add(threading.get_ident())
        seen["pieces"].append(np.asarray(block).shape[-1])
        return real_add(self, block, speech)

    monkeypatch.setattr(programme, "shared_gain", gain)
    monkeypatch.setattr(meter_lib.IntegratedMeter, "add", add)
    return seen


def test_the_curve_is_computed_on_another_thread_than_the_one_that_measures(
    tmp_path, caplog, monkeypatch
):
    seen = _watch(monkeypatch)
    _deliver(tmp_path, caplog)
    assert seen["curve"] and seen["meter"]
    assert seen["curve"].isdisjoint(seen["meter"])


def test_prefetch_off_keeps_everything_on_the_calling_thread(tmp_path, caplog, monkeypatch):
    monkeypatch.setenv("SPEECHMIX_PREFETCH", "0")
    seen = _watch(monkeypatch)
    _deliver(tmp_path, caplog)
    assert seen["curve"] == seen["meter"] == {threading.get_ident()}


def test_the_result_and_the_order_are_the_same_with_and_without(tmp_path, caplog, monkeypatch):
    runs = {}
    for mode in ("1", "0"):
        with monkeypatch.context() as patch:
            patch.setenv("SPEECHMIX_PREFETCH", mode)
            seen = _watch(patch)
            where = tmp_path / mode
            where.mkdir()
            runs[mode] = (_deliver(where, caplog), seen["pieces"])
        caplog.clear()
    (on, off) = runs["1"], runs["0"]
    assert on[1] == off[1] and len(on[1]) >= 2 * _pieces(9.0)  # every piece, in order
    for key in on[0][1]:
        assert np.array_equal(on[0][1][key], off[0][1][key]), key
    assert on[0][0].program_lufs == off[0][0].program_lufs
    assert on[0][0].program_limit_cost == off[0][0].program_limit_cost


def test_a_failure_while_preparing_a_piece_reaches_the_caller(tmp_path, caplog, monkeypatch):
    def broken(blocks, rate, ceiling_db=-1.0):
        raise OSError("the curve could not be computed")

    monkeypatch.setattr(programme, "shared_gain", broken)
    result = stems.StemResult()
    from types import SimpleNamespace

    from test_deliver_memo import _jobs

    jobs = _jobs(tmp_path)
    stems.program_deliver(jobs, result, {}, {}, SimpleNamespace(target_lufs=-16.0,
                                                               program_peak_db=-1.0))
    # program_ceiling reports an OSError as a note on the stems and goes on.
    assert any("the curve could not be computed" in n for notes in result.notes.values()
               for n in notes)


@pytest.mark.parametrize("value", ["", "x", "-1"])
def test_anything_but_zero_means_on(tmp_path, caplog, monkeypatch, value):
    monkeypatch.setenv("SPEECHMIX_PREFETCH", value)
    seen = _watch(monkeypatch)
    _deliver(tmp_path, caplog)
    assert seen["curve"].isdisjoint(seen["meter"])


def test_two_pieces_are_prepared_at_the_same_time(tmp_path, caplog, monkeypatch):
    """The piece being measured needs far less than the next one needs to be
    prepared (8 min x 3 speakers: 17 s against 42 s), so one piece ahead leaves
    the other cores idle. The barrier only opens if two preparations are inside
    the curve computation together."""
    monkeypatch.delenv("SPEECHMIX_PREFETCH", raising=False)
    meeting = threading.Barrier(2, timeout=10)
    real = programme.shared_gain
    lock, calls = threading.Lock(), {"n": 0}

    def gain(blocks, rate, ceiling_db=-1.0):
        with lock:
            calls["n"] += 1
            first_two = calls["n"] <= 2   # one meeting is enough: the rest run free
        if first_two:
            meeting.wait()
        return real(blocks, rate, ceiling_db)

    monkeypatch.setattr(programme, "shared_gain", gain)
    result, *_ = _deliver(tmp_path, caplog)
    assert result.program_lufs != 0.0 and not meeting.broken


def test_prefetch_one_keeps_to_one_piece_ahead(tmp_path, caplog, monkeypatch):
    monkeypatch.setenv("SPEECHMIX_PREFETCH", "1")
    live, most = {"now": 0}, {"n": 0}
    lock = threading.Lock()
    real = programme.shared_gain

    def gain(blocks, rate, ceiling_db=-1.0):
        with lock:
            live["now"] += 1
            most["n"] = max(most["n"], live["now"])
        try:
            return real(blocks, rate, ceiling_db)
        finally:
            with lock:
                live["now"] -= 1

    monkeypatch.setattr(programme, "shared_gain", gain)
    _deliver(tmp_path, caplog)
    assert most["n"] == 1


@pytest.mark.parametrize("depth", ["1", "2", "3"])
def test_the_depth_changes_nothing_in_the_result(tmp_path, caplog, monkeypatch, depth):
    runs = {}
    for mode in (depth, "0"):
        with monkeypatch.context() as patch:
            patch.setenv("SPEECHMIX_PREFETCH", mode)
            where = tmp_path / mode
            where.mkdir()
            runs[mode] = _deliver(where, caplog)
        caplog.clear()
    for key in runs[depth][1]:
        assert np.array_equal(runs[depth][1][key], runs["0"][1][key]), key
    assert runs[depth][0].program_lufs == runs["0"][0].program_lufs
