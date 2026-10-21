"""The list of test modules left out where mlx is missing must be true.

``mlx_modules.NEEDS_MLX`` is not collected on Linux. A module that stopped
needing mlx would then lose its Linux coverage without a word, and a module
missing from the list fails the Linux job at collection. This proves the
first half on every machine, macOS included: each listed module really cannot
be imported with mlx made unimportable, and does fail on mlx and not on
something else.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from mlx_modules import NEEDS_MLX

HERE = Path(__file__).parent

IMPORT = (
    "import importlib.util, sys; "
    "sys.modules['mlx'] = None; "
    "sys.path[:0] = [sys.argv[2]]; "
    "spec = importlib.util.spec_from_file_location('probe', sys.argv[1]); "
    "spec.loader.exec_module(importlib.util.module_from_spec(spec))"
)


def test_every_listed_module_exists():
    assert [m for m in NEEDS_MLX if not (HERE / m).is_file()] == []


@pytest.mark.parametrize("module", NEEDS_MLX)
def test_a_listed_module_cannot_be_imported_without_mlx(module):
    done = subprocess.run(
        [sys.executable, "-c", IMPORT, str(HERE / module), str(HERE)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert done.returncode != 0, f"{module} imports without mlx: take it off the list"
    assert "mlx" in done.stderr.splitlines()[-1], done.stderr[-400:]
