"""PyInstaller käynnistää ohjelman paketin kautta."""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_pyinstaller_uses_package_aware_launcher():
    spec = (ROOT / "podcast-magic.spec").read_text(encoding="utf-8")
    assert 'BASE_DIR / "scripts" / "launch_app.py"' in spec


def test_launcher_reports_the_packaged_version():
    result = subprocess.run(
        [sys.executable, "scripts/launch_app.py", "--version"],
        cwd=ROOT,
        capture_output=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "2026.10.26.1"
