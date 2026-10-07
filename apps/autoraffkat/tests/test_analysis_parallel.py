"""Verhokäyrät («lasketaan verhokäyrät») rinnakkain.

Jokainen tiedosto on oma yksisäikeinen ffmpeg-purkunsa. Monikamerajaksossa
tiedostoja on 6–10, ja ne laskettiin yksi kerrallaan yhdellä ytimellä
kymmenestä (M1 Max).
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import numpy as np

from autoraffkat import analysis


def test_envelopes_are_computed_in_parallel(monkeypatch):
    items = [SimpleNamespace(key=f"k{i}", name=f"n{i}", path=f"/x/{i}.wav", has_audio=True)
             for i in range(4)]
    timeline = SimpleNamespace(media=items)
    running, peak = 0, 0
    lock = threading.Lock()

    def slow(path, cache_dir=None):
        nonlocal running, peak
        with lock:
            running += 1
            peak = max(peak, running)
        time.sleep(0.3)
        with lock:
            running -= 1
        return np.zeros(10, dtype=np.float32)

    monkeypatch.setattr(analysis, "envelope_for", slow)
    calls = []
    started = time.perf_counter()
    result = analysis.analyze(timeline, progress=lambda i, n, name: calls.append((i, n)))
    elapsed = time.perf_counter() - started
    assert set(result.envelopes) == {"k0", "k1", "k2", "k3"}
    assert peak > 1 and elapsed < 0.9, (peak, elapsed)
    assert calls[-1] == (4, 4)
