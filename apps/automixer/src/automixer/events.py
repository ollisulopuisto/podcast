"""Live events for a host (kuulas): ``--events``.

With the flag, every event is one extra line on stdout next to the text lines:
``@@kuulas `` and one JSON object on the same line, flushed at once. stdout is
used because it reaches a host the same way locally and over ssh; the text
lines are unchanged. Spec: kuulas ``docs/PODCAST-MAGIC.md``, "Live events".

Every object has ``schema`` and ``event``; fields may be added, never renamed.
"""

from __future__ import annotations

import json
import math
import threading

PREFIX = "@@kuulas "
SCHEMA = 1

_lock = threading.Lock()
_enabled = False


def enable(on: bool = True) -> None:
    global _enabled
    _enabled = bool(on)


def _clean(value):
    """JSON has no inf or nan: they become null (a limit of 'none' is inf)."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    return value


def emit(event: str, **fields) -> None:
    if not _enabled:
        return
    line = PREFIX + json.dumps(
        {"schema": SCHEMA, "event": event, **_clean(fields)}, ensure_ascii=False
    )
    # One write under a lock: the tracks run on threads, and two lines must
    # never run into each other.
    with _lock:
        print(line, flush=True)


class StageTrail:
    """``stage`` events for one track from the library's 'stage reached' calls.

    The chain only says when a stage is *done*. The stages and their order are
    fixed, so finishing one is also the moment the next one starts, which is
    what a host wants to show ("now working on ..."). ``skipped`` stages are
    said once and the next one starts.
    """

    def __init__(self, track: str, order: list[str], skipped: set[str] | None = None):
        self.track = track
        self.order = list(order)
        self.skipped = set(skipped or ())
        self._next = 0

    def _announce(self) -> None:
        """Start the next stage, saying in passing which ones are skipped."""
        while self._next < len(self.order) and self.order[self._next] in self.skipped:
            emit("stage", track=self.track, stage=self.order[self._next], state="skipped")
            self._next += 1
        if self._next < len(self.order):
            emit("stage", track=self.track, stage=self.order[self._next], state="start")

    def begin(self) -> None:
        self._next = 0
        self._announce()

    def reached(self, stage: str) -> None:
        if stage in self.skipped:
            return  # already said; the library still reports it
        emit("stage", track=self.track, stage=stage, state="done")
        self._next = self.order.index(stage) + 1
        self._announce()
