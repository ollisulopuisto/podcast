"""autovideo Finderin pikatoimintona.

Finder käynnistää skriptin ilman käyttäjän PATHia (vain /usr/bin:/bin:
/usr/sbin:/sbin), eikä kukaan näe sen tulostetta. Siksi viat ovat hiljaisia:
uv jää löytymättä, tila puuttuu ja dxRevive ajaa oletusmallinsa, tai ajo
kaatuu eikä virheestä jää jälkeä. Testit ajavat oikean skriptin väärennetyllä
`uv`:lla ja `osascript`illa, jotka kirjaavat kutsunsa.
"""

from __future__ import annotations

import os
import plistlib
import subprocess
from pathlib import Path

from automixer import finder_action

FINDER_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"


def fake_tools(bin_dir: Path, uv_exit: int = 0) -> None:
    """`uv` ja `osascript`, jotka kirjoittavat argumenttinsa tiedostoon."""
    bin_dir.mkdir()
    for name, code in (("uv", uv_exit), ("osascript", 0)):
        tool = bin_dir / name
        tool.write_text(
            "#!/bin/bash\n"
            f'printf "%s\\n" "$@" >> "{bin_dir}/{name}.calls"\n'
            f'echo "{name} output"\n'
            f"exit {code}\n"
        )
        tool.chmod(0o755)


def run_action(tmp_path: Path, files: list[Path], *, state: bool = True,
               uv_exit: int = 0) -> tuple[subprocess.CompletedProcess, Path, Path]:
    bin_dir = tmp_path / "bin"
    fake_tools(bin_dir, uv_exit)
    state_file = tmp_path / "support" / "dx.state"
    if state:
        state_file.parent.mkdir()
        state_file.write_text("c3RhdGU=")
    log = tmp_path / "autovideo.log"
    env = {
        "HOME": str(tmp_path),
        # Väärennökset ennen Finderin PATHia: oikea osascript on /usr/binissä
        # ja lähettäisi testistä oikeita ilmoituksia.
        "PATH": f"{bin_dir}:{FINDER_PATH}",
        "AUTOVIDEO_STATE": str(state_file),
        "AUTOVIDEO_LOG": str(log),
    }
    done = subprocess.run(
        ["/bin/bash", str(finder_action.RUNNER), *map(str, files)],
        env=env, capture_output=True, text=True, check=False,
    )
    return done, bin_dir, log


def calls(bin_dir: Path, name: str) -> str:
    path = bin_dir / f"{name}.calls"
    return path.read_text() if path.exists() else ""


def test_each_file_runs_autovideo_in_the_app_with_the_state(tmp_path):
    clips = [tmp_path / "a clip.mov", tmp_path / "b.mp4"]
    done, bin_dir, _ = run_action(tmp_path, clips)
    assert done.returncode == 0, done.stderr
    uv = calls(bin_dir, "uv").splitlines()
    state = str(tmp_path / "support" / "dx.state")
    expected = []
    for clip in clips:
        expected += ["run", "--project", str(finder_action.PROJECT), "autovideo",
                     str(clip), "--state", state]
    assert uv == expected
    assert calls(bin_dir, "osascript").count("autovideo done") == 2


def test_missing_state_refuses_instead_of_running_the_default_model(tmp_path):
    """Ilman tilaa dxRevive ajaa oletusmallinsa ja tulos on kelvollinen,
    tasoltaan oikea ja väärin korjattu — juuri se hiljainen vika."""
    done, bin_dir, _ = run_action(tmp_path, [tmp_path / "a.mov"], state=False)
    assert done.returncode != 0
    assert calls(bin_dir, "uv") == ""
    assert "--edit" in calls(bin_dir, "osascript")


def test_failure_is_reported_and_its_output_kept(tmp_path):
    done, bin_dir, log = run_action(tmp_path, [tmp_path / "a.mov"], uv_exit=1)
    assert done.returncode != 0
    assert "FAILED" in calls(bin_dir, "osascript")
    assert "uv output" in log.read_text()


def test_one_failure_does_not_stop_the_rest(tmp_path):
    clips = [tmp_path / "a.mov", tmp_path / "b.mov"]
    _, bin_dir, _ = run_action(tmp_path, clips, uv_exit=1)
    assert calls(bin_dir, "uv").count("autovideo") == 2


def test_workflow_is_a_finder_quick_action_for_movies(tmp_path):
    bundle = finder_action.write_workflow(tmp_path / "autovideo.workflow")
    info = plistlib.loads((bundle / "Contents" / "Info.plist").read_bytes())
    service = info["NSServices"][0]
    assert service["NSMessage"] == "runWorkflowAsService"
    assert service["NSMenuItem"]["default"] == "autovideo"
    assert service["NSRequiredContext"]["NSApplicationIdentifier"] == "com.apple.finder"
    assert service["NSSendFileTypes"] == ["public.movie"]

    doc = plistlib.loads((bundle / "Contents" / "document.wflow").read_bytes())
    (step,) = doc["actions"]
    params = step["action"]["ActionParameters"]
    # 1 = argumentteina; 0 antaisi tiedostot stdiniin ja "$@" olisi tyhjä.
    assert params["inputMethod"] == 1
    assert params["COMMAND_STRING"] == f'exec /bin/bash "{finder_action.RUNNER}" "$@"'
    assert doc["workflowMetaData"]["workflowTypeIdentifier"] == \
        "com.apple.Automator.servicesMenu"


def test_workflow_command_runs_the_selected_files(tmp_path):
    """Automatorin komento on sama kuin ajettu: `bash -c` samoilla
    argumenteilla kuin Automator antaa."""
    bundle = finder_action.write_workflow(tmp_path / "autovideo.workflow")
    doc = plistlib.loads((bundle / "Contents" / "document.wflow").read_bytes())
    command = doc["actions"][0]["action"]["ActionParameters"]["COMMAND_STRING"]
    bin_dir = tmp_path / "bin"
    fake_tools(bin_dir)
    (tmp_path / "dx.state").write_text("x")
    env = {"HOME": str(tmp_path), "PATH": f"{bin_dir}:{FINDER_PATH}",
           "AUTOVIDEO_STATE": str(tmp_path / "dx.state"),
           "AUTOVIDEO_LOG": str(tmp_path / "log")}
    done = subprocess.run(["/bin/bash", "-c", command, "bash", "/x/a b.mov"],
                          env=env, capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr
    assert "/x/a b.mov" in calls(bin_dir, "uv").splitlines()


def test_install_replaces_an_old_bundle_and_copies_the_state_once(tmp_path):
    services = tmp_path / "Services"
    stale = services / "autovideo.workflow" / "Contents" / "stale"
    stale.parent.mkdir(parents=True)
    stale.write_text("old")
    source_state = tmp_path / "repo-dx.state"
    source_state.write_text("repo")
    target_state = tmp_path / "support" / "dx.state"

    finder_action.install(services, source_state, target_state)
    assert not stale.exists()
    assert (services / "autovideo.workflow" / "Contents" / "Info.plist").exists()
    assert target_state.read_text() == "repo"

    # Käyttäjän myöhemmin valitsema malli ei jää uudelleenasennuksen alle.
    target_state.write_text("chosen")
    finder_action.install(services, source_state, target_state)
    assert target_state.read_text() == "chosen"


def test_runner_is_executable():
    """Finder ajaa sen `bash`illa, mutta käsin ajettaessa suoritusbitti ratkaisee."""
    assert os.access(finder_action.RUNNER, os.X_OK)
