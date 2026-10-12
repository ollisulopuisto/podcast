"""Kynnys opitaan käsin vaimennetuista alueista: istunto kirjaston syötteeksi.

Laskenta asuu ``silencelearn``-paketissa (``packages/silencelearn``), ja syy on
tämän sovelluksen toisessa puolessa: colab-transcriben Colab-skripti ei voi
tuoda työtilaa, joten sama laskenta oli kopiona siellä ja pidettiin
yhdenmukaisena vain vertailutestillä. Nyt kirjasto on yksi tiedosto jonka
ajuri lataa Colabiin sellaisenaan, ja kopiota ei ole.

Täällä on vain se mikä on tämän sovelluksen: istunnon alueet raidoiksi
(``is_muted``) ja ``Source``, joka vastaa sanoihin ja tasoihin ``nhsx``:n
tiedostotiedoilla ja ``AudioCache``lla. Luvut, algoritmi ja niiden perustelut
ovat kirjastossa.
"""

from __future__ import annotations

from silencelearn import (
    BLEED_GAP_PERCENTILE,
    GAP_MARGIN_DB,
    GUARD_DB,
    HOP,
    KEEP_MARGIN_DB,
    MARGIN_DB,
    MIN_BLEED_FRAMES,
    MIN_SECONDS,
    MIN_SPEECH_WORDS,
    PERCENTILE,
    SPEECH_GAP_PERCENTILE,
    SPEECH_WORDS,
    WINDOW,
    Calibration,
    Region,
    Track,
)
from silencelearn import calibrate as _calibrate
from silencelearn import horizon as _horizon

from .. import audio as audio_io
from ..nhsx import Session, locate
from .detect import AudioCache, is_muted

__all__ = [
    "BLEED_GAP_PERCENTILE", "GAP_MARGIN_DB", "GUARD_DB", "HOP", "KEEP_MARGIN_DB",
    "MARGIN_DB", "MIN_BLEED_FRAMES", "MIN_SECONDS", "MIN_SPEECH_WORDS",
    "PERCENTILE", "SPEECH_GAP_PERCENTILE", "SPEECH_WORDS", "WINDOW",
    "Calibration", "calibrate", "horizon",
]


def _tracks(session: Session) -> list[Track]:
    return [
        Track(t.name, [Region(r.ref, r.start, r.length, r.offset, is_muted(r))
                       for r in t.regions])
        for t in session.tracks
    ]


def horizon(session: Session) -> float:
    """Muokattu aika: viimeisen vaimennetun alueen loppu ohjelma-aikajanalla."""
    return _horizon(_tracks(session))


class _Source:
    """Sanat ja tasot istunnon tiedostoista."""

    def __init__(self, session: Session, cache: AudioCache, extra_dir: str):
        self.session = session
        self.cache = cache
        self.extra_dir = extra_dir
        self._paths: dict[str, str] = {}
        self._missing: set[str] = set()

    def words(self, ref: str) -> list[tuple[float, float]]:
        info = self.session.file_by_id(ref)
        return [] if info is None else [(w.start, w.length) for w in info.words()]

    def level(self, ref: str, start: float, end: float) -> float | None:
        info = self.session.file_by_id(ref)
        if info is None:
            return None
        if ref not in self._paths:
            self._paths[ref] = locate(self.session, info, self.extra_dir)
        path = self._paths[ref]
        samples = self.cache.get(path) if path else None
        if samples is None:
            self._missing.add(info.name)
            return None
        return audio_io.dbfs(samples, start, end)

    def missing(self) -> bool:
        return bool(self._missing)


def calibrate(session: Session, cache: AudioCache | None = None,
              extra_dir: str = "") -> dict[str, Calibration]:
    """Raita -> opittu kynnys ja ero-raja. Raidalla jolla ei ole opittavaa on syy.

    Kaikki tiedostot pidetään muistissa laskennan ajan (``AudioCache.unbounded``):
    jokaisen ikkunan kohdalla verrataan myös muita raitoja, ja kahden tiedoston
    katolla kolmen raidan kierto purkaisi joka haun uudestaan.
    """
    cache = cache or AudioCache()
    with cache.unbounded():
        return _calibrate(_tracks(session), _Source(session, cache, extra_dir))
