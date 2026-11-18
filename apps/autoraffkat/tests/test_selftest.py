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
    """Ikkunoitu (console=False) Windows-build: sys.stdin/out/err ovat None.

    Lapsiprosessin täytyy yhdistää putket uudelleen ennen kuin editori lukee työnsä.
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


def test_plugin_load_reports_a_library_that_cannot_be_loaded(capsys, tmp_path):
    assert selftest.plugin_load(str(tmp_path / "puuttuu.vst3")) == 1
    assert "selftest-plugin-load: failed" in capsys.readouterr().err


def test_plugin_load_succeeds_when_the_library_loads(capsys, monkeypatch):
    import ctypes

    loaded = []
    monkeypatch.setattr(ctypes, "CDLL", lambda path: loaded.append(path))

    assert selftest.plugin_load("/x/Fake") == 0
    assert loaded == ["/x/Fake"]
    assert "selftest-plugin-load: ok" in capsys.readouterr().out


def test_plugin_load_is_an_internal_command(capsys, tmp_path):
    assert main(["--selftest-plugin-load", str(tmp_path / "puuttuu.vst3")]) == 1
