"""Real advisory-lock behavior without loading any model or GPU runtime."""

import os
import subprocess
import sys

import pytest

from colabtranscribe.local_inference import local_inference_slot

pytestmark = pytest.mark.skipif(os.name == "nt", reason="local MLX uses POSIX macOS")


def test_local_slot_refuses_concurrency_and_releases_on_error(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    with pytest.raises(ValueError, match="inference failed"), local_inference_slot():
        with pytest.raises(RuntimeError, match="already running"), local_inference_slot():
            pytest.fail("second model admitted")
        raise ValueError("inference failed")
    with local_inference_slot():
        pass


def test_different_process_cannot_load_second_model(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    script = "from colabtranscribe.local_inference import local_inference_slot\n"
    script += "with local_inference_slot(): print('admitted')\n"
    with local_inference_slot():
        result = subprocess.run([sys.executable, "-c", script],
                                capture_output=True, text=True, check=False)
    assert result.returncode != 0
    assert "already running" in result.stderr
    assert "admitted" not in result.stdout
    result = subprocess.run([sys.executable, "-c", script],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert "admitted" in result.stdout


def test_killed_worker_does_not_leave_stale_lock(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    script = "from colabtranscribe.local_inference import local_inference_slot\n"
    script += "import time\nwith local_inference_slot():\n print('locked', flush=True)\n time.sleep(30)\n"
    proc = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)
    try:
        assert proc.stdout.readline().strip() == "locked"
        proc.kill()
        proc.wait(timeout=5)
        with local_inference_slot():
            pass
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.communicate(timeout=5)
