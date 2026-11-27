"""Run actual frozen GUI and child audio jobs, without source-checkout imports."""
from __future__ import annotations

import argparse
import os
import plistlib
import subprocess
import tempfile
from pathlib import Path


def smoke(app: Path, captures: Path):
    app = app.resolve()
    captures.mkdir(parents=True, exist_ok=True)
    captures = captures.resolve()
    executable = app / 'Contents/MacOS/Automixer'
    info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
    assert info['CFBundleIdentifier'] == 'com.sulopuis.automixer'
    assert info['CFBundleShortVersionString'] == info['CFBundleVersion']
    # A frozen child must work with no checkout on PYTHONPATH and no Homebrew
    # PATH. The app's own smoke validates output/progress before its capture.
    for mode in ('files', 'folder'):
        with tempfile.TemporaryDirectory(prefix='automixer-frozen-') as home:
            environment = {key: value for key, value in os.environ.items()
                           if not key.startswith(('PYTHON', 'UV_'))}
            environment.update(HOME=home, PATH='/usr/bin:/bin',
                               AUTOMIXER_SMOKE_PNG=str(captures / f'frozen-{mode}.png'))
            command = [str(executable), '--smoke']
            if mode == 'folder':
                command.append('--smoke-folder')
            subprocess.run(command, cwd=home, env=environment, timeout=90, check=True)
            state = Path(home) / 'Library/Application Support/Automixer'
            source = state / 'native-smoke.wav'
            target = state / 'native-smoke-mixed.wav'
            assert target.is_file() and target.stat().st_size > 48000
            assert target.read_bytes() != source.read_bytes()
            assert (captures / f'frozen-{mode}.png').read_bytes().startswith(b'\x89PNG')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('app', type=Path)
    parser.add_argument('--captures', type=Path, required=True)
    arguments = parser.parse_args()
    smoke(arguments.app, arguments.captures)
