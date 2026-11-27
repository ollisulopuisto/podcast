"""Launch the real AppKit window on the existing Mac test job."""
import os
import subprocess
import sys
from pathlib import Path

import pytest


def test_native_shell_renders_window_on_mac(tmp_path):
    if sys.platform != 'darwin':
        pytest.skip('native AppKit requires macOS')
    screenshot = Path(os.environ.get('AUTOMIXER_SMOKE_PNG', '/tmp/automixer-smoke.png'))
    screenshot.unlink(missing_ok=True)
    env = {**os.environ, 'AUTOMIXER_SMOKE_PNG': str(screenshot), 'HOME': str(tmp_path)}
    result = subprocess.run([sys.executable, '-m', 'automixer.mac_gui', '--smoke'],
                            capture_output=True, text=True, env=env, timeout=25)
    assert result.returncode == 0, result.stdout + result.stderr
    assert screenshot.read_bytes().startswith(b'\x89PNG')
    assert screenshot.stat().st_size > 5000
