"""Build an arm64 Automixer app. Signing/notarization is a separate release gate."""
from __future__ import annotations

import argparse
import os
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build(media_dir: Path, *, output: Path | None = None):
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        raise RuntimeError('Build on an Apple Silicon Mac')
    media_dir = Path(media_dir).resolve()
    for name in ('ffmpeg', 'ffprobe'):
        binary = media_dir / name
        if not binary.is_file() or not os.access(binary, os.X_OK):
            raise FileNotFoundError(f'Standalone executable required: {binary}')
        description = subprocess.check_output(['file', '-b', str(binary)], text=True)
        if 'arm64' not in description:
            raise RuntimeError(f'{name} must contain arm64 code')
        linked = subprocess.check_output(['otool', '-L', str(binary)], text=True)
        if '/opt/homebrew/' in linked or '/usr/local/' in linked:
            raise RuntimeError(f'{name} is not standalone; it links a package-manager library')
    output = (output or ROOT / 'dist/automixer-macos').resolve()
    subprocess.run([
        sys.executable, '-m', 'PyInstaller', '--noconfirm',
        '--distpath', str(output), '--workpath', str(output / '.build'),
        str(ROOT / 'apps/automixer/packaging/automixer.spec'),
    ], cwd=ROOT, env={**os.environ, 'AUTOMIXER_MEDIA_DIR': str(media_dir)}, check=True)
    return output / 'Automixer.app'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--media-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    arguments = parser.parse_args()
    print(build(arguments.media_dir, output=arguments.output))
