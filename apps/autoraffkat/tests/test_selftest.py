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
