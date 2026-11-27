"""Packaging boundary contracts, independent of PyInstaller and macOS."""
import runpy
from pathlib import Path
from unittest.mock import patch

from automixer import file_jobs

ROOT = Path(__file__).resolve().parents[3]


def test_frozen_job_finds_both_bundled_media_tools(tmp_path):
    tools = tmp_path / 'bin'
    tools.mkdir()
    for name in ('ffmpeg', 'ffprobe'):
        tool = tools / name
        tool.write_text('#!/bin/sh\n')
        tool.chmod(0o755)
    with patch.object(file_jobs.sys, '_MEIPASS', str(tmp_path), create=True):
        env = file_jobs.media_environment(path='')
    assert str(tools) in env['PATH'].split(':')


def test_package_builder_requires_arm64_and_both_media_tools(tmp_path):
    import pytest
    build = runpy.run_path(str(ROOT / 'scripts/build_automixer_macos.py'))['build']
    with patch('platform.system', return_value='Linux'), pytest.raises(RuntimeError):
        build(tmp_path)
    with patch('platform.system', return_value='Darwin'), patch('platform.machine', return_value='arm64'), pytest.raises(FileNotFoundError):
        build(tmp_path)


def test_builder_passes_bundled_tools_to_frozen_worker_and_pinned_app(tmp_path):
    import os
    media = tmp_path / 'media'
    media.mkdir()
    for name in ('ffmpeg', 'ffprobe'):
        tool = media / name
        tool.write_text('#!/bin/sh\n')
        tool.chmod(0o755)
    build = runpy.run_path(str(ROOT / 'scripts/build_automixer_macos.py'))['build']
    with (patch('platform.system', return_value='Darwin'),
          patch('platform.machine', return_value='arm64'),
          patch('subprocess.check_output', side_effect=lambda cmd, **_: 'Mach-O arm64' if cmd[0] == 'file' else '/usr/lib/libSystem.B.dylib'),
          patch('subprocess.run') as run):
        app = build(media, output=tmp_path / 'dist')
    command = run.call_args.args[0]
    assert command[-1] == str(ROOT / 'apps/automixer/packaging/automixer.spec')
    assert run.call_args.kwargs['env']['AUTOMIXER_MEDIA_DIR'] == str(media)
    assert app.name == 'Automixer.app'
    assert os.environ.get('AUTOMIXER_MEDIA_DIR') is None
