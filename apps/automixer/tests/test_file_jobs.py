"""Single-file jobs serialize work, preserve originals, and cancel children."""
import os

import pytest

from automixer import file_jobs


def test_finder_path_searches_homebrew_without_changing_parent(tmp_path):
    for name in ('ffmpeg', 'ffprobe'):
        binary = tmp_path / name
        binary.write_text('#!/bin/sh\n')
        binary.chmod(0o755)
    original = os.environ.get('PATH')
    env = file_jobs.media_environment(path='', search_dirs=[tmp_path])
    assert str(tmp_path) in env['PATH'].split(os.pathsep)
    assert os.environ.get('PATH') == original


def test_output_naming_uses_existing_container_rules(tmp_path, monkeypatch):
    assert file_jobs.output_for(tmp_path / 'clip.mov') == tmp_path / 'clip-mixed.mov'


def test_worker_command_has_plugin_off_and_explicit_level(tmp_path):
    command = file_jobs.worker_command(tmp_path / 'in.wav', tmp_path / 'out.wav', -20)
    assert '--no-plugin' in command
    assert command[command.index('--lufs') + 1] == '-20'


def test_worker_processes_real_file_and_refuses_collision(tmp_path):
    import numpy as np
    import soundfile as sf
    source = tmp_path / 'source.wav'
    sf.write(source, np.random.default_rng(3).normal(0, .04, 48000), 48000)
    target = tmp_path / 'out.wav'
    logs = []
    file_jobs.run_file(source, target, log=logs.append)
    original = target.read_bytes()
    assert logs
    with pytest.raises(file_jobs.JobError):
        file_jobs.run_file(source, target)
    assert target.read_bytes() == original


def test_serial_queue_deduplicates_active_and_reports_failure_then_continues(tmp_path):
    calls, events = [], []
    def run(source, target, **kwargs):
        calls.append(source.name)
        if source.name == 'bad.wav':
            raise file_jobs.JobError('bad file')
        target.write_bytes(b'done')
    queue = file_jobs.FileQueue(run=run, on_event=events.append)
    try:
        queue.add(tmp_path / 'bad.wav')
        queue.add(tmp_path / 'good.wav')
        queue.wait()
        assert calls == ['bad.wav', 'good.wav']
        assert [e['state'] for e in events if e['state'] in {'failed', 'done'}] == ['failed', 'done']
    finally:
        queue.close()


def test_cancel_stops_child_and_does_not_publish(tmp_path):
    import threading
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(file_jobs.JobCancelled):
        file_jobs.run_file(tmp_path / 'in.wav', tmp_path / 'out.wav', cancel=cancel)
    assert not (tmp_path / 'out.wav').exists()


def test_active_duplicate_and_cancellation_are_serial(tmp_path):
    import threading
    entered, release = threading.Event(), threading.Event()
    calls, events = [], []
    def run(source, target, **kwargs):
        calls.append(source.name)
        entered.set()
        if not release.wait(2):
            raise AssertionError('test worker not released')
        if kwargs['cancel'].is_set():
            raise file_jobs.JobCancelled('Cancelled')
        target.write_bytes(b'done')
    q = file_jobs.FileQueue(run=run, on_event=events.append)
    try:
        assert q.add(tmp_path / 'one.wav')
        assert entered.wait(2)
        assert not q.add(tmp_path / 'one.wav')
        assert q.add(tmp_path / 'two.wav')
        assert calls == ['one.wav']
        q.cancel()
        release.set()
        q.wait()
        assert calls == ['one.wav', 'two.wav']
        assert [e['state'] for e in events if e['state'] in {'cancelled', 'done'}] == ['cancelled', 'done']
    finally:
        release.set()
        q.close()


def test_cancel_running_process_group(tmp_path, monkeypatch):
    import sys
    import threading
    marker = tmp_path / 'child-started'
    monkeypatch.setattr(file_jobs, 'worker_command', lambda *args: [
        sys.executable, '-u', '-c',
        'import pathlib,time,sys; pathlib.Path(sys.argv[1]).touch(); print("ready",flush=True); time.sleep(30)',
        str(marker),
    ])
    cancel = threading.Event()
    def on_line(line):
        if line == 'ready':
            cancel.set()
    with pytest.raises(file_jobs.JobCancelled):
        file_jobs.run_file(tmp_path / 'in.wav', tmp_path / 'out.wav', cancel=cancel, log=on_line)
    assert marker.exists()
    assert not (tmp_path / 'out.wav').exists()


def test_mov_probe_uses_discovered_environment_and_preserves_dolby(tmp_path, monkeypatch):
    from types import SimpleNamespace
    source = tmp_path / 'clip.MOV'
    source.touch()
    monkeypatch.setattr(file_jobs, 'media_environment', lambda: {'PATH': 'discovered'})
    def probe(*args, **kwargs):
        assert kwargs['env']['PATH'] == 'discovered'
        return SimpleNamespace(stdout='{"streams":[{"codec_type":"video","side_data_list":[{"side_data_type":"DOVI configuration record"}]}]}')
    monkeypatch.setattr(file_jobs.subprocess, 'run', probe)
    assert file_jobs.output_for(source) == tmp_path / 'clip-mixed.mp4'


def test_custom_media_directory_is_used_only_in_child_environment(tmp_path, monkeypatch):
    import os
    import stat
    before = os.environ.get('PATH')
    for name in ('ffmpeg', 'ffprobe'):
        tool = tmp_path / name
        tool.write_text('#!/bin/sh\nexit 0\n')
        tool.chmod(tool.stat().st_mode | stat.S_IXUSR)
    env = file_jobs.media_environment(path='', search_dirs=[tmp_path])
    assert env['PATH'].split(os.pathsep)[-1] == str(tmp_path)
    assert os.environ.get('PATH') == before
    with pytest.raises(file_jobs.MissingTools):
        file_jobs.media_environment(path='', search_dirs=[])


def test_missing_tools_report_distinct_recoverable_state(tmp_path):
    events = []
    def run(*args, **kwargs):
        raise file_jobs.MissingTools('ffmpeg and ffprobe unavailable')
    q = file_jobs.FileQueue(run=run, on_event=events.append)
    try:
        q.add(tmp_path / 'audio.wav')
        q.wait()
        assert events[-1]['state'] == 'failed'
        assert events[-1]['error_kind'] == 'missing_tools'
    finally:
        q.close()


def test_selected_tools_take_precedence_over_inherited_path(tmp_path):
    custom = tmp_path / 'custom'
    inherited = tmp_path / 'old'
    for folder in (custom, inherited):
        folder.mkdir()
        for name in ('ffmpeg', 'ffprobe'):
            tool = folder / name
            tool.touch()
            tool.chmod(0o755)
    env = file_jobs.media_environment(path=str(inherited), search_dirs=[], tools_dir=custom)
    import shutil
    assert shutil.which('ffmpeg', path=env['PATH']) == str(custom / 'ffmpeg')
