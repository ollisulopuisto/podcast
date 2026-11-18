"""``--selftest-jit`` ajaa ääniketjun JIT-polun; sen on pysyttävä toimivana."""

from __future__ import annotations

import pytest

pytest.importorskip("numba")

from autoraffkat import selftest
from autoraffkat.__main__ import main


def test_selftest_runs_the_audio_kernels(capsys):
    assert selftest.main() == 0
    assert "selftest-jit: ok" in capsys.readouterr().out


def test_selftest_is_an_internal_command(capsys):
    assert main(["--selftest-jit"]) == 0


def test_plugin_editor_command_restores_unset_streams():
    """Windowed (console=False) Windows build: sys.stdin/out/err are None.

    The child must reconnect the pipes before the editor reads its job.
    """
    import json
    import subprocess
    import sys

    code = (
        "import sys; sys.stdin = sys.stdout = sys.stderr = None\n"
        "from autoraffkat.__main__ import main\n"
        "raise SystemExit(main(['--plugin-editor']))\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", code],
        input=json.dumps({"plugin_path": "", "params": {}, "state": None}),
        capture_output=True, text=True, timeout=120,
    )
    first = json.loads(done.stdout.splitlines()[0])
    assert first["kind"] == "failed", done.stderr
    assert done.returncode == 1
