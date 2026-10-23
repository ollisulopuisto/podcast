"""``--events``: jäsennelty edistyminen kuulakselle tekstirivien rinnalla.

kuulaksen BUGS 107: «colab-transcribe should give structured output the same
way podcast-magic does». Sama sopimus kuin automixerissa: lippu, jonka kanssa
jokaisen tapahtuman kohdalla tulostuu tekstirivien lisäksi yksi rivi
``@@kuulas `` ja yksi JSON-olio, heti huuhdeltuna. Ilman lippua mikään ei
muutu.
"""

from __future__ import annotations

import json
import os
import tarfile
import threading

import pytest

from colabtranscribe import __main__ as cli
from colabtranscribe import driver, events
from colabtranscribe.onboarding import OnboardingReport

PREFIX = "@@kuulas "


def _events(out: str) -> list[dict]:
    return [json.loads(x[len(PREFIX):]) for x in out.splitlines() if x.startswith(PREFIX)]


@pytest.fixture(autouse=True)
def _events_off_afterwards():
    yield
    events.enable(False)


# --- Lähetin ------------------------------------------------------------------------


def test_nothing_is_printed_while_events_are_off(capsys):
    events.emit("progress", percent=1, message="x")
    assert capsys.readouterr().out == ""


def test_an_event_is_one_prefixed_json_line_with_schema_and_name(capsys):
    events.enable(True)
    events.emit("session", state="new")
    out = capsys.readouterr().out
    assert out.count("\n") == 1 and out.startswith(PREFIX)
    assert json.loads(out[len(PREFIX):]) == {"schema": 1, "event": "session", "state": "new"}


def test_numbers_json_cannot_hold_become_null(capsys):
    events.enable(True)
    events.emit("progress", percent=float("inf"), message="x")
    (event,) = _events(capsys.readouterr().out)
    assert event["percent"] is None


def test_text_is_kept_as_written_not_escaped(capsys):
    events.enable(True)
    events.emit("warning", message="Istunto katosi → yritetään uudelleen")
    assert "Istunto katosi → yritetään uudelleen" in capsys.readouterr().out


def test_lines_from_many_threads_never_run_into_each_other(capsys):
    events.enable(True)

    def spam(n):
        for i in range(100):
            events.emit("progress", percent=i, message=f"säie {n} " + "x" * 200)

    threads = [threading.Thread(target=spam, args=(n,)) for n in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(_events(capsys.readouterr().out)) == 800


# --- Vaihepolku ---------------------------------------------------------------------


def test_entering_a_stage_closes_the_one_before(capsys):
    events.enable(True)
    trail = events.StageTrail()
    trail.enter("upload")
    trail.enter("run")
    trail.finish()
    got = [(e["stage"], e["state"]) for e in _events(capsys.readouterr().out)]
    assert got == [("upload", "start"), ("upload", "done"), ("run", "start"), ("run", "done")]


def test_the_same_stage_and_index_is_not_announced_twice(capsys):
    events.enable(True)
    trail = events.StageTrail()
    trail.enter("transcribe", index=1, total=2)
    trail.enter("transcribe", index=1, total=2)
    trail.enter("transcribe", index=2, total=2)
    trail.finish()
    got = [(e["state"], e.get("index")) for e in _events(capsys.readouterr().out)]
    assert got == [("start", 1), ("done", 1), ("start", 2), ("done", 2)]


def test_the_trail_knows_where_a_failed_run_stopped(capsys):
    events.enable(True)
    trail = events.StageTrail()
    assert trail.current is None
    trail.enter("download")
    assert trail.current == "download"  # ei suljettu: ajo kaatui tähän
    trail.finish()
    assert trail.current is None


# --- Komentorivi --------------------------------------------------------------------


@pytest.fixture
def audio(tmp_path):
    a, b = tmp_path / "Olli 1.wav", tmp_path / "Panu.mp3"
    a.write_bytes(b"aaa")
    b.write_bytes(b"bbb")
    return a, b, tmp_path / "sanat"


def _args(audio, *extra):
    a, b, out = audio
    return ["--audio", str(a), "--audio", str(b), "--json", str(out), *extra]


@pytest.fixture
def ready(monkeypatch):
    monkeypatch.setattr(cli, "check_environment", lambda: OnboardingReport(items=[]))


def _runner(write=("Olli 1", "Panu"), code=0, progress=(), lines=(), stage=None, enter=()):
    """Tekaistu ajuri: kirjoittaa sanatiedostot kuin lataus olisi tuonut ne."""

    def fake_run(commands, log, timeout=None, on_progress=None, trail=None, **_):
        for step in progress if on_progress else ():
            on_progress(*step)
        for line in lines:
            log(line)
        for name in enter:
            if trail is not None:
                trail.enter(name)
        for command in commands:
            if command[:2] == ["colab", "download"] and code == 0:
                os.makedirs(command[5], exist_ok=True)
                for stem in write:
                    with open(os.path.join(command[5], f"{stem}.words.json"), "w") as f:
                        f.write("{}")
        if trail is not None and code == 0:
            trail.finish()
        return code

    return fake_run


def test_without_the_flag_no_event_line_is_printed(audio, ready, monkeypatch, capsys):
    monkeypatch.setattr(cli.driver, "run", _runner(progress=[(10.0, "a")]))
    assert cli.main(_args(audio, "--progress")) == 0
    assert PREFIX not in capsys.readouterr().out


def test_the_flag_is_in_help_because_kuulas_looks_for_it_there(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    assert "--events" in capsys.readouterr().out


def test_events_need_the_audio_mode(capsys):
    assert cli.main(["--events"]) == 1
    assert "--events" in capsys.readouterr().err


def test_every_line_with_the_prefix_is_json_with_a_schema_and_an_event(
    audio, ready, monkeypatch, capsys
):
    monkeypatch.setattr(cli.driver, "run", _runner(progress=[(10.0, "a"), (50.0, "b")]))
    assert cli.main(_args(audio, "--events")) == 0
    out = capsys.readouterr().out
    got = _events(out)
    assert got and all(e["schema"] == 1 and e["event"] for e in got)
    assert len(got) == sum(x.startswith(PREFIX) for x in out.splitlines())


def test_progress_events_carry_what_progress_lines_would_print_and_need_no_progress_flag(
    audio, ready, monkeypatch, capsys
):
    monkeypatch.setattr(
        cli.driver, "run", _runner(progress=[(10.0, "a"), (5.0, "b"), (150.0, "c")])
    )
    assert cli.main(_args(audio, "--events")) == 0
    out = capsys.readouterr().out
    assert "PROGRESS" not in out  # tekstirivit vain --progress -lipulla
    got = [(e["percent"], e["message"]) for e in _events(out) if e["event"] == "progress"]
    assert got == [(10, "a"), (10, "b"), (100, "c")]  # ei laske, ei ylitä sataa


def test_events_and_progress_lines_can_be_asked_for_together(audio, ready, monkeypatch, capsys):
    monkeypatch.setattr(cli.driver, "run", _runner(progress=[(10.0, "a")]))
    assert cli.main(_args(audio, "--events", "--progress")) == 0
    out = capsys.readouterr().out
    assert "PROGRESS 10 a" in out
    assert [e["percent"] for e in _events(out) if e["event"] == "progress"] == [10]


def test_the_session_event_says_whether_it_is_new_or_reused(audio, ready, monkeypatch, capsys):
    monkeypatch.setattr(cli.driver, "run", _runner())
    monkeypatch.setattr(cli.session, "is_session_alive", lambda name: False)
    cli.main(_args(audio, "--events"))
    assert [e["state"] for e in _events(capsys.readouterr().out) if e["event"] == "session"] == [
        "new"
    ]
    monkeypatch.setattr(cli.session, "is_session_alive", lambda name: True)
    cli.main(_args(audio, "--events"))
    assert [e["state"] for e in _events(capsys.readouterr().out) if e["event"] == "session"] == [
        "reuse"
    ]


def test_a_reset_session_is_announced_as_reset(audio, ready, monkeypatch, capsys):
    monkeypatch.setattr(cli.driver, "run", _runner())
    monkeypatch.setattr(cli.session, "is_session_alive", lambda name: True)
    monkeypatch.setattr(cli.session, "stop_session", lambda name: 0)
    cli.main(_args(audio, "--events", "--reset-session"))
    assert [e["state"] for e in _events(capsys.readouterr().out) if e["event"] == "session"] == [
        "reset"
    ]


def test_the_last_event_is_done_with_the_words_files(audio, ready, monkeypatch, capsys):
    monkeypatch.setattr(cli.driver, "run", _runner())
    assert cli.main(_args(audio, "--events")) == 0
    got = _events(capsys.readouterr().out)
    out_dir = audio[2]
    assert got[-1] == {
        "schema": 1,
        "event": "done",
        "files": [str(out_dir / "Olli 1.words.json"), str(out_dir / "Panu.words.json")],
    }
    assert [e["event"] for e in got].count("done") == 1


def test_a_lost_session_is_a_warning_with_a_code(audio, ready, monkeypatch, capsys):
    line = "Session 'whisper' appears to be lost (the VM was reclaimed)"
    monkeypatch.setattr(cli.driver, "run", _runner(lines=[line]))
    cli.main(_args(audio, "--events"))
    out = capsys.readouterr().out
    assert line in out  # tekstirivi pysyy
    (warning,) = [e for e in _events(out) if e["event"] == "warning"]
    assert warning["code"] == "session_lost" and "appears to be lost" in warning["message"]


def test_a_failed_run_ends_in_an_error_event_with_the_stage_it_stopped_in(
    audio, ready, monkeypatch, capsys
):
    monkeypatch.setattr(cli.driver, "run", _runner(code=3, enter=["upload"]))
    assert cli.main(_args(audio, "--events")) == 3
    got = _events(capsys.readouterr().out)
    assert got[-1] == {
        "schema": 1,
        "event": "error",
        "reason": "failed",
        "code": 3,
        "stage": "upload",
        "message": got[-1]["message"],
    }
    assert "done" not in [e["event"] for e in got]


def test_a_missing_words_file_ends_in_an_error_event_naming_it(audio, ready, monkeypatch, capsys):
    monkeypatch.setattr(cli.driver, "run", _runner(write=("Olli 1",)))
    assert cli.main(_args(audio, "--events")) == 1
    got = _events(capsys.readouterr().out)
    assert got[-1]["event"] == "error" and got[-1]["reason"] == "missing_words"
    assert got[-1]["files"] == [str(audio[2] / "Panu.words.json")]


def test_a_cancel_ends_in_an_error_event_with_reason_cancelled(
    audio, ready, monkeypatch, capsys
):
    monkeypatch.setattr(cli.driver, "run", _runner(code=130))
    monkeypatch.setattr(cli.session, "stop_session", lambda name: 0)
    assert cli.main(_args(audio, "--events")) == 130
    got = _events(capsys.readouterr().out)
    assert got[-1]["event"] == "error" and got[-1]["reason"] == "cancelled"


def test_missing_tools_end_in_an_error_event(audio, monkeypatch, capsys):
    class NotReady:
        is_ready = False

        def summary(self):
            return "colab puuttuu"

    monkeypatch.setattr(cli, "check_environment", lambda: NotReady())
    assert cli.main(_args(audio, "--events")) == 1
    got = _events(capsys.readouterr().out)
    assert got[-1]["event"] == "error" and got[-1]["reason"] == "environment"


# --- Ajuri: vaiheet -----------------------------------------------------------------


def test_the_driver_announces_each_step_and_the_cloud_markers_inside_the_run(
    monkeypatch, capsys
):
    events.enable(True)

    def fake_execute(command, log, timeout=None, on_line=None, **_):
        if command[:2] == ["colab", "download"]:  # ajuri purkaa ladatun paketin
            with tarfile.open(command[5], "w:gz"):
                pass
        if "pipeline.py" in command[-1] and command[1] == "exec":
            for line in (
                "[vaihe 1/4] Asennetaan",
                "[vaihe 2/4 (1/2)] Litteroidaan",
                "[ääni (1/2)] Litteroidaan: a.wav",
                "[ääni (2/2)] Litteroidaan: b.wav",
                "[kohdistus (1/2)] Kohdistetaan: a.wav",
                "[kohdistus (2/2)] Kohdistetaan: b.wav",
            ):
                on_line(line)
        return 0

    monkeypatch.setattr(driver, "_execute_single", fake_execute)
    plan = [
        ["colab", "new", "-s", "s", "--gpu", "T4"],
        ["colab", "exec", "-s", "s", "rm -rf /content/input/* && mkdir -p /content/input"],
        ["colab", "upload", "-s", "s", "x.wav", "/content/input/x.wav"],
        ["colab", "exec", "-s", "s", "python3 /content/pipeline.py --source audio"],
        ["colab", "download", "-s", "s", "/content/output/", "out"],
        ["colab", "stop", "-s", "s"],
    ]
    trail = events.StageTrail()
    assert driver.run(plan, lambda _: None, trail=trail) == 0
    got = [
        (e["stage"], e["state"], e.get("index"), e.get("total"))
        for e in _events(capsys.readouterr().out)
        if e["event"] == "stage"
    ]
    starts = [(s, i, t) for s, st, i, t in got if st == "start"]
    assert starts == [
        ("session", None, None),
        ("prepare", None, None),
        ("upload", None, None),
        ("run", None, None),
        ("install", None, None),
        ("transcribe", 1, 2),
        ("transcribe", 2, 2),
        ("align", 1, 2),
        ("align", 2, 2),
        ("download", None, None),
        ("stop", None, None),
    ]
    # joka alku saa lopun, ja vaiheet eivät ole päällekkäin
    open_now = []
    for stage, state, index, _ in got:
        if state == "start":
            assert not open_now
            open_now.append((stage, index))
        else:
            assert open_now == [(stage, index)]
            open_now.clear()
    assert not open_now


def test_a_driver_without_a_trail_behaves_as_before(monkeypatch):
    monkeypatch.setattr(driver, "_execute_single", lambda *a, **k: 0)
    assert driver.run([["colab", "stop", "-s", "s"]], lambda _: None) == 0
