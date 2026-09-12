"""Apuohjelmien ja ympäristömuuttujien tarkistuksen ja opastuksen (onboarding) testit.

Käyttäjää ei saa jättää pulaan puuttuvan `colab`-komennon tai
tunnistetietojen kanssa: järjestelmä tarkistaa tarpeet etukäteen ja
antaa selkeät asennus- ja kirjautumisohjeet.
"""

from __future__ import annotations

from pathlib import Path

from colabtranscribe.onboarding import (
    check_credentials,
    check_environment,
    check_helper_apps,
)
from colabtranscribe.options import RunOptions


def test_missing_colab_is_reported_with_install_instructions(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda cmd: None)
    items = check_helper_apps()
    colab_item = next(i for i in items if i.key == "colab")
    assert not colab_item.ok
    assert "uv tool install google-colab-cli" in colab_item.instructions


def test_found_colab_is_reported_as_ok(monkeypatch):
    monkeypatch.setattr(
        "shutil.which", lambda cmd: "/opt/homebrew/bin/colab" if cmd == "colab" else None
    )
    items = check_helper_apps()
    colab_item = next(i for i in items if i.key == "colab")
    assert colab_item.ok
    assert colab_item.current_value == "/opt/homebrew/bin/colab"


def test_missing_credentials_reported_with_login_instructions(monkeypatch, tmp_path):
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    items = check_credentials()
    cred_item = next(i for i in items if i.key == "credentials")
    assert not cred_item.ok
    assert "gcloud auth application-default login" in cred_item.instructions
    assert "GOOGLE_APPLICATION_CREDENTIALS" in cred_item.instructions


def test_credentials_ok_when_adc_file_exists(monkeypatch, tmp_path):
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    fake_home = tmp_path / "home"
    gcloud_dir = fake_home / ".config" / "gcloud"
    gcloud_dir.mkdir(parents=True)
    (gcloud_dir / "application_default_credentials.json").write_text(
        "{}", encoding="utf-8"
    )
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    items = check_credentials()
    cred_item = next(i for i in items if i.key == "credentials")
    assert cred_item.ok


def test_credentials_ok_when_env_var_points_to_file(monkeypatch, tmp_path):
    cred_file = tmp_path / "sa.json"
    cred_file.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(cred_file))

    items = check_credentials()
    cred_item = next(i for i in items if i.key == "credentials")
    assert cred_item.ok
    assert str(cred_file) in cred_item.current_value


def test_credentials_ok_when_colab_token_exists(monkeypatch, tmp_path):
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    fake_home = tmp_path / "home"
    colab_dir = fake_home / ".config" / "colab-cli"
    colab_dir.mkdir(parents=True)
    (colab_dir / "token.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    items = check_credentials()
    cred_item = next(i for i in items if i.key == "credentials")
    assert cred_item.ok


def test_check_environment_is_ready_only_when_all_required_ok(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "shutil.which", lambda cmd: "/bin/colab" if cmd == "colab" else None
    )
    cred_file = tmp_path / "creds.json"
    cred_file.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(cred_file))

    report = check_environment()
    assert report.is_ready is True

    monkeypatch.setattr("shutil.which", lambda cmd: None)
    report2 = check_environment()
    assert report2.is_ready is False


def test_run_options_reads_environment_variables(monkeypatch):
    monkeypatch.setenv("COLAB_SESSION", "oma-sessio")
    monkeypatch.setenv("COLAB_GPU", "A100")
    monkeypatch.setenv("COLAB_INPUT_DIR", "/tmp/syote")
    monkeypatch.setenv("COLAB_OUTPUT_DIR", "/tmp/tulos")
    monkeypatch.setenv("COLAB_PRESET", "intra-mic")

    options = RunOptions.from_env()
    assert options.session == "oma-sessio"
    assert options.gpu == "A100"
    assert options.input_dir == "/tmp/syote"
    assert options.output_dir == "/tmp/tulos"
    assert options.preset == "intra-mic"


def test_patch_colab_cli_automation(tmp_path: Path, monkeypatch):
    from colabtranscribe.onboarding import patch_colab_cli_automation

    # Setup fake colab executable and fake automation.py
    fake_py = tmp_path / "python3"
    fake_py.write_text("#!/bin/sh\nexit 0\n")
    fake_py.chmod(0o755)

    fake_colab = tmp_path / "colab"
    fake_colab.write_text(f"#!{fake_py}\n# fake colab\n")
    fake_colab.chmod(0o755)

    fake_automation = tmp_path / "automation.py"
    unpatched_content = (
        "def drivefs_hook():\n"
        "    if not data.get('success'):\n"
        "        try:\n"
        "            webbrowser.open(uri)\n"
        '            typer.echo("[colab] Opening authorization URL automatically in your default browser...")\n'
        "        except Exception:\n"
        "            pass\n"
        '        sys.stdout.write("Press Enter after you have granted access... ")\n'
        "        sys.stdout.flush()\n"
        '        with open("/dev/tty") as tty:\n'
        "            tty.readline()\n"
        "    return True\n"
    )
    fake_automation.write_text(unpatched_content, encoding="utf-8")

    import subprocess

    orig_run = subprocess.run

    def fake_subprocess_run(cmd, *args, **kwargs):
        if len(cmd) >= 3 and "colab_cli.commands.automation" in cmd[2]:

            class FakeResult:
                returncode = 0
                stdout = str(fake_automation)
                stderr = ""

            return FakeResult()
        return orig_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", fake_subprocess_run)

    res = patch_colab_cli_automation(str(fake_colab))
    assert res is True

    patched_content = fake_automation.read_text(encoding="utf-8")
    assert 'with open("/dev/tty")' not in patched_content
    assert "Waiting for authorization in browser" in patched_content
    assert "COLAB_CLI_NO_BROWSER" in patched_content
