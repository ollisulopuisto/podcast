"""Moottorien yhteinen rajapinta."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ...jobs import Progress
from ...nhsx import Word
from ..options import Options


@dataclass(frozen=True)
class BackendInfo:
    key: str
    label: str
    available: bool
    reason: str = ""
    device: str = ""
    install: str = ""


@dataclass
class TranscriptResult:
    """Litteroinnin tulos: sanat aikoineen ja alkuperäinen Whisper-rakenne.

    ``raw`` talletetaan levylle sellaisenaan. Se on sama muoto jonka
    Colab-muistikirja tuotti, joten vanhat JSONit kelpaavat tähän ja tämän
    tuottamat sinne — ja kun litterointi näyttää oudolta, sen voi lukea.
    """

    words: list[Word] = field(default_factory=list)
    text: str = ""
    language: str = ""
    raw: dict = field(default_factory=dict)


def words_from_segments(segments: list[dict]) -> list[Word]:
    """Whisper-segmenteistä sanalistaksi.

    Sanan ``end`` voi olla ``start`` tai sitä pienempi kun malli on
    epävarma. Nollapituinen sana katoaisi vaimennuksessa kokonaan — se on
    kuitenkin puhuttu — joten pituudelle annetaan lattia.
    """
    out: list[Word] = []
    for segment in segments:
        for word in segment.get("words") or ():
            text = str(word.get("word", "")).strip()
            if not text:
                continue
            start = float(word.get("start", 0.0))
            end = float(word.get("end", start))
            out.append(Word(text=text, start=start, length=max(0.02, end - start)))
    return out


class Backend:
    """Moottorin rajapinta. Toteutukset perivät tämän."""

    key = ""
    label = ""

    def info(self) -> BackendInfo:  # pragma: no cover - toteutetaan alaluokassa
        raise NotImplementedError

    def transcribe(
        self,
        samples: np.ndarray,
        options: Options,
        progress: Progress,
    ) -> TranscriptResult:  # pragma: no cover - toteutetaan alaluokassa
        raise NotImplementedError
