#!/usr/bin/env python3
"""Opt-in Linux/Colab/WSL2 CUDA 13 smoke test, no driver or global installs.

Pass a short speech WAV path to include transcription. In Colab mount Drive
first and pass its path. Audio is processed on the machine running this script.
First use downloads several GB of packages and public Whisper model weights.
"""

import argparse
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

KUULAS_COMMIT = "f22296ee821236a7611d8a337136055a07fb663d"
PODCAST_COMMIT = "40a7d503c2637e7c685c7ca1c56850385524600e"  # Snapshot with the path packages used to resolve the experiment.
UV_VERSION = "0.13.9"


def main(argv=None, *, run=subprocess.run, system=None, work_root=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wav", nargs="?", type=Path, help="optional local or mounted Drive WAV")
    args = parser.parse_args(argv)
    if (system or platform.system()) != "Linux":
        print("FAIL platform: run in Linux, Colab or WSL2, not macOS/native Windows")
        return 1
    audio = args.wav.expanduser().resolve() if args.wav is not None else None
    if audio is not None and (not audio.is_file() or audio.suffix.lower() != ".wav"):
        print("FAIL input: provide an existing short speech WAV; no downloads started")
        return 1
    stage = "hardware"
    try:
        probe = shutil.which("nvidia-smi")
        if probe is None:
            wsl_probe = Path("/usr/lib/wsl/lib/nvidia-smi")
            probe = str(wsl_probe) if wsl_probe.is_file() else "nvidia-smi"
        result = run(
            [probe, "--query-gpu=uuid,name,driver_version,compute_cap", "--format=csv,noheader"],
            check=True, capture_output=True, text=True, timeout=30,
        )
        if not result.stdout.strip():
            raise ValueError("no NVIDIA GPU assigned")
        inventory = [[value.strip() for value in row.split(",")]
                     for row in result.stdout.strip().splitlines()]
        visible = os.environ.get("CUDA_VISIBLE_DEVICES")
        if visible is not None:
            if not visible.strip() or visible.strip() == "-1":
                raise ValueError("CUDA_VISIBLE_DEVICES disables all GPUs")
            selection = visible.split(",")[0].strip()
            if selection.isdigit():
                if len(inventory) != 1 or selection != "0":
                    raise ValueError("For multiple GPUs use a stable GPU UUID, not numeric ordering")
                selected = inventory[0]
            else:
                matches = [gpu for gpu in inventory if gpu[0].startswith(selection)]
                if len(matches) != 1:
                    raise ValueError("Selected GPU UUID is missing or ambiguous")
                selected = matches[0]
        else:
            compatible = [gpu for gpu in inventory
                          if int(gpu[2].split(".")[0]) >= 580 and float(gpu[3]) >= 7.5]
            if not compatible:
                raise ValueError("CUDA 13 needs driver family >=580 and Turing or newer")
            selected = compatible[0]
        uuid, name, driver, capability = selected
        print(f"Selected GPU: {name}; UUID: {uuid}; driver: {driver}; capability: {capability}")
        if int(driver.split(".")[0]) < 580 or float(capability) < 7.5:
            raise ValueError("Selected GPU does not support the CUDA 13 experiment")
        print("PASS hardware: driver-family/architecture gate; actual kernels checked below")
        stage = "checkout"
        with tempfile.TemporaryDirectory(prefix="podcast-cuda13-", dir=work_root) as folder:
            root = Path(folder)
            kuulas = root / "kuulas"
            podcast = root / "podcast"
            run(["git", "clone", "--branch", "experiment/cuda13-torch213", "--single-branch",
                 "https://github.com/ollisulopuisto/kuulas.git", str(kuulas)],
                check=True, timeout=300)
            run(["git", "checkout", "--detach", KUULAS_COMMIT], cwd=kuulas,
                check=True, timeout=60)
            run(["git", "clone", "https://github.com/ollisulopuisto/podcast.git", str(podcast)],
                check=True, timeout=300)
            run(["git", "checkout", "--detach", PODCAST_COMMIT], cwd=podcast,
                check=True, timeout=60)
            print(f"PASS checkout: pinned experiment {KUULAS_COMMIT}")
            stage = "install"
            bootstrap = root / "bootstrap"
            child_env = {key: value for key, value in os.environ.items()
                         if not key.startswith(("UV_", "PIP_"))
                         and key not in {"VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME"}}
            child_env["UV_PROJECT_ENVIRONMENT"] = str(kuulas / ".venv")
            child_env["CUDA_VISIBLE_DEVICES"] = uuid
            run([sys.executable, "-m", "venv", str(bootstrap)], env=child_env, check=True, timeout=120)
            python = str(bootstrap / "bin" / "python")
            run([python, "-m", "pip", "--isolated", "install", "uv==" + UV_VERSION],
                env=child_env, check=True, timeout=300)
            uv = [python, "-m", "uv"]
            run([*uv, "sync", "--locked", "--extra", "transcribe", "--python", "3.13"],
                cwd=kuulas, env=child_env, check=True, timeout=3600)
            print("PASS install: isolated locked environment; no global packages changed")
            stage = "torch"
            command = [*uv, "run", "--frozen", "--extra", "transcribe", "python",
                       "scripts/cuda13_smoke.py"]
            run([*command, "--check"], cwd=kuulas, env=child_env, check=True, timeout=180)
            print("PASS torch: CUDA 13 tensor calculation and TorchAudio API")
            if audio is not None:
                stage = "transcription"
                run([*command, str(audio)], cwd=kuulas, env=child_env, check=True, timeout=900)
                print("PASS transcription: nonempty GPU Whisper output, no CPU fallback")
            else:
                print("NOT RUN transcription: pass a short speech WAV as the optional argument")
        print("PASS requested stages; full Kuulas GUI, CTC model and other machines remain untested")
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"FAIL {stage}: {type(error).__name__}: {error}")
        print("STOP: later stages were not run. No driver install or CPU fallback attempted.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
