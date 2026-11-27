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

    source = tmp_path / 'Library' / 'Application Support' / 'Automixer' / 'native-smoke.wav'
    output = source.with_name('native-smoke-mixed.wav')
    assert output.exists(), result.stdout + result.stderr
    import wave
    with wave.open(str(output), 'rb') as audio:
        assert audio.getnframes() == 48000
        assert audio.getnchannels() == 1
    assert source.read_bytes() != output.read_bytes()
