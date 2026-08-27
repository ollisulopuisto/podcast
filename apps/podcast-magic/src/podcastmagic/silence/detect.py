"""Puhejaksojen paikannus aikajanalta.

Sanan aikaleima on **tiedoston** aikaa. Alue kertoo mistä kohtaa tiedostoa se
alkaa (``Offset``) ja mihin kohtaan aikajanaa se on sijoitettu (``Start``),
joten sanan paikka aikajanalla on ``Start + (s - Offset)``. Sama tiedosto voi
esiintyä aikajanalla useaan kertaan eri kohdissa; siksi muunnos tehdään
alueittain eikä tiedostoittain.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field

import numpy as np

from .. import audio as audio_io
from ..nhsx import Session, TrackInfo, locate
from ..nhsx.read import RegionInfo


@dataclass
class TrackResult:
    """Yhden raidan puhejaksot aikajanalla."""

    name: str
    intervals: list[tuple[float, float]] = field(default_factory=list)
    words_seen: int = 0
    words_quiet: int = 0
    # Monelta sanalta taso tosiasiassa mitattiin. Eri asia kuin «tarkistus
    # on päällä»: ilman ääntä levyllä tarkistus on päällä eikä mittaa mitään.
    words_levelled: int = 0
    missing_audio: list[str] = field(default_factory=list)


class AudioCache:
    """Puretut raidat muistissa. Kaksi kerrallaan.

    Tason tarkistus lukee samaa tiedostoa tuhansien sanojen kohdalta. Purku
    kerran on sekunteja, purku sanaa kohti olisi tunteja.

    Kattona kaksi tiedostoa: ajo etenee raita kerrallaan ja raita on yleensä
    yksi tiedosto, joten enempää ei tarvita — ja tunnin jakso on int16:na
    115 MB, joten neljä raitaa muistissa yhtä aikaa on puoli gigatavua
    turhaan.
    """

    MAXSIZE = 2

    def __init__(self) -> None:
        self._data: "OrderedDict[str, np.ndarray | None]" = OrderedDict()

    def get(self, path: str) -> np.ndarray | None:
        if path in self._data:
            self._data.move_to_end(path)
            return self._data[path]
        try:
            samples = audio_io.decode_pcm(path)
        except Exception:  # noqa: BLE001 — puuttuva tai rikki ääni ei kaada ajoa
            samples = None
        self._data[path] = samples
        while len(self._data) > self.MAXSIZE:
            self._data.popitem(last=False)
        return samples


def region_words(session: Session, region: RegionInfo):
    """Alueeseen osuvat sanat aikajanalle muunnettuina.

    Sanan loppu leikataan alueen loppuun. Alueen ulkopuolelle jäävä osa ei ole
    olemassa aikajanalla, eikä sen perusteella pidä pidentää kuuluvaa jaksoa.
    """
    file_info = session.file_by_id(region.ref)
    if file_info is None:
        return
    for word in file_info.words():
        if word.start < region.offset or word.start >= region.offset + region.length:
            continue
        start = region.start + (word.start - region.offset)
        end = min(region.end, start + word.length)
        if end <= start:
            continue
        yield word, file_info, start, end


def speech_intervals(
    session: Session,
    track: TrackInfo,
    settings,
    cache: AudioCache | None = None,
    extra_dir: str = "",
) -> TrackResult:
    """Yhden raidan puhejaksot aikajanalla."""
    result = TrackResult(name=track.name)
    cache = cache or AudioCache()
    missing: set[str] = set()

    for region in track.regions:
        for word, file_info, start, end in region_words(session, region):
            result.words_seen += 1

            if settings.rms:
                path = locate(session, file_info, extra_dir)
                if not path:
                    missing.add(file_info.name)
                    # Ilman ääntä tasoa ei voi mitata. Sana päästetään läpi:
                    # liikaa vaimennettu haastattelu on pahempi virhe kuin
                    # liian vähän vaimennettu.
                else:
                    samples = cache.get(path)
                    if samples is None:
                        missing.add(file_info.name)
                    else:
                        result.words_levelled += 1
                        level = audio_io.dbfs(samples, word.start, word.end)
                        if level < settings.threshold:
                            result.words_quiet += 1
                            continue

            result.intervals.append((start, end))

    result.intervals.sort()
    result.missing_audio = sorted(missing)
    return result
