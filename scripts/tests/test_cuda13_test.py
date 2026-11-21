"""Contract tests for the opt-in CUDA experiment, no network or GPU required."""

import importlib.util
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).parents[1] / "cuda13_test.py"
spec = importlib.util.spec_from_file_location("cuda13_test", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.mark.parametrize("inventory", ["", "T4, 550.1, 7.5\n", "V100, 600.1, 7.0\n"])
def test_failed_hardware_gate_never_installs_or_clones(inventory, tmp_path, capsys):
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(stdout=inventory)

    assert module.main([], run=run, system="Linux", work_root=tmp_path) == 1
    assert len(calls) == 1
    assert calls[0][0] == "nvidia-smi"
    assert "FAIL hardware" in capsys.readouterr().out
    assert not list(tmp_path.iterdir())


def test_hardware_failure_reports_and_stops(tmp_path, capsys):
    def run(argv, **kwargs):
        raise FileNotFoundError("nvidia-smi")

    assert module.main([], run=run, system="Linux", work_root=tmp_path) == 1
    assert "FAIL hardware" in capsys.readouterr().out


def test_no_wav_is_not_claimed_as_transcription_pass(tmp_path, capsys):
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        if argv[0] == "nvidia-smi":
            return SimpleNamespace(stdout="T4, 600.1, 7.5\n")
        return SimpleNamespace(stdout=module.KUULAS_COMMIT + "\n")

    assert module.main([], run=run, system="Linux", work_root=tmp_path) == 0
    output = capsys.readouterr().out
    assert "PASS torch" in output
    assert "NOT RUN transcription" in output
    assert not any("--system" in call for call in calls)


def test_failed_install_does_not_run_gpu_smoke(tmp_path, capsys):
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        if argv[0] == "nvidia-smi":
            return SimpleNamespace(stdout="T4, 600.1, 7.5\n")
        if "sync" in argv:
            raise subprocess.CalledProcessError(1, argv)
        return SimpleNamespace(stdout=module.KUULAS_COMMIT + "\n")

    assert module.main([], run=run, system="Linux", work_root=tmp_path) == 1
    assert "FAIL install" in capsys.readouterr().out
    assert not any("scripts/cuda13_smoke.py" in call for call in calls)


def test_wav_with_spaces_is_one_argument_and_cuda_processes_are_separate(tmp_path, capsys):
    audio = tmp_path / "short speech.wav"
    audio.write_bytes(b"synthetic path fixture, not decoded by test")
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        if argv[0] == "nvidia-smi":
            return SimpleNamespace(stdout="T4, 600.1, 7.5\n")
        return SimpleNamespace(stdout=module.KUULAS_COMMIT + "\n")

    assert module.main([str(audio)], run=run, system="Linux", work_root=tmp_path) == 0
    smoke = [call for call in calls if "scripts/cuda13_smoke.py" in call]
    assert len(smoke) == 2
    assert smoke[0][-1] == "--check"
    assert smoke[1][-1] == str(audio)
    assert "PASS transcription" in capsys.readouterr().out


def test_native_windows_stops_before_commands(tmp_path, capsys):
    def run(argv, **kwargs):
        pytest.fail("must not run on native Windows")

    assert module.main([], run=run, system="Windows", work_root=tmp_path) == 1
    assert "FAIL platform" in capsys.readouterr().out
