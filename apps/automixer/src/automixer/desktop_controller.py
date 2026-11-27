"""UI-independent command registry and desktop job coordination."""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from pathlib import Path

from automixer.file_jobs import FileQueue, JobError
from automixer.folder_watch import MEDIA_SUFFIXES, FolderState, WatchError


@dataclass(frozen=True)
class Command:
    id: str
    menu: str
    title_en: str
    title_fi: str
    key: str = ''


COMMANDS = (
    Command('add', 'File', 'Add Files...', 'Lisää tiedostoja...', 'o'),
    Command('folder', 'File', 'Watch Folder...', 'Seuraa kansiota...', 'O'),
    Command('start', 'Process', 'Start', 'Aloita', '\r'),
    Command('cancel', 'Process', 'Cancel', 'Peru', '.'),
    Command('reveal', 'File', 'Reveal Output', 'Näytä tulos Finderissa', 'r'),
    Command('changes', 'Help', "What's New", 'Uutta tässä versiossa'),
    Command('shortcuts', 'Help', 'Keyboard Shortcuts', 'Pikanäppäimet'),
    Command('quit', 'Automixer', 'Quit Automixer', 'Lopeta Automixer', 'q'),
)


def command_id(sender):
    ident = sender.identifier() if hasattr(sender, 'identifier') else None
    if not ident and hasattr(sender, 'representedObject'):
        ident = sender.representedObject()
    return str(ident) if ident else None


def shortcut_text(language='en'):
    return '\n'.join(
        f'{c.title_fi if language == "fi" else c.title_en}: ⌘{c.key.upper()}'
        for c in COMMANDS if c.key
    )


def progress_percent(line):
    match = re.fullmatch(r'\s+[A-Za-z_ -]+ \((\d{1,3})%\)', line)
    if match and 0 <= int(match[1]) <= 100:
        # Chain completion is not publication; reserve the last 5% for encoding.
        return min(95, int(match[1]))
    return None


class Controller:
    """Owns referenced paths; native shell dispatches callbacks to the main thread.

    Folder scans and worker completion events share a lock. No disk or UI
    polling is started here; a platform filesystem adapter supplies changes.
    """

    def __init__(self, state_dir, *, queue_factory=FileQueue, on_event=lambda _e: None):
        self.files = []
        self.folder = None
        self.target_lufs = -16
        self.watching = False
        self.outputs = {}
        self._notify = on_event
        self._lock = threading.RLock()
        self._watch = FolderState(Path(state_dir) / 'folder-history.json')
        self._watched_pending = set()
        self._submitted = set()
        self.queue = queue_factory(on_event=self._event)

    def add_paths(self, paths):
        with self._lock:
            for raw in paths:
                path = Path(raw)
                if path.is_symlink():
                    continue
                path = path.resolve()
                if path.is_dir():
                    self.folder = path
                elif path.is_file() and path.suffix.lower() in MEDIA_SUFFIXES and path not in self.files:
                    self.files.append(path)

    def start(self, mode='files'):
        with self._lock:
            if mode == 'folder':
                if self.folder is None:
                    raise JobError('Choose a folder first')
                self.watching = True
                return
            for source in self.files:
                if source not in self._submitted:
                    self.queue.add(source, target_lufs=self.target_lufs)
                    self._submitted.add(source)

    def scan(self, *, now):
        with self._lock:
            if not self.watching or self.folder is None:
                return []
            ready = self._watch.scan(self.folder, now=now)
            for source in ready:
                self._watched_pending.add(str(source))
                try:
                    self.queue.add(source, target_lufs=self.target_lufs)
                except Exception:
                    self._watch.fail(source)
                    self._watched_pending.discard(str(source))
                    raise
            return self._watch.unsettled()

    def _event(self, event):
        with self._lock:
            source, state = event['source'], event['state']
            if state == 'done':
                self.outputs[source] = event['target']
            elif state in {'failed', 'cancelled'}:
                # Start retries unfinished files, never a successfully published one.
                self._submitted.discard(Path(source))
            if source in self._watched_pending and state in {'done', 'failed', 'cancelled'}:
                if state == 'done':
                    try:
                        self._watch.complete(source)
                    except WatchError as exc:
                        self._notify({'source': source, 'state': 'failed', 'error': str(exc)})
                        return
                else:
                    self._watch.fail(source)
                self._watched_pending.discard(source)
        self._notify(event)

    def cancel(self):
        with self._lock:
            self.watching = False
        self.queue.cancel()

    def close(self):
        self.watching = False
        self.queue.close()
