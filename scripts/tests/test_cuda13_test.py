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


@pytest.fixture(autouse=True)
def isolated_hardware_environment(monkeypatch):
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)
    monkeypatch.setattr(module.shutil, "which", lambda name: "nvidia-smi")


@pytest.mark.parametrize("inventory", ["", "GPU-good, T4, 550.1, 7.5\n", "GPU-old, V100, 600.1, 7.0\n"])
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
            return SimpleNamespace(stdout="GPU-good, T4, 600.1, 7.5\n")
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
            return SimpleNamespace(stdout="GPU-good, T4, 600.1, 7.5\n")
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
            return SimpleNamespace(stdout="GPU-good, T4, 600.1, 7.5\n")
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


def test_external_uv_environment_is_replaced_for_every_uv_command(tmp_path, monkeypatch):
    audio = tmp_path / "short speech.wav"
    audio.write_bytes(b"path fixture, not decoded by mocked subprocess")
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", "/outside/important-env")
    monkeypatch.setenv("VIRTUAL_ENV", "/outside/active")
    monkeypatch.setenv("UV_INDEX_URL", "https://invalid.example/uv")
    monkeypatch.setenv("PIP_TARGET", "/outside/packages")
    monkeypatch.setenv("PYTHONPATH", "/outside/imports")
    monkeypatch.setenv("PYTHONHOME", "/outside/python")
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(stdout="GPU-good, T4, 600.1, 7.5\n")

    assert module.main([str(audio)], run=run, system="Linux", work_root=tmp_path) == 0
    for argv, kwargs in calls:
        if "uv" in argv:
            assert Path(kwargs["env"]["UV_PROJECT_ENVIRONMENT"]).is_relative_to(tmp_path)
            assert kwargs["env"]["UV_PROJECT_ENVIRONMENT"].endswith("kuulas/.venv")
            assert not {"VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME", "PIP_TARGET", "UV_INDEX_URL"} & kwargs["env"].keys()
            assert {key for key in kwargs["env"] if key.startswith("UV_")} == {"UV_PROJECT_ENVIRONMENT"}
            assert {key for key in kwargs["env"] if key.startswith("PIP_")} == {"PIP_CONFIG_FILE"}
            assert kwargs["env"]["PIP_CONFIG_FILE"] == module.os.devnull
            assert kwargs["env"]["CUDA_VISIBLE_DEVICES"] == "GPU-good"
    smoke = [(argv, kwargs) for argv, kwargs in calls if "scripts/cuda13_smoke.py" in argv]
    assert [argv[-1] for argv, _kwargs in smoke] == ["--check", str(audio)]


def test_uuid_selection_ignores_hidden_old_gpu(tmp_path, monkeypatch):
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "GPU-go")
    audio = tmp_path / "speech.wav"
    audio.write_bytes(b"path fixture, not decoded by mocked subprocess")
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(stdout="GPU-old, V100, 600.1, 7.0\nGPU-good, T4, 600.1, 7.5\n")

    assert module.main([str(audio)], run=run, system="Linux", work_root=tmp_path) == 0
    smoke = [(argv, kwargs) for argv, kwargs in calls if "scripts/cuda13_smoke.py" in argv]
    assert [argv[-1] for argv, _kwargs in smoke] == ["--check", str(audio)]
    for _argv, kwargs in smoke:
        assert kwargs["env"]["CUDA_VISIBLE_DEVICES"] == "GPU-good"


def test_empty_gpu_selection_fails_before_install(tmp_path, monkeypatch):
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "")
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(stdout="GPU-good, T4, 600.1, 7.5\n")

    assert module.main([], run=run, system="Linux", work_root=tmp_path) == 1
    assert len(calls) == 1


def test_wsl_nvidia_smi_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(module.shutil, "which", lambda name: None)
    original = Path.is_file
    monkeypatch.setattr(Path, "is_file", lambda p: str(p) == "/usr/lib/wsl/lib/nvidia-smi" or original(p))
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(stdout="GPU-good, T4, 600.1, 7.5\n")

    assert module.main([], run=run, system="Linux", work_root=tmp_path) == 0
    assert calls[0][0] == "/usr/lib/wsl/lib/nvidia-smi"


@pytest.mark.parametrize("selection", ["GPU-old", "-1", "MIG-unknown", "1", "0"])
def test_unsupported_or_ambiguous_device_stops(tmp_path, monkeypatch, selection):
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", selection)
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(stdout="GPU-old, V100, 600.1, 7.0\nGPU-good, T4, 600.1, 7.5\n")

    assert module.main([], run=run, system="Linux", work_root=tmp_path) == 1
    assert len(calls) == 1


@pytest.mark.parametrize("selection", [",0", " ,GPU-good", "-1,GPU-good"])
def test_disabled_first_gpu_does_not_enable_only_gpu(tmp_path, monkeypatch, selection):
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", selection)
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(stdout="GPU-good, T4, 600.1, 7.5\n")

    assert module.main([], run=run, system="Linux", work_root=tmp_path) == 1
    assert len(calls) == 1


def test_pip_config_cannot_redirect_bootstrap_install(tmp_path, monkeypatch):
    monkeypatch.setenv("PIP_CONFIG_FILE", "/external/pip.conf")
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(stdout="GPU-good, T4, 600.1, 7.5\n")

    assert module.main([], run=run, system="Linux", work_root=tmp_path) == 0
    pip_call = next(kwargs for argv, kwargs in calls if "pip" in argv)
    assert pip_call["env"]["PIP_CONFIG_FILE"] == module.os.devnull
