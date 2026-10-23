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
    from colabtranscribe.onboarding import OnboardingItem

    class NotReady:
        is_ready = False
        items = [OnboardingItem("colab", "Colab CLI", False, "ei asennettu", "Asenna se")]

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


# --- Kuulaksen toiveet 2026-10-23 -----------------------------------------------------
# docs/PODCAST-MAGIC.md (kuulas): nimi vaiheeseen, siirron tapa ja tavut, Colab CLI:n
# päivitysilmoitukset pois edistymisestä, kadonneen istunnon korjaus työkalun sisällä ja
# yksi lyhyt virherivi.


def _stages(out: str, stage: str) -> list[dict]:
    return [e for e in _events(out) if e["event"] == "stage" and e["stage"] == stage]


def test_transcribe_and_align_stages_carry_the_audio_file_name(monkeypatch, capsys):
    events.enable(True)

    def fake_execute(command, log, timeout=None, on_line=None, **_):
        if command[:2] == ["colab", "exec"] and "pipeline.py" in command[-1]:
            on_line("[ääni (1/2)] Litteroidaan: Take 1-Mic.wav")
            on_line("[ääni (2/2)] Litteroidaan: Panu.mp3")
            on_line("[kohdistus (1/2)] /content/input/Take 1-Mic.wav")
            on_line("[kohdistus (2/2)] /content/input/Panu.mp3")
        return 0

    monkeypatch.setattr(driver, "_execute_single", fake_execute)
    plan = [["colab", "exec", "-s", "s", "python3 /content/pipeline.py --source audio"]]
    assert driver.run(plan, lambda _: None, trail=events.StageTrail()) == 0
    out = capsys.readouterr().out
    for stage in ("transcribe", "align"):
        got = [(e["state"], e["index"], e["name"]) for e in _stages(out, stage)]
        assert got == [
            ("start", 1, "Take 1-Mic.wav"),
            ("done", 1, "Take 1-Mic.wav"),
            ("start", 2, "Panu.mp3"),
            ("done", 2, "Panu.mp3"),
        ], stage


def test_an_upload_stage_names_the_file_says_how_and_how_many_bytes(
    tmp_path, monkeypatch, capsys
):
    events.enable(True)
    source = tmp_path / "Take 1-Mic.wav"
    source.write_bytes(b"x" * 1234)
    monkeypatch.setattr(driver, "_execute_single", lambda *a, **k: 0)
    plan = [["colab", "upload", "-s", "s", str(source), "/content/input/Take 1-Mic.wav"]]
    assert driver.run(plan, lambda _: None, trail=events.StageTrail()) == 0
    start, done = _stages(capsys.readouterr().out, "upload")
    assert (start["state"], start["name"], start["via"], start["total"]) == (
        "start", "Take 1-Mic.wav", "direct", 1234
    )
    assert (done["state"], done["name"], done["via"], done["total"], done["done"]) == (
        "done", "Take 1-Mic.wav", "direct", 1234, 1234
    )


def test_each_uploaded_file_is_its_own_upload_stage(tmp_path, monkeypatch, capsys):
    events.enable(True)
    names = ["a.wav", "b.mp3"]
    for n in names:
        (tmp_path / n).write_bytes(b"xx")
    monkeypatch.setattr(driver, "_execute_single", lambda *a, **k: 0)
    plan = [["colab", "upload", "-s", "s", str(tmp_path / n), f"/content/input/{n}"] for n in names]
    driver.run(plan, lambda _: None, trail=events.StageTrail())
    got = _stages(capsys.readouterr().out, "upload")
    assert [e["name"] for e in got if e["state"] == "start"] == names


def test_a_file_already_on_the_vm_is_not_announced_as_an_upload(tmp_path, monkeypatch, capsys):
    events.enable(True)
    source = tmp_path / "a.wav"
    source.write_bytes(b"xx")
    remote = "/content/cache/xyz"
    monkeypatch.setattr(driver, "_list_cache", lambda session, log, timeout: {remote})
    monkeypatch.setattr(driver, "_execute_single", lambda *a, **k: 0)
    plan = [
        ["cache-list", "s"],
        ["chunked-upload", "s", str(source), remote],
    ]
    driver.run(plan, lambda _: None, trail=events.StageTrail())
    assert _stages(capsys.readouterr().out, "upload") == []


def test_a_big_file_reports_bytes_after_every_chunk(tmp_path, monkeypatch, capsys):
    events.enable(True)
    source = tmp_path / "Big.wav"
    source.write_bytes(b"x" * 25)
    monkeypatch.setattr(driver, "CHUNK_BYTES", 10)
    monkeypatch.setattr(driver, "_execute_single", lambda *a, **k: 0)
    plan = [["chunked-upload", "s", str(source), "/content/input/Big.wav"]]
    driver.run(plan, lambda _: None, trail=events.StageTrail())
    got = [
        (e["name"], e["via"], e["done"], e["total"])
        for e in _events(capsys.readouterr().out)
        if e["event"] == "transfer"
    ]
    assert got == [("Big.wav", "direct", 10, 25), ("Big.wav", "direct", 20, 25),
                   ("Big.wav", "direct", 25, 25)]


def test_a_packed_big_file_reports_bytes_of_the_original_file(tmp_path, monkeypatch, capsys):
    """FLACina lähetettäessä lukua ei pidä näyttää eri yksiköissä: tavut ovat
    alkuperäisen tiedoston, jotta ``done`` ja ``total`` kuuluvat yhteen."""
    import numpy as np
    import soundfile as sf

    events.enable(True)
    source = tmp_path / "Take.wav"
    sf.write(source, np.random.default_rng(1).normal(0, 0.1, 48000).astype("float32"), 48000,
             subtype="PCM_24")
    size = source.stat().st_size
    monkeypatch.setattr(driver, "CHUNK_ABOVE", 1)   # pakattukin menee paloina
    monkeypatch.setattr(driver, "CHUNK_BYTES", 5000)
    monkeypatch.setattr(driver, "_execute_single", lambda *a, **k: 0)
    plan = [["flac-upload", "s", str(source), "/content/input/Take.wav"]]
    assert driver.run(plan, lambda _: None, trail=events.StageTrail()) == 0
    got = [e for e in _events(capsys.readouterr().out) if e["event"] == "transfer"]
    assert len(got) >= 2
    assert all(e["total"] == size for e in got)
    done = [e["done"] for e in got]
    assert done == sorted(done) and done[-1] == size


def test_a_drive_upload_says_via_drive(monkeypatch, capsys):
    events.enable(True)
    monkeypatch.setattr(driver, "upload_input_to_drive", lambda *a, **k: None)
    monkeypatch.setattr(driver, "_execute_single", lambda *a, **k: 0)
    plan = [["drive", "upload", "/in", "ColabTranscribe/s/input.tar"]]
    driver.run(plan, lambda _: None, trail=events.StageTrail())
    (start, _done) = _stages(capsys.readouterr().out, "upload")
    assert start["via"] == "drive"


NOTICE = "[colab] A new version of Colab CLI is available (0.9 -> 0.10)"
NOTICES = [
    NOTICE,
    "[colab] Run 'colab update' to upgrade",
    "[colab] To silence this check, set COLAB_NO_UPDATE_CHECK=1",
]


def test_colab_update_notices_become_one_warning_and_stay_out_of_progress(
    audio, ready, monkeypatch, capsys
):
    monkeypatch.setattr(
        cli.driver, "run", _runner(progress=[(10.0, NOTICE), (20.0, "b")], lines=NOTICES)
    )
    assert cli.main(_args(audio, "--events", "--progress")) == 0
    out = capsys.readouterr().out
    assert all(line in out for line in NOTICES)  # tekstirivit pysyvät
    got = _events(out)
    (warning,) = [e for e in got if e["event"] == "warning"]
    assert warning["code"] == "colab_update" and "new version" in warning["message"]
    messages = [e["message"] for e in got if e["event"] == "progress"]
    assert messages == ["b"] and not any("[colab]" in m for m in messages)
    assert "PROGRESS 10" not in out  # ei myöskään tekstiriveillä


def _flaky(first_code=1, line="Session 'whisper' appears to be lost", then=0, plans=None):
    """Tekaistu ajuri: ensimmäinen ajo kaatuu kadonneeseen istuntoon."""
    calls = {"n": 0}

    def fake_run(commands, log, timeout=None, on_progress=None, trail=None, **_):
        calls["n"] += 1
        if plans is not None:
            plans.append(commands)
        if calls["n"] == 1:
            log(line)
            if trail is not None:
                trail.enter("run")
            return first_code
        for command in commands:
            if command[:2] == ["colab", "download"] and then == 0:
                os.makedirs(command[5], exist_ok=True)
                for stem in ("Olli 1", "Panu"):
                    with open(os.path.join(command[5], f"{stem}.words.json"), "w") as f:
                        f.write("{}")
        if trail is not None and then == 0:
            trail.finish()
        return then

    return fake_run, calls


def test_a_lost_session_is_reset_and_the_run_retried_once_inside_the_tool(
    audio, ready, monkeypatch, capsys
):
    plans, stopped = [], []
    fake, calls = _flaky(plans=plans)
    monkeypatch.setattr(cli.driver, "run", fake)
    monkeypatch.setattr(cli.session, "is_session_alive", lambda name: True)
    monkeypatch.setattr(cli.session, "stop_session", lambda name: stopped.append(name) or 0)
    assert cli.main(_args(audio, "--events")) == 0
    assert calls["n"] == 2 and stopped == ["whisper"]
    assert plans[0][0][:2] != ["colab", "new"]      # ensimmäinen ajo käytti vanhaa istuntoa
    assert plans[1][0][:2] == ["colab", "new"]      # toinen luo tuoreen
    got = _events(capsys.readouterr().out)
    sessions = [(e["state"], e.get("reason")) for e in got if e["event"] == "session"]
    assert sessions == [("reuse", None), ("reset", "lost")]
    assert got[-1]["event"] == "done" and "error" not in [e["event"] for e in got]
    assert [e["code"] for e in got if e["event"] == "warning"] == ["session_lost"]


def test_the_recovery_is_said_in_the_text_too_and_works_without_events(
    audio, ready, monkeypatch, capsys
):
    fake, calls = _flaky()
    monkeypatch.setattr(cli.driver, "run", fake)
    monkeypatch.setattr(cli.session, "stop_session", lambda name: 0)
    assert cli.main(_args(audio)) == 0
    out = capsys.readouterr().out
    assert calls["n"] == 2 and PREFIX not in out and "uudelleen" in out


def test_a_second_loss_is_not_retried_again(audio, ready, monkeypatch, capsys):
    calls = {"n": 0}

    def always_lost(commands, log, timeout=None, **_):
        calls["n"] += 1
        log("Session 'whisper' appears to be lost")
        return 1

    monkeypatch.setattr(cli.driver, "run", always_lost)
    monkeypatch.setattr(cli.session, "stop_session", lambda name: 0)
    assert cli.main(_args(audio, "--events")) == 1
    assert calls["n"] == 2
    got = _events(capsys.readouterr().out)
    assert got[-1]["event"] == "error" and got[-1]["reason"] == "failed"
    assert [e["state"] for e in got if e["event"] == "session"].count("reset") == 1


def test_a_cancel_or_another_failure_is_not_retried(audio, ready, monkeypatch):
    for code, line in ((130, "Session 'whisper' appears to be lost"), (1, "jokin muu meni vikaan")):
        fake, calls = _flaky(first_code=code, line=line)
        monkeypatch.setattr(cli.driver, "run", fake)
        monkeypatch.setattr(cli.session, "stop_session", lambda name: 0)
        assert cli.main(_args(audio)) == code
        assert calls["n"] == 1, (code, line)


def test_error_messages_are_one_short_line_never_the_log(audio, ready, monkeypatch, capsys):
    from colabtranscribe.onboarding import OnboardingItem, OnboardingReport

    cases = []
    monkeypatch.setattr(cli.driver, "run", _runner(code=3, enter=["upload"]))
    cli.main(_args(audio, "--events"))
    cases.append(_events(capsys.readouterr().out)[-1])
    monkeypatch.setattr(cli.driver, "run", _runner(write=()))
    cli.main(_args(audio, "--events"))
    cases.append(_events(capsys.readouterr().out)[-1])
    item = OnboardingItem("colab", "Colab CLI", False, "ei asennettu",
                          "Asenna:\n  uv tool install google-colab-cli\n  colab usage")
    monkeypatch.setattr(cli, "check_environment", lambda: OnboardingReport(items=[item]))
    cli.main(_args(audio, "--events"))
    cases.append(_events(capsys.readouterr().out)[-1])
    assert [c["reason"] for c in cases] == ["failed", "missing_words", "environment"]
    for case in cases:
        assert case["event"] == "error"
        assert "\n" not in case["message"] and 0 < len(case["message"]) <= 200, case
    assert "uv tool install" not in cases[2]["message"] and "Colab CLI" in cases[2]["message"]


def test_a_very_long_message_is_cut_to_one_line(capsys):
    events.enable(True)
    from colabtranscribe.__main__ import _failure

    _failure("failed", "rivi yksi\nrivi kaksi   " + "x" * 500)
    (error,) = _events(capsys.readouterr().out)
    assert "\n" not in error["message"] and len(error["message"]) <= 200
    assert error["message"].startswith("rivi yksi rivi kaksi")
