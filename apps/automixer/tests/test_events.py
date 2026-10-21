"""``--events``: live, structured progress for a host (kuulas), next to the text.

The text lines stay as they are; with the flag, one extra line per event is
printed on stdout, ``@@kuulas `` and one JSON object. Spec: kuulas
``docs/PODCAST-MAGIC.md``, "Live events".
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import shutil
import threading

import pytest
from test_stems_folder import _folder

from automixer import cli_mix, events, stems_mix
from speechmix.blocks import Block, Loud

PREFIX = "@@kuulas "


def _events(out: str) -> list[dict]:
    return [json.loads(x[len(PREFIX) :]) for x in out.splitlines() if x.startswith(PREFIX)]


@pytest.fixture(autouse=True)
def _events_off_afterwards():
    yield
    events.enable(False)


# ---- the emitter -------------------------------------------------------------


def test_nothing_is_printed_while_events_are_off(capsys):
    events.emit("progress", percent=1, message="x")
    assert capsys.readouterr().out == ""


def test_an_event_is_one_prefixed_json_line_with_schema_and_name(capsys):
    events.enable(True)
    events.emit("bed", loudest_lufs=-24.5, offset_db=1.0)
    out = capsys.readouterr().out
    assert out.count("\n") == 1 and out.startswith(PREFIX)
    assert json.loads(out[len(PREFIX) :]) == {
        "schema": 1,
        "event": "bed",
        "loudest_lufs": -24.5,
        "offset_db": 1.0,
    }


def test_numbers_json_cannot_hold_become_null(capsys):
    events.enable(True)
    events.emit("balance", limit_db=float("inf"), lufs=float("nan"), applied_db=-1.0)
    (event,) = _events(capsys.readouterr().out)
    assert event["limit_db"] is None and event["lufs"] is None
    assert event["applied_db"] == -1.0


def test_text_is_kept_as_written_not_escaped(capsys):
    events.enable(True)
    events.emit("warning", message="Pääeditio → P1")
    assert "Pääeditio → P1" in capsys.readouterr().out


def test_lines_from_many_threads_never_run_into_each_other(capsys):
    events.enable(True)

    def spam(n):
        for i in range(100):
            events.emit("progress", percent=i, message=f"thread {n} " + "x" * 200)

    threads = [threading.Thread(target=spam, args=(n,)) for n in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(_events(capsys.readouterr().out)) == 800


def test_the_trail_announces_the_next_stage_when_one_is_done(capsys):
    events.enable(True)
    trail = events.StageTrail("P0", ["read", "debleed", "write"])
    trail.begin()
    trail.reached("read")
    trail.reached("debleed")
    trail.reached("write")
    got = [(e["stage"], e["state"]) for e in _events(capsys.readouterr().out)]
    assert got == [
        ("read", "start"),
        ("read", "done"),
        ("debleed", "start"),
        ("debleed", "done"),
        ("write", "start"),
        ("write", "done"),
    ]


def test_a_skipped_stage_is_said_so_and_the_next_one_starts(capsys):
    events.enable(True)
    trail = events.StageTrail("P0", ["read", "debleed", "write"], skipped={"debleed"})
    trail.begin()
    trail.reached("read")
    trail.reached("debleed")
    trail.reached("write")
    got = [(e["stage"], e["state"]) for e in _events(capsys.readouterr().out)]
    assert got == [
        ("read", "start"),
        ("read", "done"),
        ("debleed", "skipped"),
        ("write", "start"),
        ("write", "done"),
    ]


# ---- real mixes ----------------------------------------------------------------


def _run(tmp_path, **options):
    folder = _folder(tmp_path, **{k: options.pop(k) for k in ("bed",) if k in options})
    out, text = tmp_path / "out.wav", io.StringIO()
    with contextlib.redirect_stdout(text):
        stems_mix.mix_folder(str(folder), str(out), target_lufs=-16.0, **options)
    return str(out), text.getvalue()


@pytest.fixture(scope="module")
def with_bed(tmp_path_factory):
    out, text = _run(tmp_path_factory.mktemp("bed"), events=True)
    return out, text, _events(text)


@pytest.fixture(scope="module")
def limited(tmp_path_factory):
    out, text = _run(
        tmp_path_factory.mktemp("limit"), bed=False, events=True, balance_speakers_max_db=4.0
    )
    return out, text, _events(text)


@pytest.fixture(scope="module")
def without_events(tmp_path_factory):
    return _run(tmp_path_factory.mktemp("off"))


def test_every_line_with_the_prefix_is_json_with_a_schema_and_an_event(with_bed):
    _, text, got = with_bed
    assert got and all(e["schema"] == 1 and e["event"] for e in got)
    assert len(got) == sum(x.startswith(PREFIX) for x in text.splitlines())


def test_the_text_lines_are_all_still_there(with_bed, without_events):
    def plain(text):
        # Not the same between two runs: the paths, the free disk space and,
        # with the tracks on threads, which track's line comes first.
        lines = [x for x in text.splitlines() if not x.startswith(PREFIX)]
        lines = [re.sub(r"→ .*$", "→ PATH", x) for x in lines]
        return sorted(re.sub(r"[\d.]+ GB free", "N GB free", x) for x in lines)

    assert plain(with_bed[1]) == plain(without_events[1])


def test_without_the_flag_no_event_line_is_printed(without_events):
    assert PREFIX not in without_events[1]


def test_progress_events_carry_what_progress_would_print(with_bed):
    got = [e for e in with_bed[2] if e["event"] == "progress"]
    assert got[0]["percent"] == 5 and got[-1] == {
        "schema": 1,
        "event": "progress",
        "percent": 100,
        "message": "done",
    }
    percents = [e["percent"] for e in got]
    assert percents == sorted(percents)


def test_each_speech_track_announces_itself_with_index_and_total(with_bed):
    got = [e for e in with_bed[2] if e["event"] == "track"]
    assert sorted((e["index"], e["total"], e["name"]) for e in got) == [
        (1, 2, "P0"),
        (2, 2, "P1"),
    ]


def test_stages_start_and_finish_in_order_for_every_track(with_bed):
    order = ["read", "debleed", "cleanup", "measure", "dynamics", "lag", "duck", "write"]
    for name in ("P0", "P1"):
        seq = [
            (e["stage"], e["state"])
            for e in with_bed[2]
            if e["event"] == "stage" and e["track"] == name
        ]
        expected = []
        for stage in order:
            expected += [(stage, "start"), (stage, "done")]
        assert seq == expected


def test_a_stage_is_announced_before_it_is_printed_as_done(with_bed):
    lines = with_bed[1].splitlines()
    start = next(
        i
        for i, x in enumerate(lines)
        if x.startswith(PREFIX) and '"cleanup"' in x and '"start"' in x and '"P0"' in x
    )
    done = next(i for i, x in enumerate(lines) if x.startswith("[automixer]   P0: cleanup"))
    assert start < done


def test_debleed_switched_off_is_announced_as_skipped(tmp_path):
    _, text = _run(tmp_path, events=True, debleed=False)
    got = [e for e in _events(text) if e["event"] == "stage" and e["stage"] == "debleed"]
    assert got and all(e["state"] == "skipped" for e in got)


def test_the_bed_event_says_what_the_beds_line_says(with_bed):
    (event,) = [e for e in with_bed[2] if e["event"] == "bed"]
    line = next(x for x in with_bed[1].splitlines() if x.startswith("[automixer] beds:"))
    assert f"{event['loudest_lufs']:.1f}" in line and f"{event['offset_db']:+.1f}" in line
    assert event["offset_db"] == 1.0


def test_the_balance_events_say_what_the_balance_line_says(with_bed):
    got = [e for e in with_bed[2] if e["event"] == "balance"]
    assert sorted(e["track"] for e in got) == ["P0", "P1"]
    line = next(x for x in with_bed[1].splitlines() if x.startswith("[automixer] balance:"))
    for e in got:
        assert f"{e['track']} {e['lufs']:.1f} LUFS → {e['applied_db'] + 0.0:+.1f} dB" in line
        assert e["limit_db"] is None


def test_a_balance_limit_is_in_the_event(limited):
    got = [e for e in limited[2] if e["event"] == "balance"]
    assert got and all(e["limit_db"] == 4.0 for e in got)
    assert all(abs(e["applied_db"]) <= 4.0 + 1e-9 for e in got)


def test_the_mastered_event_says_what_the_mastered_line_says(with_bed):
    (event,) = [e for e in with_bed[2] if e["event"] == "mastered"]
    line = next(x for x in with_bed[1].splitlines() if x.startswith("[automixer] mastered:"))
    assert f"{event['lufs']:.1f} LUFS" in line
    assert f"lift {event['lift_db']:+.1f} dB" in line
    assert f"limiting {event['limiting_lu']:.1f} LU" in line


def test_the_last_event_is_done_with_the_path_of_the_mix(with_bed):
    out, _, got = with_bed
    assert got[-1] == {"schema": 1, "event": "done", "path": out}


def test_notes_from_the_loader_become_warnings(tmp_path):
    from automixer import stem_folder

    def loader(path, workdir):
        loaded = stem_folder.load(path, workdir)
        loaded.notes.append("something odd")
        return loaded

    folder = _folder(tmp_path, bed=False)
    text = io.StringIO()
    with contextlib.redirect_stdout(text):
        stems_mix.mix(
            str(folder), str(tmp_path / "o.wav"), target_lufs=-16.0, loader=loader, events=True
        )
    got = [e for e in _events(text.getvalue()) if e["event"] == "warning"]
    assert got == [{"schema": 1, "event": "warning", "message": "something odd"}]


def test_blocks_and_loud_spans_are_events_in_seconds(tmp_path, monkeypatch):
    found = {"P0": [Block(10.0, 20.0, 8.0, -30.0, 2.5, 2.5)], "P1": []}
    loud = {"P0": [Loud(30.0, 32.0, 4.5)], "P1": []}
    monkeypatch.setattr(stems_mix, "review", lambda speech, lanes: (found, loud))
    monkeypatch.setattr(stems_mix, "level_blocks", lambda src, dst, blocks: shutil.copy(src, dst))
    _, text = _run(tmp_path, events=True)
    got = [e for e in _events(text) if e["event"] in ("block", "loud")]
    assert got == [
        {"schema": 1, "event": "loud", "track": "P0", "start_s": 30.0, "end_s": 32.0,
         "excess_db": 4.5},
        {"schema": 1, "event": "block", "track": "P0", "start_s": 10.0, "end_s": 20.0,
         "deviation_db": 2.5, "gain_db": 2.5},
    ]


# ---- the command line ------------------------------------------------------------


def _cli(monkeypatch, *argv):
    monkeypatch.setattr("sys.argv", ["automixer", *argv])
    cli_mix.main()


def test_the_flag_is_in_help_because_kuulas_looks_for_it_there(monkeypatch, capsys):
    with pytest.raises(SystemExit):
        _cli(monkeypatch, "--help")
    assert re.search(r"--events\b", capsys.readouterr().out)


def test_the_flag_reaches_the_mix_and_defaults_to_off(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(cli_mix, "_exit_on_sigterm", lambda: None)
    monkeypatch.setattr(stems_mix, "mix", lambda path, output, **kw: seen.append(kw))
    _cli(monkeypatch, str(tmp_path / "jakso.nhsx"))
    _cli(monkeypatch, str(tmp_path / "jakso.nhsx"), "--events")
    assert [kw["events"] for kw in seen] == [False, True]
