"""Sanatiedostosta kappaleteksti (``--txt``).

Sama jako kuin Colabin ``pipeline.paragraphs``-funktiossa ja podcast-magicin
``nhsx/write.py``:ssä: tauko vähintään ``PARAGRAPH_GAP`` sekuntia tai
``PARAGRAPH_MAX_WORDS`` sanaa aloittaa uuden kappaleen. Moduuli ei tuo
``colab.pipeline``a, koska se kuuluu Colabin puolelle.
"""

from __future__ import annotations

from itertools import pairwise
from typing import Any

PARAGRAPH_GAP = 1.2  # s
PARAGRAPH_MAX_WORDS = 80


def _stamp(seconds: float) -> str:
    total = int(seconds)
    return f"[{total // 60:02d}:{total % 60:02d}]"


def _words(doc: Any) -> list[tuple[str, float, float]]:
    """Kelvolliset sanat ``(teksti, alku, loppu)``; virheelliset rivit ohitetaan."""
    rows = doc.get("words") if isinstance(doc, dict) else None
    out: list[tuple[str, float, float]] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        text = row.get("w")
        try:
            start, end = float(row["s"]), float(row["e"])
        except (KeyError, TypeError, ValueError):
            continue
        if isinstance(text, str) and text.strip():
            out.append((text.strip(), start, end))
    return out


def paragraph_text(doc: Any) -> str:
    """``[MM:SS] teksti`` per kappale, tyhjällä rivillä erotettuna; tyhjä jos ei sanoja."""
    words = _words(doc)
    if not words:
        return ""
    groups = [[words[0]]]
    for before, word in pairwise(words):
        if word[1] - before[2] >= PARAGRAPH_GAP or len(groups[-1]) >= PARAGRAPH_MAX_WORDS:
            groups.append([word])
        else:
            groups[-1].append(word)
    lines = [f"{_stamp(g[0][1])} " + " ".join(w[0] for w in g) for g in groups]
    return "\n\n".join(lines) + "\n"
