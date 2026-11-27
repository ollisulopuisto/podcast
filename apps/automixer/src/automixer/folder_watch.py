"""Stable-file discovery state, independent of a platform's filesystem events.

The desktop feeds directory events/debounced scans here. Only successful
fingerprints persist; startup retries interrupted work, never a successful file.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

MEDIA_SUFFIXES = frozenset({'.wav', '.mp3', '.m4a', '.flac', '.mp4', '.mov', '.mkv', '.m4v'})


class WatchError(Exception):
    """Unreadable state cannot silently become an empty processing history."""


class FolderState:
    def __init__(self, state_path, *, stable_seconds=2):
        self.path = Path(state_path)
        self.stable_seconds = stable_seconds
        self._seen = {}
        self._pending = {}
        self._failed = {}
        try:
            state = json.loads(self.path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            state = {'version': 1, 'completed': {}}
        except (OSError, ValueError) as exc:
            raise WatchError('Could not read folder processing history') from exc
        if (not isinstance(state, dict) or state.get('version') != 1
                or not isinstance(state.get('completed'), dict)
                or any(not isinstance(k, str) or not isinstance(v, list)
                       or len(v) != 2 or not all(isinstance(n, int) for n in v)
                       for k, v in state['completed'].items())):
            raise WatchError('Invalid folder processing history')
        self._completed = state['completed']

    @staticmethod
    def _fingerprint(path):
        st = path.stat()
        return [st.st_size, st.st_mtime_ns]

    def scan(self, folder, *, now):
        """Return each stable, unprocessed direct child once. Caller serializes calls."""
        folder = Path(folder).resolve()
        ready = []
        present = set()
        for source in sorted(folder.iterdir()):
            if (source.is_symlink() or not source.is_file()
                    or source.name.startswith('.') or source.stem.lower().endswith('-mixed')
                    or source.suffix.lower() not in MEDIA_SUFFIXES):
                continue
            key = str(source)
            present.add(key)
            try:
                fingerprint = self._fingerprint(source)
            except FileNotFoundError:
                continue
            if key in self._pending or self._completed.get(key) == fingerprint:
                continue
            if self._failed.get(key) == fingerprint:
                continue
            previous = self._seen.get(key)
            if previous is None or previous[0] != fingerprint:
                self._seen[key] = (fingerprint, now)
                continue
            if now - previous[1] >= self.stable_seconds:
                self._pending[key] = fingerprint
                ready.append(source)
        # A deletion/recreation must get a fresh stability interval.
        for key in list(self._seen):
            if str(Path(key).parent) == str(folder) and key not in present:
                del self._seen[key]
        return ready

    def unsettled(self):
        return any(key not in self._pending and self._completed.get(key) != value[0]
                   and self._failed.get(key) != value[0]
                   for key, value in self._seen.items())

    def complete(self, source):
        key = str(Path(source).resolve())
        if key not in self._pending:
            raise WatchError('File was not scheduled by this watcher')
        completed = {**self._completed, key: self._pending[key]}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix='.automixer-history-', dir=self.path.parent)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump({'version': 1, 'completed': completed}, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
        except OSError as exc:
            raise WatchError('Could not save folder processing history') from exc
        finally:
            Path(name).unlink(missing_ok=True)
        self._completed = completed
        del self._pending[key]
        self._failed.pop(key, None)

    def fail(self, source):
        key = str(Path(source).resolve())
        fingerprint = self._pending.pop(key, None)
        if fingerprint is not None:
            self._failed[key] = fingerprint

    def retry(self, source):
        self._failed.pop(str(Path(source).resolve()), None)
