"""Ajurin komentojen muoto: mitä `colab`-komentoa mikinäkii ajetaan.

`plan_commands` on puhdas funktio: se ei aja mitään, joten koko ajoa ei
tarvitse Colabia testaamaan. Järjestys on sopimus — uusi istunto, hakemistot,
skripti ylös, äänet ylös, ajo alas, tulokset alas, istunto kiinni.
"""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

import pytest

from colabtranscribe import driver
from colabtranscribe.options import RunOptions


def test_pipeline_script_ships_with_the_package():
    # Ladattava skripti on paketin sisällä, ei sovellushakemistossa: vain
    # näin ajuri voi löytää sen myös asennettuna.
    script = driver.PIPELINE_SCRIPT
    assert script.is_file()
    assert script.name == "pipeline.py"
    assert "whisper-ctranslate2" in script.read_text(encoding="utf-8")


@pytest.mark.parametrize("transfer", ["drive", "direct"])
def test_the_library_is_uploaded_beside_the_script_before_it_runs(tmp_path: Path, transfer):
    """Skripti tuo ``silencelearn``in, eikä Colabissa ole työtilaa: kirjasto on
    ladattava ``/content``iin ennen kuin skripti ajetaan, ja samalla nimellä
    jolla se tuodaan. Ilman sitä ``--preset learned`` kaatuu tuontiin pilvessä,
    eikä mikään paikallinen testi huomaa."""
    import silencelearn

    options = RunOptions(input_dir=str(tmp_path), transfer=transfer)
    commands = driver.plan_commands(options, ["a.wav"])
    uploads = [c for c in commands if c[1] == "upload"]
    library = [c for c in uploads if c[-1] == "/content/silencelearn.py"]
    assert len(library) == 1, uploads
    assert library[0][4] == str(Path(silencelearn.__file__)) == str(driver.LEARN_MODULE)
    assert Path(library[0][-1]).stem == "silencelearn"
    run = next(i for i, c in enumerate(commands)
               if c[1] == "exec" and "python3 /content/pipeline.py" in c[-1])
    assert commands.index(library[0]) < run


def test_plan_sequence_direct(tmp_path: Path):
    options = RunOptions(
        input_dir=str(tmp_path), output_dir=str(tmp_path / "out"), transfer="direct"
    )
    commands = driver.plan_commands(options, ["pool/a.wav"])

    heads = [c[:3] for c in commands]
    assert heads[0] == ["colab", "new", "-s"]
    assert "--gpu" in commands[0] and "T4" in commands[0]
    assert heads[1] == ["colab", "exec", "-s"]
    assert "/content/input" in commands[1][-1]
    assert heads[2] == ["colab", "upload", "-s"]
    assert str(driver.PIPELINE_SCRIPT) in commands[2]
    assert commands[2][-1] == "/content/pipeline.py"
    # kirjasto skriptin viereen
    assert heads[3] == ["colab", "upload", "-s"]
    assert commands[3][-1] == "/content/silencelearn.py"
    # alipolku tehdään ennen kuin siihen ladataan
    assert heads[4] == ["colab", "exec", "-s"]
    assert "/content/input/pool" in commands[4][-1]
    assert heads[5] == ["colab", "upload", "-s"]
    # lähde on absoluuttinen: aliprosessi ei peri TUI:n työhakemistoa eikä
    # kannata arvata mistä se käynnistettiin
    assert commands[5][4] == str(tmp_path / "pool/a.wav")
    assert commands[5][-1] == "/content/input/pool/a.wav"
    assert heads[-2] == ["colab", "download", "-s"]
    assert heads[-1] == ["colab", "stop", "-s"]
    assert options.session in commands[0] and options.session in commands[-1]


def test_plan_sequence_drive(tmp_path: Path):
    options = RunOptions(
        input_dir=str(tmp_path), output_dir=str(tmp_path / "out"), transfer="drive"
    )
    commands = driver.plan_commands(options, ["pool/a.wav"])

    heads = [c[:2] for c in commands]
    assert heads[0] == ["colab", "new"]
    assert heads[1] == ["colab", "drivemount"]
    assert heads[2] == ["colab", "exec"]
    assert heads[3] == ["colab", "upload"]
    assert heads[4] == ["colab", "upload"]
    assert commands[4][-1] == "/content/silencelearn.py"
    assert heads[5] == ["drive", "upload"]
    assert commands[5][2] == str(tmp_path)
    assert f"ColabTranscribe/{options.session}/input.tar" in commands[5][3]
    # purkaminen Colabissa
    assert heads[6] == ["colab", "exec"]
    assert "tar -xf" in commands[6][-1]
    assert f"ColabTranscribe/{options.session}/input.tar" in commands[6][-1]
    # suoritus
    assert any("pipeline.py" in c[-1] for c in commands if c[1] == "exec")
    # lataus alas
    assert any(c[1] == "download" for c in commands)
    # väliaikaistiedostojen poisto Drivesta
    assert any(
        "rm -rf" in c[-1] and "ColabTranscribe" in c[-1]
        for c in commands
        if c[1] == "exec"
    )
    # lopetus
    assert heads[-1] == ["colab", "stop"]


def test_pipeline_args_land_in_the_exec_call(tmp_path: Path):
    options = RunOptions(input_dir=str(tmp_path), preset="intra-mic", thr=-42, tail=0.4)
    commands = driver.plan_commands(options, [])
    exec_cmd = next(c for c in commands if c[1] == "exec" and "pipeline.py" in c[-1])
    remote = exec_cmd[-1]
    assert remote.startswith("python3 /content/pipeline.py")
    for token in ("--preset", "intra-mic", "--thr", "-42", "--tail", "0.4"):
        assert token in remote


def test_prompt_with_spaces_is_quoted(tmp_path: Path):
    options = RunOptions(input_dir=str(tmp_path), prompt="öö, tota, niinku")
    commands = driver.plan_commands(options, [])
    exec_cmd = next(c for c in commands if c[1] == "exec" and "pipeline.py" in c[-1])
    remote = exec_cmd[-1]
    # purettuna takaisin argumenteiksi prompt on yksi argumentti, ei kolme
    args = shlex.split(remote)
    i = args.index("--prompt")
    assert args[i + 1] == "öö, tota, niinku"


def test_list_input_files_lists_everything_relative(tmp_path: Path):
    # Ei suodateta: skripti tarvitsee myös .nhsx-istunnot, ja sen tarvitsema
    # se itse. Polut ovat suhteellisia, sillä pilvipää antaa /content/inputin.
    (tmp_path / "puhe.wav").write_bytes(b"")
    (tmp_path / "jakso.nhsx").write_text("<x/>", encoding="utf-8")
    (tmp_path / "kuva.png").write_bytes(b"")
    (tmp_path / "ala").mkdir()
    (tmp_path / "ala" / "toinen.m4a").write_bytes(b"")

    assert driver.list_input_files(tmp_path) == [
        "ala/toinen.m4a",
        "jakso.nhsx",
        "kuva.png",
        "puhe.wav",
    ]


def test_parse_generated_reads_the_script_output():
    out = (
        "Litteroidaan tiedostoa: /content/input/a.wav\n"
        "Litteroitu .nhsx luotu: /content/output/jakso litteroitu.nhsx\n"
    )
    assert driver.parse_generated(out) == ["/content/output/jakso litteroitu.nhsx"]


def test_parse_generated_empty_when_nothing():
    assert driver.parse_generated("Koko putki suoritettu onnistuneesti.") == []


def test_list_input_files_excludes_hidden_files(tmp_path: Path):
    (tmp_path / "puhe.wav").write_bytes(b"")
    (tmp_path / ".DS_Store").write_bytes(b"")
    (tmp_path / ".hidden").write_bytes(b"")
    # piilotetut tiedostot eivät kuulu siirtoon
    assert driver.list_input_files(tmp_path) == ["puhe.wav"]


def test_list_input_files_excludes_hidden_directories(tmp_path: Path):
    (tmp_path / "puhe.wav").write_bytes(b"")
    cache = tmp_path / ".cache"
    cache.mkdir()
    (cache / "model.bin").write_bytes(b"")
    assert driver.list_input_files(tmp_path) == ["puhe.wav"]


def test_list_input_files_does_not_follow_symlinks_outside(tmp_path: Path):
    inbox = tmp_path / "in"
    inbox.mkdir()
    (inbox / "puhe.wav").write_bytes(b"")
    secret = tmp_path / "secret.wav"
    secret.write_bytes(b"secret")
    (inbox / "link.wav").symlink_to(secret)
    assert driver.list_input_files(inbox) == ["puhe.wav"]


def test_plan_commands_quotes_subdirectory_names_for_remote_shell(tmp_path: Path):
    options = RunOptions(
        input_dir=str(tmp_path), output_dir=str(tmp_path / "out"), transfer="direct"
    )
    commands = driver.plan_commands(options, ["x;touch pwned/a.wav"])
    mkdir = [
        c[-1]
        for c in commands
        if c[1] == "exec" and "mkdir" in c[-1] and "pwned" in c[-1]
    ]
    assert mkdir
    tokens = shlex.split(mkdir[0])
    assert tokens[:2] == ["mkdir", "-p"]
    assert tokens[2:] == ["/content/input/x;touch pwned"]


def test_run_kills_a_hung_process_that_prints_nothing():
    """Timeout pitää koskea myös prosessia joka ei sulje stdoutia.

    ``wait(timeout=)`` ajettuna vasta kun stdout on luettu loppuun ei
    koskaan laukea: ``sleep`` pitää putken auki kunnes se itse kuolee.
    """
    logs: list[str] = []
    code = driver.run([["sleep", "10"]], logs.append, timeout=0.3)
    assert code == 124
    assert any("aikarajan" in line for line in logs)


def test_command_timeout_outlasts_whisper():
    from colabtranscribe.colab import pipeline

    assert driver.COMMAND_TIMEOUT >= pipeline.WHISPER_TIMEOUT


def test_run_translates_colab_exec_to_stdin(monkeypatch):
    """colab exec ei ota koodia komentoriviltä vaan stdin-syötteenä."""
    import io

    recorded_calls = []

    class FakeProcess:
        def __init__(self, cmd, stdin=None, **kwargs):
            recorded_calls.append((cmd, kwargs))
            self.stdin = io.StringIO()
            self.stdout = ["Valmis\n"]

        def wait(self):
            return 0

    monkeypatch.setattr(subprocess, "Popen", FakeProcess)
    logs = []
    code = driver.run(
        [["colab", "exec", "-s", "sess", "mkdir -p /content/input"]], logs.append
    )
    assert code == 0
    assert len(recorded_calls) == 1
    cmd, _ = recorded_calls[0]
    assert cmd == [
        "colab",
        "exec",
        "-s",
        "sess",
        "--timeout",
        str(driver.COMMAND_TIMEOUT),
    ]


def test_run_detects_colab_exec_traceback(monkeypatch):
    """colab exec palauttaa 0 vaikka ytimessä tulisi poikkeus; ajurin on huomattava se."""
    import io

    class FakeProcess:
        def __init__(self, cmd, stdin=None, **kwargs):
            self.stdin = io.StringIO()
            self.stdout = [
                "---------------------------------------------------------------------------\n",
                "RuntimeError: jotain meni pieleen\n",
            ]

        def wait(self):
            return 0

    monkeypatch.setattr(subprocess, "Popen", FakeProcess)
    logs = []
    code = driver.run(
        [["colab", "exec", "-s", "sess", "python3 /content/pipeline.py"]], logs.append
    )
    assert code != 0
    assert any("Etäkomento epäonnistui" in line for line in logs)


def test_run_handles_directory_download(monkeypatch, tmp_path):
    """colab download ei voi ladata kansiota, joten se ladataan tar-pakettina ja puretaan."""
    import io
    import tarfile

    out_dir = tmp_path / "output"

    def fake_popen(cmd, stdin=None, **kwargs):
        class P:
            def __init__(self, c):
                self.stdin = io.StringIO()
                self.stdout = []

            def wait(self):
                if len(cmd) >= 6 and cmd[1] == "download" and cmd[4].endswith(".tar.gz"):
                    local_tar = Path(cmd[5])
                    local_tar.parent.mkdir(parents=True, exist_ok=True)
                    with tarfile.open(local_tar, "w:gz") as tar:
                        sample = tmp_path / "sample.txt"
                        sample.write_text("testisisältö")
                        tar.add(sample, arcname="sample.txt")
                return 0

        return P(cmd)

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    logs = []
    code = driver.run(
        [["colab", "download", "-s", "sess", "/content/output/", str(out_dir)]],
        logs.append,
    )
    assert code == 0
    assert (out_dir / "sample.txt").read_text() == "testisisältö"


def test_run_handles_drive_upload(monkeypatch, tmp_path):
    """drive upload luo paikallisen paketin ja lataa sen gdrive-moduulilla."""
    in_dir = tmp_path / "input"
    in_dir.mkdir()
    (in_dir / "audio.wav").write_bytes(b"test")

    uploaded = []

    def fake_upload(local_dir, session, log):
        uploaded.append((local_dir, session))
        return "file-id-123"

    monkeypatch.setattr(driver, "upload_input_to_drive", fake_upload)
    logs = []
    cmd = ["drive", "upload", str(in_dir), "ColabTranscribe/vst-pipeline/input.tar"]
    code = driver.run([cmd], logs.append)
    assert code == 0
    assert len(uploaded) == 1
    assert uploaded[0] == (str(in_dir), "vst-pipeline")


def test_run_reports_actionable_hint_on_drive_403(monkeypatch, tmp_path: Path):
    def failing_upload(input_dir, session, log):
        raise RuntimeError("HTTP Error 403: Forbidden")

    monkeypatch.setattr(driver, "upload_input_to_drive", failing_upload)
    logs: list[str] = []
    cmd = ["drive", "upload", str(tmp_path), "ColabTranscribe/vst-pipeline/input.tar"]
    code = driver.run([cmd], logs.append)
    assert code == 1
    assert any(
        "Google Drive -lataus epäonnistui: HTTP Error 403: Forbidden" in line
        for line in logs
    )
    assert any("quota project" in line for line in logs)
    assert any("direct" in line for line in logs)


def test_plan_sequence_reuse_session_skips_colab_new(tmp_path: Path):
    options = RunOptions(input_dir=str(tmp_path), transfer="drive")
    commands = driver.plan_commands(options, [], reuse_session=True)
    assert not any(c[:2] == ["colab", "new"] for c in commands)
    # Varmistetaan että tyhjennyskomento on mukana
    assert any(
        "rm -rf" in c[-1] and "/content/input" in c[-1]
        for c in commands
        if c[1] == "exec"
    )


def test_plan_sequence_keep_session_skips_colab_stop(tmp_path: Path):
    options = RunOptions(input_dir=str(tmp_path), keep_session=True)
    commands = driver.plan_commands(options, [])
    assert not any(c[:2] == ["colab", "stop"] for c in commands)


def test_run_handles_keyboard_interrupt(monkeypatch):
    def fake_popen(*args, **kwargs):
        raise KeyboardInterrupt()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    logs = []
    code = driver.run(
        [["colab", "new", "-s", "vst-pipeline", "--gpu", "T4"]], logs.append
    )
    assert code == 130
    assert any("Ajo keskeytetty" in line for line in logs)


def test_run_detects_precondition_failed_on_colab_new(monkeypatch):
    import io

    class FakeProcess:
        def __init__(self, cmd, **kwargs):
            self.stdin = io.StringIO()
            self.stdout = [
                "TooManyAssignmentsError: Failed to issue request POST https://colab.research.google.com/tun/m/assign: Precondition Failed\n"
            ]

        def wait(self):
            return 1

    monkeypatch.setattr(subprocess, "Popen", FakeProcess)
    logs = []
    code = driver.run(
        [["colab", "new", "-s", "vst-pipeline", "--gpu", "T4"]], logs.append
    )
    assert code != 0
    assert any("Precondition Failed" in line for line in logs)
    assert any("colab stop" in line for line in logs)


def test_run_retries_on_connection_lost_and_succeeds(monkeypatch):
    import io

    attempts = 0

    class FlakyProcess:
        def __init__(self, cmd, **kwargs):
            nonlocal attempts
            attempts += 1
            self.stdin = io.StringIO()
            if attempts == 1:
                self.stdout = ["RuntimeError: Connection was lost.\n"]
                self._code = 1
            else:
                self.stdout = ["Success\n"]
                self._code = 0

        def wait(self):
            return self._code

    monkeypatch.setattr(subprocess, "Popen", FlakyProcess)
    monkeypatch.setattr("time.sleep", lambda _: None)
    logs = []
    code = driver.run(
        [["colab", "exec", "-s", "vst-pipeline", "ls /content"]], logs.append
    )
    assert code == 0
    assert attempts == 2
    assert any("Connection was lost" in line or "Yhteys katkesi" in line for line in logs)
    assert any("yritetään uudelleen" in line for line in logs)


def test_run_reports_actionable_hint_on_persistent_connection_lost(monkeypatch):
    import io

    class BrokenProcess:
        def __init__(self, cmd, **kwargs):
            self.stdin = io.StringIO()
            self.stdout = ["RuntimeError: Connection was lost.\n"]

        def wait(self):
            return 1

    monkeypatch.setattr(subprocess, "Popen", BrokenProcess)
    monkeypatch.setattr("time.sleep", lambda _: None)
    logs = []
    code = driver.run(
        [["colab", "exec", "-s", "vst-pipeline", "ls /content"]], logs.append
    )
    assert code != 0
    assert any("Connection was lost" in line for line in logs)
    assert any("uv run colab-transcribe" in line for line in logs)


def test_run_auto_opens_auth_url(monkeypatch):
    import io
    import webbrowser

    opened_urls = []
    monkeypatch.setattr(webbrowser, "open", lambda url: opened_urls.append(url) or True)

    auth_url = (
        "https://accounts.google.com/o/oauth2/v2/auth?access_type=offline"
        "&client_id=123.apps.googleusercontent.com&response_type=code"
    )

    class FakeProcess:
        def __init__(self, cmd, **kwargs):
            self.stdin = io.StringIO()
            self.stdout = [
                "[colab] REQUIRED: Google Drive Authorization needed.\n",
                "Please visit:\n",
                f"{auth_url}\n",
            ]

        def wait(self):
            return 0

    monkeypatch.setattr(subprocess, "Popen", FakeProcess)
    logs = []
    code = driver.run([["colab", "drivemount", "-s", "vst-pipeline"]], logs.append)
    assert code == 0
    assert opened_urls == [auth_url]
    assert any("Avattu" in line or "valtuutus" in line.lower() for line in logs)


def test_execute_single_passes_colab_cli_no_browser_env(monkeypatch):
    import io

    captured_env = {}

    class FakeProcess:
        def __init__(self, cmd, **kwargs):
            nonlocal captured_env
            captured_env = kwargs.get("env", {})
            self.stdin = io.StringIO()
            self.stdout = []

        def wait(self):
            return 0

    monkeypatch.setattr(subprocess, "Popen", FakeProcess)
    code = driver.run([["colab", "drivemount", "-s", "vst-pipeline"]], lambda _: None)
    assert code == 0
    assert captured_env.get("COLAB_CLI_NO_BROWSER") == "1"


def test_run_deduplicates_auth_urls(monkeypatch):
    import io
    import webbrowser

    opened_urls = []
    monkeypatch.setattr(webbrowser, "open", lambda url: opened_urls.append(url) or True)

    auth_url = (
        "https://accounts.google.com/o/oauth2/v2/auth?access_type=offline"
        "&client_id=123.apps.googleusercontent.com&response_type=code"
    )

    class FakeProcess:
        def __init__(self, cmd, **kwargs):
            self.stdin = io.StringIO()
            self.stdout = [
                f"Line 1: {auth_url}\n",
                f"Line 2: {auth_url}\n",
            ]

        def wait(self):
            return 0

    monkeypatch.setattr(subprocess, "Popen", FakeProcess)
    logs = []
    code = driver.run(
        [
            ["colab", "drivemount", "-s", "vst-pipeline"],
            ["colab", "drivemount", "-s", "vst-pipeline"],
        ],
        logs.append,
    )
    assert code == 0
    # Must only be opened ONCE across the entire run despite duplicate lines and multiple commands
    assert opened_urls == [auth_url]


def test_plan_commands_resolves_relative_output_dir(tmp_path: Path):
    options = RunOptions(input_dir=str(tmp_path), output_dir="output")
    cmds = driver.plan_commands(options, [])
    download_cmd = next(c for c in cmds if c[1] == "download")
    assert download_cmd[-1] == str(tmp_path / "output")


def test_list_input_files_single_file(tmp_path: Path):
    audio = tmp_path / "puhe.wav"
    audio.write_bytes(b"data")
    assert driver.list_input_files(audio) == ["puhe.wav"]


def test_has_nhsx_files(tmp_path: Path):
    assert driver.has_nhsx_files(tmp_path) is False

    nhsx_file = tmp_path / "jakso.nhsx"
    nhsx_file.write_text("<Session/>", encoding="utf-8")
    assert driver.has_nhsx_files(tmp_path) is True
    assert driver.has_nhsx_files(nhsx_file) is True

    audio_file = tmp_path / "puhe.wav"
    audio_file.write_bytes(b"data")
    assert driver.has_nhsx_files(audio_file) is False


def test_plan_commands_single_audio_file_direct(tmp_path: Path):
    audio = tmp_path / "haastattelu.mp3"
    audio.write_bytes(b"data")
    options = RunOptions(input_dir=str(audio), output_dir="out", transfer="direct")
    commands = driver.plan_commands(options, ["haastattelu.mp3"])

    upload_cmds = [c for c in commands if c[0] == "colab" and c[1] == "upload"]
    audio_uploads = [c for c in upload_cmds if c[-1] == "/content/input/haastattelu.mp3"]
    assert len(audio_uploads) == 1
    assert audio_uploads[0][4] == str(audio)


def test_plan_commands_single_audio_file_drive(tmp_path: Path):
    audio = tmp_path / "haastattelu.mp3"
    audio.write_bytes(b"data")
    options = RunOptions(input_dir=str(audio), output_dir="out", transfer="drive")
    commands = driver.plan_commands(options, ["haastattelu.mp3"])

    drive_upload = next(c for c in commands if c[0] == "drive" and c[1] == "upload")
    assert drive_upload[2] == str(audio)


def test_parse_generated_transcripts():
    output = (
        "Litteroidaan tiedostoa: /content/input/haastattelu.mp3\n"
        "Litterointi luotu: /content/output/transcripts/haastattelu.json\n"
        "Koko putki suoritettu onnistuneesti.\n"
    )
    assert driver.parse_generated_transcripts(output) == [
        "/content/output/transcripts/haastattelu.json"
    ]


def test_get_transcript_files(tmp_path: Path):
    out_dir = tmp_path / "out"
    transcripts_dir = out_dir / "transcripts"
    transcripts_dir.mkdir(parents=True)
    json_f = transcripts_dir / "audio.json"
    json_f.write_text("{}", encoding="utf-8")
    txt_f = transcripts_dir / "audio.txt"
    txt_f.write_text("puhe", encoding="utf-8")
    other_f = transcripts_dir / "ignore.bin"
    other_f.write_bytes(b"")

    found = driver.get_transcript_files(out_dir)
    assert found == [json_f, txt_f]


def test_describe_command():
    assert "GPU-istuntoa" in driver.describe_command(["colab", "new", "-s", "vst"])
    assert "Google Drive" in driver.describe_command(["colab", "drivemount", "-s", "vst"])
    assert "pipeline.py" in driver.describe_command(
        ["colab", "upload", "-s", "vst", "path/to/pipeline.py", "/content/pipeline.py"]
    )
    assert "litterointi" in driver.describe_command(
        ["colab", "exec", "-s", "vst", "python3 /content/pipeline.py"]
    )
    assert "tulokset" in driver.describe_command(["colab", "download", "-s", "vst", "out/"])
    assert "Suljetaan" in driver.describe_command(["colab", "stop", "-s", "vst"])


def test_run_calls_on_progress(monkeypatch):
    import io

    class FakeProcess:
        def __init__(self, cmd, **kwargs):
            self.stdin = io.StringIO()
            self.stdout = ["[vaihe 1/4] Asennetaan riippuvuudet...\n"]

        def wait(self):
            return 0

    monkeypatch.setattr(subprocess, "Popen", FakeProcess)

    progress_events = []
    commands = [
        ["colab", "new", "-s", "vst"],
        ["colab", "exec", "-s", "vst", "python3 /content/pipeline.py"],
    ]
    code = driver.run(
        commands,
        log=lambda _: None,
        on_progress=lambda pct, msg: progress_events.append((pct, msg)),
    )
    assert code == 0
    assert len(progress_events) >= 3
    # First command at 0%
    assert progress_events[0][0] == 0.0
    # Second command base at 50%
    assert any(pct >= 50.0 for pct, _ in progress_events)
    # End reaches 100%
    assert progress_events[-1][0] == 100.0


def test_commands_find_the_bundled_colab(monkeypatch):
    """Komento pysyy ``colab ...``:na (sama kuin ``--dry-run``), ja uvx:n
    ympäristön ``bin`` on PATHin alussa, jolloin sen ``colab`` ajetaan."""
    from colabtranscribe import driver

    monkeypatch.setattr("colabtranscribe.onboarding.bundled_colab", lambda: "/env/bin/colab")
    started = []

    class Done:
        def __init__(self, cmd, **kwargs):
            started.append((cmd, kwargs["env"]["PATH"].split(":")[0]))
            self.stdout = iter(())
            self.returncode = 0

        def communicate(self, *a, **k):
            return ("", None)

        def wait(self, *a, **k):
            return 0

        def poll(self):
            return 0

    monkeypatch.setattr("subprocess.Popen", Done)
    driver._execute_single(["colab", "stop", "-s", "x"], lambda _m: None, max_retries=0)
    assert started == [(["colab", "stop", "-s", "x"], "/env/bin")]


def test_a_drive_403_continues_with_direct_upload_when_a_fallback_is_given(
    monkeypatch, tmp_path: Path
):
    """Drive-API vaatii quota-projektin jota ystävän tilillä ei ollut (HTTP 403).
    Ajon ei pidä pysähtyä: Drive-vaiheen ja sen jälkeisten tilalle tulee suora
    siirto, ja vanha loppu (tar-purku, Drive-siivous) jää pois."""

    def failing_upload(input_dir, session, log):
        raise RuntimeError("HTTP Error 403: Forbidden")

    monkeypatch.setattr(driver, "upload_input_to_drive", failing_upload)
    logs: list[str] = []
    plan = [
        ["drive", "upload", str(tmp_path), "ColabTranscribe/iiris/input.tar"],
        ["echo", "tar-purku-driveltä"],
    ]
    code = driver.run(plan, logs.append, on_drive_failure=lambda: [["echo", "suora-siirto"]])
    assert code == 0
    assert any("suora-siirto" in line for line in logs)
    assert not any("tar-purku-driveltä" in line for line in logs)
    assert any("403" in line for line in logs)


def test_the_direct_tail_starts_after_the_scripts_and_covers_the_inputs(tmp_path: Path):
    """Pilvessä skriptit ovat jo ylhäällä kun Drive kaatuu, joten suora häntä
    alkaa vasta syötteistä: ei toista ``colab new``tä eikä skriptien latausta."""
    (tmp_path / "a.nhsx").write_text("x")
    (tmp_path / "a Files").mkdir()
    (tmp_path / "a Files" / "m.wav").write_bytes(b"w")
    options = RunOptions(input_dir=str(tmp_path), transfer="drive", session="iiris")
    files = driver.list_input_files(tmp_path)
    tail = driver.direct_tail(options, files)
    assert not any(c[:2] == ["colab", "new"] for c in tail)
    assert not any(c[:2] == ["colab", "drivemount"] for c in tail)
    assert not any(str(driver.PIPELINE_SCRIPT) in c for c in tail)
    uploads = [c for c in tail if c[:2] == ["colab", "upload"]]
    assert {Path(c[-1]).name for c in uploads} == {"a.nhsx", "m.wav"}
    assert tail[-1][:2] == ["colab", "stop"] or tail[-1][:2] == ["colab", "download"]


def test_a_big_input_goes_up_in_parts_and_is_joined_in_colab(monkeypatch, tmp_path: Path):
    """Suora siirto kaatui HTTP 500:een 409 MB:n WAVissa (Colabin tiedostorajapinta).
    Iso tiedosto lähtee paloina; jokainen pala yritetään uudelleen erikseen, ja
    Colabissa palat liitetään `cat`illa takaisin yhdeksi tiedostoksi."""
    monkeypatch.setattr(driver, "CHUNK_BYTES", 1000)
    src = tmp_path / "iso.WAV"
    data = bytes(range(256)) * 10  # 2560 tavua -> 3 palaa
    src.write_bytes(data)

    seen: list[list[str]] = []
    got: list[bytes] = []
    failures = {"left": 1}

    def fake_execute(command, log, timeout=None, **_):
        seen.append(command)
        if command[:2] == ["colab", "upload"]:
            if failures["left"] and command[-1].endswith(".part0001"):
                failures["left"] -= 1
                return 1
            got.append(Path(command[4]).read_bytes())
        return 0

    monkeypatch.setattr(driver, "_execute_single", fake_execute)
    monkeypatch.setattr(driver.time, "sleep", lambda _: None)
    code = driver.run(
        [["chunked-upload", "iiris", str(src), "/content/input/a b/iso.WAV"]],
        lambda _: None,
    )
    assert code == 0
    assert b"".join(got) == data
    uploads = [c[-1] for c in seen if c[:2] == ["colab", "upload"]]
    assert uploads.count("/content/input/a b/iso.WAV.part0001") == 2  # yksi uusinta
    join = seen[-1]
    assert join[:4] == ["colab", "exec", "-s", "iiris"]
    assert "cat '/content/input/a b/iso.WAV'.part*" in join[4]
    assert "rm" in join[4]


def test_a_part_that_keeps_failing_stops_the_run(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(driver, "CHUNK_BYTES", 1000)
    src = tmp_path / "iso.WAV"
    src.write_bytes(b"x" * 2500)
    monkeypatch.setattr(driver, "_execute_single", lambda *a, **k: 1)
    monkeypatch.setattr(driver.time, "sleep", lambda _: None)
    code = driver.run([["chunked-upload", "s", str(src), "/content/input/x"]], lambda _: None)
    assert code == 1


def test_the_plan_chunks_only_big_direct_uploads(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(driver, "CHUNK_ABOVE", 100)
    (tmp_path / "pieni.wav").write_bytes(b"x" * 10)
    (tmp_path / "iso.wav").write_bytes(b"x" * 500)
    options = RunOptions(input_dir=str(tmp_path), transfer="direct", session="iiris")
    plan = driver.plan_commands(options, ["pieni.wav", "iso.wav"], reuse_session=True)
    assert any(c[0] == "chunked-upload" and c[2].endswith("iso.wav") for c in plan)
    assert any(c[:2] == ["colab", "upload"] and c[-1].endswith("pieni.wav") for c in plan)
    assert not any(c[:2] == ["colab", "upload"] and c[-1].endswith("iso.wav") for c in plan)


def _session(tmp_path: Path, pool_path="rec Files", names=("a.wav", "b.wav")) -> None:
    files = "".join(f'<File Id="{i}" Name="{n}"/>' for i, n in enumerate(names, 1))
    (tmp_path / "jakso.nhsx").write_text(
        f'<?xml version="1.0"?><Session><AudioPool Path="{pool_path}" Location="/x">'
        f"{files}</AudioPool><Tracks/></Session>",
        encoding="utf-8",
    )


def _touch(root: Path, *rels: str) -> list[str]:
    for rel in rels:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(b"x")
    return driver.list_input_files(root)


def test_only_what_the_session_uses_goes_up(tmp_path: Path):
    """Hänen kansionsa: istunto + sen oma ``rec Files``, mutta vieressä myös
    ``.TAKE``-kopiot ja raakamatsku.mp3. Pilvessä skripti litteroi *kaiken*
    äänen jonka löytää, joten ylimääräinen maksaa sekä latauksen että ajan."""
    _session(tmp_path)
    files = _touch(
        tmp_path,
        "rec Files/a.wav", "rec Files/b.wav", "rec Files/c.wav",
        "001.TAKE/a.wav", "raakamatsku.mp3", "muistiinpano.txt",
    )
    kept, skipped = driver.session_inputs(tmp_path, files)
    assert kept == ["jakso.nhsx", "rec Files/a.wav", "rec Files/b.wav"]
    assert set(skipped) == {
        "rec Files/c.wav", "001.TAKE/a.wav", "raakamatsku.mp3", "muistiinpano.txt",
    }


def test_without_a_session_everything_goes_up(tmp_path: Path):
    files = _touch(tmp_path, "puhe.wav", "toinen.mp3")
    assert driver.session_inputs(tmp_path, files) == (files, [])


def test_an_unreadable_session_uploads_everything_rather_than_guessing(tmp_path: Path):
    files = _touch(tmp_path, "rec Files/a.wav", "raaka.mp3")
    (tmp_path / "rikki.nhsx").write_text("<Session><AudioPool", encoding="utf-8")
    files = driver.list_input_files(tmp_path)
    assert driver.session_inputs(tmp_path, files) == (files, [])


def test_a_file_the_session_names_but_the_folder_lacks_is_not_an_error(tmp_path: Path):
    _session(tmp_path, names=("a.wav", "puuttuu.wav"))
    files = _touch(tmp_path, "rec Files/a.wav")
    kept, _ = driver.session_inputs(tmp_path, files)
    assert kept == ["jakso.nhsx", "rec Files/a.wav"]
