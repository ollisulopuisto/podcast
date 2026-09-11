"""Ajurin komentojen muoto: mitä `colab`-komentoa mikinäkii ajetaan.

`plan_commands` on puhdas funktio: se ei aja mitään, joten koko ajoa ei
tarvitse Colabia testaamaan. Järjestys on sopimus — uusi istunto, hakemistot,
skripti ylös, äänet ylös, ajo alas, tulokset alas, istunto kiinni.
"""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

from colabtranscribe import driver
from colabtranscribe.options import RunOptions


def test_pipeline_script_ships_with_the_package():
    # Ladattava skripti on paketin sisällä, ei sovellushakemistossa: vain
    # näin ajuri voi löytää sen myös asennettuna.
    script = driver.PIPELINE_SCRIPT
    assert script.is_file()
    assert script.name == "pipeline.py"
    assert "whisper-ctranslate2" in script.read_text(encoding="utf-8")


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
    # alipolku tehdään ennen kuin siihen ladataan
    assert heads[3] == ["colab", "exec", "-s"]
    assert "/content/input/pool" in commands[3][-1]
    assert heads[4] == ["colab", "upload", "-s"]
    # lähde on absoluuttinen: aliprosessi ei peri TUI:n työhakemistoa eikä
    # kannata arvata mistä se käynnistettiin
    assert commands[4][4] == str(tmp_path / "pool/a.wav")
    assert commands[4][-1] == "/content/input/pool/a.wav"
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
    assert heads[4] == ["drive", "upload"]
    assert commands[4][2] == str(tmp_path)
    assert f"ColabTranscribe/{options.session}/input.tar.gz" in commands[4][3]
    # purkaminen Colabissa
    assert heads[5] == ["colab", "exec"]
    assert "tar -xzf" in commands[5][-1]
    assert f"ColabTranscribe/{options.session}/input.tar.gz" in commands[5][-1]
    # suoritus
    assert any("pipeline.py" in c[-1] for c in commands if c[1] == "exec")
    # lataus alas
    assert any(c[1] == "download" for c in commands)
    # väliaikaistiedostojen poisto Drivesta
    assert any("rm -rf" in c[-1] and "ColabTranscribe" in c[-1] for c in commands if c[1] == "exec")
    # lopetus
    assert heads[-1] == ["colab", "stop"]



def test_pipeline_args_land_in_the_exec_call(tmp_path: Path):
    options = RunOptions(
        input_dir=str(tmp_path), preset="intra-mic", thr=-42, tail=0.4
    )
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
    out = "Litteroidaan tiedostoa: /content/input/a.wav\n" "Litteroitu .nhsx luotu: /content/output/jakso litteroitu.nhsx\n"
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
    mkdir = [c[-1] for c in commands if c[1] == "exec" and "mkdir" in c[-1] and "pwned" in c[-1]]
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
    code = driver.run([["colab", "exec", "-s", "sess", "mkdir -p /content/input"]], logs.append)
    assert code == 0
    assert len(recorded_calls) == 1
    cmd, _ = recorded_calls[0]
    assert cmd == ["colab", "exec", "-s", "sess", "--timeout", str(driver.COMMAND_TIMEOUT)]


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
    code = driver.run([["colab", "exec", "-s", "sess", "python3 /content/pipeline.py"]], logs.append)
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
    cmd = ["drive", "upload", str(in_dir), "ColabTranscribe/vst-pipeline/input.tar.gz"]
    code = driver.run([cmd], logs.append)
    assert code == 0
    assert len(uploaded) == 1
    assert uploaded[0] == (str(in_dir), "vst-pipeline")


def test_run_reports_actionable_hint_on_drive_403(monkeypatch, tmp_path: Path):
    def failing_upload(input_dir, session, log):
        raise RuntimeError("HTTP Error 403: Forbidden")

    monkeypatch.setattr(driver, "upload_input_to_drive", failing_upload)
    logs: list[str] = []
    cmd = ["drive", "upload", str(tmp_path), "ColabTranscribe/vst-pipeline/input.tar.gz"]
    code = driver.run([cmd], logs.append)
    assert code == 1
    assert any("Google Drive -lataus epäonnistui: HTTP Error 403: Forbidden" in line for line in logs)
    assert any("quota project" in line for line in logs)
    assert any("direct" in line for line in logs)


def test_plan_sequence_reuse_session_skips_colab_new(tmp_path: Path):
    options = RunOptions(input_dir=str(tmp_path), transfer="drive")
    commands = driver.plan_commands(options, [], reuse_session=True)
    assert not any(c[:2] == ["colab", "new"] for c in commands)
    # Varmistetaan että tyhjennyskomento on mukana
    assert any("rm -rf" in c[-1] and "/content/input" in c[-1] for c in commands if c[1] == "exec")


def test_plan_sequence_keep_session_skips_colab_stop(tmp_path: Path):
    options = RunOptions(input_dir=str(tmp_path), keep_session=True)
    commands = driver.plan_commands(options, [])
    assert not any(c[:2] == ["colab", "stop"] for c in commands)


def test_run_handles_keyboard_interrupt(monkeypatch):
    def fake_popen(*args, **kwargs):
        raise KeyboardInterrupt()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    logs = []
    code = driver.run([["colab", "new", "-s", "vst-pipeline", "--gpu", "T4"]], logs.append)
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
    code = driver.run([["colab", "new", "-s", "vst-pipeline", "--gpu", "T4"]], logs.append)
    assert code != 0
    assert any("Precondition Failed" in line for line in logs)
    assert any("colab stop" in line for line in logs)


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
