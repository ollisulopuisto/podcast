"""One local transcription model at a time per user, including detached workers.

This is a concurrency guard, not a memory fit or kernel-panic safety guarantee.
The OS releases the advisory lock if a process exits or is killed. Never unlink
its file: another process could still hold the old inode while a new one locks a
replacement. Cloud transcription does not use this lock.
"""

from __future__ import annotations

import contextlib
from pathlib import Path


@contextlib.contextmanager
def local_inference_slot():
    # Local MLX is macOS-only; keep its POSIX dependency lazy so cloud imports
    # and availability diagnostics continue to work on other platforms.
    import fcntl

    folder = Path.home() / "Library" / "Caches" / "colab-transcribe"
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (folder / "local-inference.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError(
                "Another local transcription is already running. Cancel it or wait "
                "for it to finish before starting another."
            ) from error
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
