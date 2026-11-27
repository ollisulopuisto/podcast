"""Portable, isolated single-file processing for desktop clients.

Only the child gets the expanded media-tool PATH. A serial queue owns one
child at a time; notifications are data for the UI's main-thread dispatcher.
"""
from __future__ import annotations

import contextlib
import json
import os
import queue
import shutil
import signal
import subprocess
import sys
import threading
from pathlib import Path

from automixer import cli_video


class JobError(Exception):
    """The job failed without replacing its source or an existing target."""


class JobCancelled(JobError):
    """Cancellation requested before publication completed."""


def media_environment(*, path=None, search_dirs=None):
    env = os.environ.copy()
    search = list(search_dirs if search_dirs is not None else [
        Path(sys.executable).parent / 'media', Path('/opt/homebrew/bin'),
        Path('/usr/local/bin'), Path('/usr/bin'), Path('/bin'),
    ])
    env['PATH'] = os.pathsep.join([env.get('PATH', '') if path is None else path,
                                 *(str(p) for p in search)])
    missing = [name for name in ('ffmpeg', 'ffprobe')
               if not shutil.which(name, path=env['PATH'])]
    if missing:
        raise JobError('Media tools not found: ' + ', '.join(missing))
    env['PYTHONUNBUFFERED'] = '1'
    return env


def output_for(source):
    source = Path(source)
    suffix = source.suffix
    if suffix.lower() == '.mov' and source.exists():
        try:
            data = subprocess.run(
                ['ffprobe', '-v', 'error', '-show_streams', '-of', 'json', str(source)],
                env=media_environment(), check=True, capture_output=True, text=True,
            )
            info = json.loads(data.stdout)
        except (subprocess.SubprocessError, ValueError) as exc:
            raise JobError('Could not inspect video format') from exc
        if any(d.get('side_data_type') == cli_video.DOLBY_VISION
               for stream in info.get('streams', []) if stream.get('codec_type') == 'video'
               for d in stream.get('side_data_list', [])):
            suffix = '.mp4'
    return source.with_name(source.stem + '-mixed' + suffix)


def worker_command(source, target, target_lufs=-16):
    return [sys.executable, '-m', 'automixer.file_worker', str(source),
            str(target), '--lufs', str(target_lufs), '--no-plugin']


def run_file(source, target, *, target_lufs=-16, cancel=None, log=lambda _line: None):
    cancel = cancel if cancel is not None else threading.Event()
    if cancel.is_set():
        raise JobCancelled('Cancelled')
    env = media_environment()
    child = subprocess.Popen(worker_command(source, target, target_lufs), env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, start_new_session=os.name != 'nt')
    lines = queue.Queue()

    def read():
        try:
            for line in child.stdout:
                lines.put(line.rstrip('\n'))
        finally:
            lines.put(None)

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    cancelled = False
    deadline = None
    import time
    try:
        while True:
            if cancel.is_set() and child.poll() is None and not cancelled:
                cancelled = True
                deadline = time.monotonic() + 5
                if os.name == 'nt':
                    child.terminate()
                else:
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(child.pid, signal.SIGTERM)
            if deadline is not None and time.monotonic() > deadline and child.poll() is None:
                if os.name == 'nt':
                    child.kill()
                else:
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(child.pid, signal.SIGKILL)
            try:
                line = lines.get(timeout=.05)
            except queue.Empty:
                continue
            if line is None:
                break
            log(line)
        code = child.wait()
        if code == 0:
            return
        if cancelled:
            raise JobCancelled('Cancelled')
        raise JobError(f'Processing failed (exit {code})')
    finally:
        if child.poll() is None:
            if os.name == 'nt':
                child.kill()
            else:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(child.pid, signal.SIGKILL)
            child.wait()
        reader.join(timeout=1)
        child.stdout.close()


class FileQueue:
    """One worker; failures do not block later jobs. Call close before exit."""

    def __init__(self, *, run=run_file, on_event=lambda _event: None):
        self._run, self._notify = run, on_event
        self._jobs = queue.Queue()
        self._lock = threading.Lock()
        self._active = set()
        self._cancel = None
        self._closed = False
        self._thread = threading.Thread(target=self._work, daemon=True)
        self._thread.start()

    def _event(self, source, state, **values):
        try:
            self._notify(dict(source=str(source), state=state, **values))
        except Exception:
            # A UI callback must not strand the worker or queue.join().
            import logging
            logging.getLogger(__name__).exception('Job notification failed')

    def add(self, source, *, target_lufs=-16):
        source = Path(source).resolve()
        with self._lock:
            if self._closed:
                raise JobError('Queue is closed')
            if source in self._active:
                return False
            self._active.add(source)
            self._jobs.put((source, target_lufs))
        return True

    def cancel(self):
        with self._lock:
            if self._cancel is not None:
                self._cancel.set()

    def wait(self):
        self._jobs.join()

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self.cancel()
        self._jobs.put(None)
        self._thread.join()

    def _work(self):
        while True:
            job = self._jobs.get()
            if job is None:
                self._jobs.task_done()
                return
            source, target_lufs = job
            self._event(source, 'queued')
            with self._lock:
                cancel = threading.Event()
                self._cancel = cancel
                closed = self._closed
            try:
                if closed:
                    raise JobCancelled('Queue closed')
                target = output_for(source)
                self._event(source, 'running', target=str(target))
                self._run(source, target, target_lufs=target_lufs, cancel=cancel,
                          log=lambda line, source=source: self._event(source, 'progress', line=line))
                self._event(source, 'done', target=str(target))
            except JobCancelled:
                self._event(source, 'cancelled')
            except Exception as exc:
                self._event(source, 'failed', error=str(exc))
            finally:
                with self._lock:
                    self._active.discard(source)
                    self._cancel = None
                self._jobs.task_done()
