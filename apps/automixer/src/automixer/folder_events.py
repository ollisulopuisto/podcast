"""macOS vnode notifications and bounded stable-file rechecks, no UI polling."""
from __future__ import annotations

import threading
import time


class StabilityChecks:
    def __init__(self, scan, *, later=None, clock=time.monotonic):
        self.scan, self.clock = scan, clock
        self._later = later or self._timer
        self._lock = threading.Lock()
        self._scheduled = False
        self._closed = False
        self._generation = 0

    @staticmethod
    def _timer(delay, callback):
        timer = threading.Timer(delay, callback)
        timer.daemon = True
        timer.start()

    def changed(self):
        with self._lock:
            if self._closed:
                return
            self._generation += 1
            if self._scheduled:
                return
            self._scheduled = True
        self._later(.1, self._first)

    def _first(self):
        with self._lock:
            if self._closed:
                return
            generation = self._generation
        self.scan(now=self.clock())
        self._later(2.1, lambda: self._settled(generation))

    def _settled(self, generation):
        with self._lock:
            if self._closed:
                return
        unsettled = self.scan(now=self.clock())
        with self._lock:
            changed = generation != self._generation or bool(unsettled)
            self._scheduled = changed
        if changed:
            self._later(.1, self._first)

    def close(self):
        with self._lock:
            self._closed = True


class MacFolderEvents:
    """Native filesystem observer. close() cancels pending stability checks."""

    def __init__(self, folder, scan, *, on_error=lambda _e: None):
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer

        def guarded(**kwargs):
            try:
                return scan(**kwargs)
            except Exception as exc:
                on_error(exc)
                return False

        self._checks = StabilityChecks(guarded)
        checks = self._checks

        class Handler(FileSystemEventHandler):
            def on_any_event(self, event):
                if event.event_type in {'created', 'modified', 'moved', 'deleted'}:
                    checks.changed()

        self._observer = Observer()
        self._observer.schedule(Handler(), str(folder), recursive=False)
        self._observer.start()
        self._checks.changed()

    def changed(self):
        self._checks.changed()

    def close(self):
        self._checks.close()
        self._observer.stop()
        self._observer.join(timeout=3)
