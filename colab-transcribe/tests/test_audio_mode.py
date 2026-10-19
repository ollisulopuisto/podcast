"""Pelkkä ääni sisään, sanat ulos: ``--audio`` ja ``--json``, ilman ``.nhsx``:ää.

Sopimus on ``docs/KUULAS-COLAB.md``: kuulas kutsuu tätä suoraan, joten
tulostiedoston muoto (``<nimi>.words.json``), edistymisrivit (``PROGRESS
<0-100> <viesti>``), poistumiskoodit ja SIGTERM ovat sen rajapinta eikä
sisäinen yksityiskohta.
"""

from __future__ import annotations

import json
import os
import signal

import pytest

from colabtranscribe import __main__ as cli
from colabtranscribe.colab import pipeline
from colabtranscribe.onboarding import OnboardingItem, OnboardingReport
from colabtranscribe.options import RunOptions, pipeline_args

# --- Asetukset -----------------------------------------------------------------


def test_audio_is_a_source_and_its_arguments_reach_the_script():
    args = pipeline_args(RunOptions(source="audio"))
    assert args[args.index("--source") + 1] == "audio"
    assert args[args.index("--model") + 1] == "turbo"
    assert args[args.index("--language") + 1] == "fi"


def test_model_and_language_are_passed_on():
    args = pipeline_args(RunOptions(source="audio", model="large-v3", language="en"))
    assert args[args.index("--model") + 1] == "large-v3"
    assert args[args.index("--language") + 1] == "en"


def test_the_nhsx_modes_do_not_get_model_arguments():
    assert "--model" not in pipeline_args(RunOptions())
    assert "--language" not in pipeline_args(RunOptions(source="downmix"))


def test_an_empty_model_or_language_is_refused():
    with pytest.raises(ValueError, match="model"):
        RunOptions(source="audio", model="")
    with pytest.raises(ValueError, match="language"):
        RunOptions(source="audio", language="")


# --- Sanatiedosto ----------------------------------------------------------------


def _raw(*words):
    return {
        "segments": [{"words": [{"word": w, "start": s, "end": e} for w, s, e in words]}]
    }


def test_the_document_has_the_contracts_fields():
    doc = pipeline.words_document(_raw((" moi", 1.0, 1.4)), "fi")
    assert doc == {
        "version": 1,
        "timing": "whisper",
        "language": "fi",
        "rejected": 0,
        "words": [{"w": "moi", "s": 1.0, "e": 1.4}],
    }


def test_words_are_in_time_order_whatever_order_whisper_gave():
    doc = pipeline.words_document(_raw(("b", 2.0, 2.5), ("a", 1.0, 1.5)), "fi")
    assert [w["w"] for w in doc["words"]] == ["a", "b"]


def test_an_overlap_shortens_the_preceding_word_not_the_next():
    doc = pipeline.words_document(_raw(("a", 1.0, 2.0), ("b", 1.5, 2.5)), "fi")
    a, b = doc["words"]
    assert (a["s"], a["e"]) == (1.0, 1.5)
    assert (b["s"], b["e"]) == (1.5, 2.5)


def test_a_zero_length_word_gets_a_twenty_millisecond_floor():
    doc = pipeline.words_document(_raw(("a", 1.0, 1.0)), "fi")
    assert doc["words"][0]["e"] == pytest.approx(1.02)


def test_no_word_ends_before_it_starts_even_when_starts_nearly_coincide():
    doc = pipeline.words_document(_raw(("a", 1.0, 1.5), ("b", 1.005, 1.5)), "fi")
    assert all(w["e"] > w["s"] for w in doc["words"])


def test_times_are_rounded_to_milliseconds():
    doc = pipeline.words_document(_raw(("a", 1.0006, 1.40051)), "fi")
    assert doc["words"][0] == {"w": "a", "s": 1.001, "e": 1.401}


def test_words_without_text_or_times_are_left_out():
    raw = {
        "segments": [
            {
                "words": [
                    {"word": "  ", "start": 1.0, "end": 1.2},
                    {"word": "ei aikaa"},
                    {"word": "joo", "start": "x", "end": 2.0},
                    {"word": "niin", "start": 3.0, "end": 3.2},
                ]
            },
            {"text": "ei sanoja"},
        ]
    }
    assert [w["w"] for w in pipeline.words_document(raw, "fi")["words"]] == ["niin"]


# --- Pilvessä ajettava puoli -------------------------------------------------------


def _fake_transcribe(words_by_name):
    def transcribe(path, model, language, prompt):
        transcribe.calls.append((os.path.basename(path), model, language, prompt))
        return _raw(*words_by_name.get(os.path.basename(path), []))

    transcribe.calls = []
    return transcribe


def test_run_audio_writes_one_words_file_per_audio_file(tmp_path, monkeypatch, capsys):
    (tmp_path / "in").mkdir()
    for name in ("Olli 1.wav", "Panu.mp3"):
        (tmp_path / "in" / name).write_bytes(b"x")
    fake = _fake_transcribe(
        {"Olli 1.wav": [("moi", 1.0, 1.3)], "Panu.mp3": [("hei", 2.0, 2.2)]}
    )
    monkeypatch.setattr(pipeline, "transcribe_file", fake)
    pipeline.run_audio(str(tmp_path / "in"), str(tmp_path / "out"), "turbo", "fi", "p")
    out = tmp_path / "out"
    assert sorted(p.name for p in out.iterdir()) == [
        "Olli 1.words.json",
        "Panu.words.json",
    ]
    doc = json.loads((out / "Olli 1.words.json").read_text(encoding="utf-8"))
    assert doc["words"][0]["w"] == "moi" and doc["language"] == "fi"
    assert {c[1:] for c in fake.calls} == {("turbo", "fi", "p")}
    assert "Sanat luotu:" in capsys.readouterr().out


def test_run_audio_announces_each_file_with_its_position(tmp_path, monkeypatch, capsys):
    (tmp_path / "in").mkdir()
    for name in ("a.wav", "b.wav"):
        (tmp_path / "in" / name).write_bytes(b"x")
    monkeypatch.setattr(pipeline, "transcribe_file", _fake_transcribe({}))
    pipeline.run_audio(str(tmp_path / "in"), str(tmp_path / "out"), "turbo", "fi", "")
    printed = capsys.readouterr().out
    assert "[ääni (1/2)]" in printed and "[ääni (2/2)]" in printed


def test_a_file_with_no_words_writes_nothing_and_says_so(tmp_path, monkeypatch, capsys):
    (tmp_path / "in").mkdir()
    (tmp_path / "in" / "hiljaa.wav").write_bytes(b"x")
    monkeypatch.setattr(pipeline, "transcribe_file", _fake_transcribe({}))
    pipeline.run_audio(str(tmp_path / "in"), str(tmp_path / "out"), "turbo", "fi", "")
    assert list((tmp_path / "out").glob("*.words.json")) == []
    assert "VAROITUS" in capsys.readouterr().out


def test_run_audio_without_audio_fails_loudly(tmp_path):
    (tmp_path / "in").mkdir()
    with pytest.raises(RuntimeError, match="ääni"):
        pipeline.run_audio(str(tmp_path / "in"), str(tmp_path / "out"), "turbo", "fi", "")


def test_transcribe_file_asks_whisper_for_the_chosen_model_and_language(
    monkeypatch, tmp_path
):
    seen = {}

    def fake_run(cmd, check, timeout):
        seen["cmd"] = cmd
        out = cmd[cmd.index("--output_dir") + 1]
        with open(os.path.join(out, "puhe.json"), "w", encoding="utf-8") as f:
            json.dump(_raw(("moi", 1.0, 1.2)), f)

    monkeypatch.setattr(pipeline.subprocess, "run", fake_run)
    data = pipeline.transcribe_file(str(tmp_path / "puhe.wav"), "large-v3", "en", "täyte")
    cmd = seen["cmd"]
    assert cmd[cmd.index("--model") + 1] == "large-v3"
    assert cmd[cmd.index("--language") + 1] == "en"
    assert cmd[cmd.index("--initial_prompt") + 1] == "täyte"
    assert cmd[cmd.index("--word_timestamps") + 1] == "True"
    assert cmd[cmd.index("--output_format") + 1] == "json"
    assert data["segments"][0]["words"][0]["word"] == "moi"


def test_main_audio_runs_only_the_audio_step(monkeypatch):
    import sys

    def boom(*a, **k):
        raise AssertionError("nhsx-ketju ajettiin")

    called = []
    monkeypatch.setattr(
        sys,
        "argv",
        ["pipeline.py", "--source", "audio", "--model", "large-v3", "--language", "en"],
    )
    monkeypatch.setattr(pipeline.os, "makedirs", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "install_dependencies", lambda: None)
    monkeypatch.setattr(pipeline, "run_audio", lambda *a: called.append(a))
    for name in (
        "run_transcription",
        "inject_transcriptions_to_nhsx",
        "run_auto_silence",
        "write_script",
        "run_downmix",
    ):
        monkeypatch.setattr(pipeline, name, boom)
    pipeline.main()
    assert called[0][:4] == ("/content/input", "/content/output", "large-v3", "en")


# --- Komentorivi: suunnitelma ---------------------------------------------------------


@pytest.fixture
def audio(tmp_path):
    a, b = tmp_path / "Olli 1.wav", tmp_path / "Panu.mp3"
    a.write_bytes(b"aaa")
    b.write_bytes(b"bbb")
    return a, b, tmp_path / "sanat"


def _args(audio, *extra):
    a, b, out = audio
    return ["--audio", str(a), "--audio", str(b), "--json", str(out), *extra]


def test_dry_run_plans_a_direct_upload_and_a_download_to_the_json_folder(audio, capsys):
    assert cli.main(_args(audio, "--dry-run")) == 0
    out = capsys.readouterr().out
    assert "colab new" in out
    assert "colab upload" in out and "Olli 1.wav" in out and "Panu.mp3" in out
    assert "--source audio" in out
    assert f"colab download -s whisper /content/output/ {audio[2]}" in out
    assert "colab stop" in out


def test_the_audio_plan_never_touches_drive_or_the_nhsx_helpers(audio, capsys):
    cli.main(_args(audio, "--dry-run"))
    out = capsys.readouterr().out
    assert "drive" not in out.lower().replace("--transfer", "")
    assert "silencelearn" not in out


def test_every_audio_file_lands_in_the_input_folder_by_its_own_name(audio, capsys):
    cli.main(_args(audio, "--dry-run"))
    out = capsys.readouterr().out
    assert "/content/input/Olli 1.wav" in out.replace("'", "")
    assert "/content/input/Panu.mp3" in out.replace("'", "")


def test_model_and_language_flags_reach_the_planned_command(audio, capsys):
    cli.main(_args(audio, "--model", "large-v3", "--language", "en", "--dry-run"))
    out = capsys.readouterr().out
    assert "--model large-v3" in out and "--language en" in out


def test_keep_session_leaves_the_session_running(audio, capsys):
    cli.main(_args(audio, "--keep-session", "--dry-run"))
    assert "colab stop" not in capsys.readouterr().out


def test_an_existing_session_is_reused_not_recreated(audio, capsys, monkeypatch):
    monkeypatch.setattr(cli.session, "is_session_alive", lambda name: True)
    cli.main(_args(audio, "--dry-run"))
    assert "colab new" not in capsys.readouterr().out


# --- Komentorivi: kieltäytymiset ----------------------------------------------------------


def _refused(argv, capsys, word):
    assert cli.main(argv) == 1
    err = capsys.readouterr().err
    assert word in err
    return err


def test_audio_without_a_json_folder_is_refused(audio, capsys):
    _refused(["--audio", str(audio[0])], capsys, "--json")


def test_json_without_audio_is_refused(audio, capsys):
    _refused(
        ["--json", str(audio[2]), "--input", str(audio[0].parent)], capsys, "--audio"
    )


def test_audio_and_input_cannot_be_combined(audio, capsys):
    _refused(_args(audio, "--input", str(audio[0].parent)), capsys, "--input")


def test_a_missing_audio_file_is_named(audio, capsys):
    _refused(
        ["--audio", "/eiole/puhe.wav", "--json", str(audio[2])], capsys, "/eiole/puhe.wav"
    )


def test_two_files_with_the_same_stem_are_refused(tmp_path, capsys):
    (tmp_path / "x").mkdir()
    (tmp_path / "y").mkdir()
    one, two = tmp_path / "x" / "puhe.wav", tmp_path / "y" / "puhe.mp3"
    one.write_bytes(b"1")
    two.write_bytes(b"2")
    _refused(
        ["--audio", str(one), "--audio", str(two), "--json", str(tmp_path / "o")],
        capsys,
        "puhe",
    )


def test_drive_transfer_is_refused_in_this_mode(audio, capsys):
    _refused(_args(audio, "--transfer", "drive"), capsys, "Drive")


# --- Komentorivi: ajo ---------------------------------------------------------------------


@pytest.fixture
def ready(monkeypatch):
    monkeypatch.setattr(cli, "check_environment", lambda: OnboardingReport(items=[]))


def _runner(write=("Olli 1", "Panu"), code=0, record=None, progress=()):
    """Tekaistu ajuri: kirjoittaa sanatiedostot kuin lataus olisi tuonut ne."""

    def fake_run(commands, log, timeout=None, on_progress=None, **_):
        if record is not None:
            record.append(commands)
        for step in progress if on_progress else ():
            on_progress(*step)
        for command in commands:
            if command[:2] == ["colab", "download"]:
                os.makedirs(command[5], exist_ok=True)
                for stem in write:
                    with open(os.path.join(command[5], f"{stem}.words.json"), "w") as f:
                        f.write("{}")
        return code

    return fake_run


def test_a_run_that_brings_every_words_file_succeeds(audio, ready, monkeypatch, capsys):
    monkeypatch.setattr(cli.driver, "run", _runner())
    assert cli.main(_args(audio)) == 0
    out = capsys.readouterr().out
    assert "Olli 1.words.json" in out and "Panu.words.json" in out


def test_a_missing_words_file_fails_and_names_the_file(audio, ready, monkeypatch, capsys):
    monkeypatch.setattr(cli.driver, "run", _runner(write=("Olli 1",)))
    assert cli.main(_args(audio)) == 1
    err = capsys.readouterr().err
    assert "Panu.words.json" in err and "Olli 1.words.json" not in err


def test_an_old_words_file_is_not_mistaken_for_this_runs_result(
    audio, ready, monkeypatch, capsys
):
    out = audio[2]
    out.mkdir()
    (out / "Panu.words.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(cli.driver, "run", _runner(write=("Olli 1",)))
    assert cli.main(_args(audio)) == 1
    assert "Panu.words.json" in capsys.readouterr().err


def test_a_failing_command_passes_its_code_through(audio, ready, monkeypatch):
    monkeypatch.setattr(cli.driver, "run", _runner(write=(), code=3))
    assert cli.main(_args(audio)) == 3


def test_the_environment_is_checked_before_anything_is_uploaded(
    audio, monkeypatch, capsys
):
    called = []
    monkeypatch.setattr(
        cli, "check_environment", lambda: OnboardingReport(items=[_missing()])
    )
    monkeypatch.setattr(cli.driver, "run", lambda *a, **k: called.append(1) or 0)
    assert cli.main(_args(audio)) == 1
    assert called == []


def _missing():
    return OnboardingItem(
        key="colab",
        title="colab",
        ok=False,
        current_value="puuttuu",
        instructions="asenna",
    )


# --- Edistyminen ----------------------------------------------------------------------------


def test_progress_lines_are_integers_that_never_fall(audio, ready, monkeypatch, capsys):
    steps = [(10.0, "a"), (42.7, "b"), (30.0, "takaisin"), (100.0, "valmis")]
    monkeypatch.setattr(cli.driver, "run", _runner(progress=steps))
    assert cli.main(_args(audio, "--progress")) == 0
    lines = [x for x in capsys.readouterr().out.splitlines() if x.startswith("PROGRESS ")]
    values = [int(x.split()[1]) for x in lines]
    assert values == [10, 42, 42, 100]
    assert lines[0] == "PROGRESS 10 a"
    assert values == sorted(values)


def test_no_progress_lines_without_the_flag(audio, ready, monkeypatch, capsys):
    monkeypatch.setattr(cli.driver, "run", _runner(progress=[(10.0, "a")]))
    cli.main(_args(audio))
    assert "PROGRESS" not in capsys.readouterr().out


def test_progress_never_exceeds_one_hundred(audio, ready, monkeypatch, capsys):
    monkeypatch.setattr(cli.driver, "run", _runner(progress=[(150.0, "yli")]))
    cli.main(_args(audio, "--progress"))
    assert "PROGRESS 100 yli" in capsys.readouterr().out


# --- Keskeytys ---------------------------------------------------------------------------------


def _interrupting(sig):
    def fake_run(commands, log, timeout=None, **_):
        try:
            os.kill(os.getpid(), sig)
        except KeyboardInterrupt:
            return 130
        return 0

    return fake_run


@pytest.mark.parametrize("sig", [signal.SIGINT, signal.SIGTERM])
def test_a_cancel_stops_the_colab_session(audio, ready, monkeypatch, sig):
    stopped = []
    monkeypatch.setattr(cli.driver, "run", _interrupting(sig))
    monkeypatch.setattr(
        cli.session, "stop_session", lambda name: stopped.append(name) or 0
    )
    assert cli.main(_args(audio)) == 130
    assert stopped == ["whisper"]


def test_a_cancel_with_keep_session_leaves_the_session(audio, ready, monkeypatch):
    stopped = []
    monkeypatch.setattr(cli.driver, "run", _interrupting(signal.SIGTERM))
    monkeypatch.setattr(
        cli.session, "stop_session", lambda name: stopped.append(name) or 0
    )
    assert cli.main(_args(audio, "--keep-session")) == 130
    assert stopped == []


def test_sigterm_handling_is_undone_when_the_run_ends(audio, ready, monkeypatch):
    def sentinel(_signum, _frame):
        pass

    before = signal.signal(signal.SIGTERM, sentinel)
    try:
        monkeypatch.setattr(cli.driver, "run", _runner())
        cli.main(_args(audio))
        assert signal.getsignal(signal.SIGTERM) is sentinel
    finally:
        signal.signal(signal.SIGTERM, before)


# --- Ajurin edistymislukija -----------------------------------------------------------------


def test_the_driver_turns_audio_markers_into_progress_between_the_steps(monkeypatch):
    from colabtranscribe import driver

    def fake_execute(command, log, timeout=None, on_line=None, **_):
        if "pipeline.py" in command[-1]:
            for n in (1, 2, 3):
                on_line(f"[ääni ({n}/3)] Litteroidaan: x{n}.wav")
        return 0

    monkeypatch.setattr(driver, "_execute_single", fake_execute)
    seen = []
    plan = [["colab", "exec", "-s", "s", "python3 /content/pipeline.py"]]
    assert (
        driver.run(plan, lambda _: None, on_progress=lambda p, m: seen.append((p, m)))
        == 0
    )
    marked = [(p, m) for p, m in seen if "Litteroidaan (" in m]
    assert [m.split("Litteroidaan ")[1] for _, m in marked] == [
        "(1/3)...",
        "(2/3)...",
        "(3/3)...",
    ]
    percents = [p for p, _ in marked]
    assert percents == sorted(percents) and len(set(percents)) == 3
    assert percents == pytest.approx([20.0, 20.0 + 70 / 3, 20.0 + 140 / 3])


def test_the_audio_plan_gives_each_file_its_own_name_in_the_input_folder(tmp_path):
    from colabtranscribe import driver

    a = tmp_path / "Olli 1.wav"
    a.write_bytes(b"x")
    plan = driver.plan_audio_commands(
        RunOptions(source="audio", output_dir="o"), [str(a)]
    )
    links = [c[-1] for c in plan if c[:2] == ["colab", "exec"] and "ln -f" in c[-1]]
    assert len(links) == 1 and "'/content/input/Olli 1.wav'" in links[0]


def test_a_reused_session_lists_its_cache_before_uploading(audio):
    from colabtranscribe import driver

    options = RunOptions(source="audio", output_dir="o")
    files = [str(audio[0])]
    reused = driver.plan_audio_commands(options, files, reuse_session=True)
    fresh = driver.plan_audio_commands(options, files, reuse_session=False)
    assert ["cache-list", "whisper"] in reused
    assert reused[0][:2] != ["colab", "new"]
    assert ["cache-list", "whisper"] not in fresh
    assert fresh[0][:2] == ["colab", "new"]
