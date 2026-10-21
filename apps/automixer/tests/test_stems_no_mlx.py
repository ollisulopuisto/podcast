"""The stems CLI path must work without importing Apple's mlx runtime."""

import json
import os
import subprocess
import sys

import numpy as np
import soundfile as sf

RATE = 48_000


def test_cli_mixes_stems_folder_without_mlx_in_subprocess(tmp_path):
    folder = tmp_path / "stems"
    folder.mkdir()
    frames = 12 * RATE
    samples = (0.2 * np.sin(2 * np.pi * 180 * np.arange(frames) / RATE)).astype(
        np.float32
    )
    sf.write(folder / "voice.wav", samples, RATE, subtype="PCM_24")
    (folder / "tracks.json").write_text(
        json.dumps(
            {
                "edit": "test",
                "project": "test",
                "version": 1,
                "rate": RATE,
                "start_frame": 0,
                "frames": frames,
                "processing": "dry",
                "format": "wav",
                "bit_depth": 24,
                "tracks": [
                    {
                        "id": "voice",
                        "name": "voice",
                        "kind": "speech",
                        "speaker": "",
                        "channels": 1,
                        "file": "voice.wav",
                        "audible": True,
                        "gain_db": 0.0,
                        "pan": 0.0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "linux mix.wav"
    code = (
        "import sys; sys.modules['mlx'] = None; "
        "from automixer import cli_mix; "
        "sys.argv = ['automixer', sys.argv[1], '-o', sys.argv[2]]; cli_mix.main()"
    )
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    result = subprocess.run(
        [sys.executable, "-c", code, str(folder), str(output)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert output.exists()
