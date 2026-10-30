"""Session-only settings history must retain alternate branches without a cap."""
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="node missing")
def test_uncapped_branching_history():
    here = Path(__file__).parent
    app = here.parent / "src/autoraffkat/server/static/app.js"
    done = subprocess.run(
        ["node", str(here / "ui_history.js"), str(app)],
        capture_output=True, text=True, timeout=30,
    )
    assert done.returncode == 0, done.stderr
    assert "1000 edits" in done.stdout
