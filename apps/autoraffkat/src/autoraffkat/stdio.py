"""Lapsiprosessin putket pakatussa windowed-sovelluksessa.

Windows-paketti on ``console=False``: Python jättää ``sys.stdin``,
``sys.stdout`` ja ``sys.stderr`` arvoon ``None``, vaikka emo antoi lapselle
putket. Sisäinen lapsikomento (``--audio-worker``, ``--plugin-editor``) kytkee
ne takaisin ennen kuin lukee tehtävänsä.
"""

from __future__ import annotations

import os
import sys


def restore_stdio() -> None:
    """Kytke puuttuvat vakiovirrat takaisin tiedostokuvaajiin 0, 1 ja 2."""
    for name, fd, mode in (
        ("stdin", 0, "r"),
        ("stdout", 1, "w"),
        ("stderr", 2, "w"),
    ):
        if getattr(sys, name) is None:
            stream = os.fdopen(fd, mode, encoding="utf-8",
                               buffering=1 if mode == "w" else -1)
            setattr(sys, name, stream)
