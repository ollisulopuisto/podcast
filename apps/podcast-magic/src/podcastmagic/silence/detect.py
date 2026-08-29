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

from speechmix import grid
from speechmix.dsp import FLOOR_DB

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
    # Sanat jotka kuuluivat, mutta kuuluivat kovempaa toisella raidalla.
    # Eri asia kuin ``words_quiet``: vuoto ei ole hiljaista, se on
    # hiljaisempaa kuin sama puhe omalla mikillä.
    words_bled: int = 0
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
        # Puuttuva tai rikki ääni ei kaada ajoa: muut raidat käsitellään silti.
        except Exception:
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


def _region_at(regions, programme_time: float):
    """Alue joka on tällä raidalla kyseisellä hetkellä, tai ``None``."""
    for region in regions:
        if region.start <= programme_time < region.end:
            return region
    return None


def probe_windows(session: Session) -> list[tuple[float, float, str]]:
    """Kaikkien raitojen sanat ohjelma-aikajanalla, yhtenä listana.

    Järjestys on sama kuin ``speech_intervals``in kulku — raita, alue, sana —
    jotta raidan oma osuus tästä listasta vastaa alkio alkiolta sitä
    järjestystä jossa sen sanat käsitellään.
    """
    out: list[tuple[float, float, str]] = []
    for track in session.tracks:
        for region in track.regions:
            for _word, _info, start, end in region_words(session, region):
                out.append((start, end, track.name))
    return out


def noise_floor_of(samples: np.ndarray) -> float:
    """Raidan oma pohjakohina desibeleinä.

    Sääntö on kirjastosta — ``grid.smooth`` tasoittaa tavukohtaisen värinän ja
    ``grid.noise_floor`` lukee 20. persentiilin — mutta tasot mitataan tällä
    puolella. Syy on muisti: ``grid.speech_grid`` ottaa kaikki raidat yhtä
    aikaa liukulukuina, ja tämän sovelluksen istunto on viisi raitaa kertaa
    75 minuuttia, eli int16:na 575 MB ja liukulukuina yli kaksi kertaa se.
    Katto on kaksi tiedostoa, ja käyrä on raidasta megatavun luokkaa.

    Sama ``audio.dbfs`` mittaa tässä ja sanan kohdalla: pohjan ja sanan pitää
    olla samalla asteikolla, tai marginaali niiden välillä ei tarkoita mitään.

    Digitaalinen hiljaisuus on ``-inf`` ja se on mittaustulos, ei puuttuva
    mittaus — mutta persentiili ``-inf``:istä on ``-inf``, ja silloin mikä
    tahansa marginaali sen yli päästäisi kaiken läpi. Siksi lattia on
    kirjaston ``FLOOR_DB``.
    """
    total = audio_io.duration(samples)
    if total <= grid.FRAME_SEC:
        return FLOOR_DB
    starts = np.arange(0.0, total - grid.FRAME_SEC, grid.HOP_SEC)
    curve = np.array(
        [audio_io.dbfs(samples, t, t + grid.FRAME_SEC) for t in starts],
        dtype=np.float32,
    )
    curve = np.maximum(curve, FLOOR_DB)
    return float(grid.noise_floor(grid.smooth(curve, hop_sec=grid.HOP_SEC)))


def dominant_words(
    session: Session,
    settings,
    cache: AudioCache | None = None,
    extra_dir: str = "",
) -> dict:
    """Raita -> onko sen jokainen sana omaa puhetta vai vuotoa.

    **Tämä on kopio, ei tuonti.** Sama päätös samalla vakiolla on jo
    ``speechmix.grid.speech_grid``issa (``DOMINANCE_DB = 6.0``,
    ``levels >= loudest - dominance_db``), ja tämä sovellus ei käytä
    ``speechmix``iä lainkaan — ei tuontia, ei riippuvuutta. Kopio tehtiin
    sanan tarkkuuden vuoksi: vaimennus tarvitsee tiedon siitä mikä alue jää
    auki, ei liu'utettavaa vahvistuskäyrää. Se ei tee siitä vähemmän kopiota,
    ja ``speech_grid`` osaa lisäksi sen mitä tämä ei: aktiivisuus mitataan
    raidan omasta pohjakohinasta eikä absoluuttisesta kynnyksestä.

    Kun ääniketju tuodaan, tämä korvataan sillä. Ks. CLAUDE.md, «Tämä sovellus
    ei käytä speechmixiä lainkaan» — siinä on taulukko siitä mikä korvaa minkä.

    Jokaisen raidan taso mitataan **jokaisen** sanan kohdalta, myös toisten
    raitojen sanojen, koska vertailu on se mikä ratkaisee. Ohjelma-aika
    käännetään kunkin raidan omaksi tiedostoajaksi sen omalla alueella —
    sama kaava kuin muualla, ``offset + (t - start)``.

    Muisti pysyy ennallaan: raidat mitataan yksi kerrallaan ja ikkunat ovat
    sekunnin murto-osia, joten levyltä on auki edelleen enintään kaksi
    tiedostoa. Mittauksia tulee raitojen verran enemmän kuin ennen, mutta
    yksi mittaus on muutama tuhat näytettä.

    Tyhjä tulos tarkoittaa «sääntöä ei sovelleta»: yksi raita, ei sanoja,
    tai ``dominance`` nollassa. Yhdellä mikillä ei ole mihin verrata.
    """
    if settings.dominance <= 0 or len(session.tracks) < 2:
        return {}
    windows = probe_windows(session)
    if not windows:
        return {}

    cache = cache or AudioCache()
    levels = np.full((len(session.tracks), len(windows)), -np.inf)
    # Mitattiinko taso lainkaan. Eri asia kuin taso itse: digitaalinen
    # hiljaisuus on -inf ja on mittaustulos, puuttuva tiedosto on -inf eikä
    # ole. Yhteen laskettuna raita jonka tiedosto ei aukea häviäisi joka
    # vertailun ja vaikenisi kokonaan.
    measured = np.zeros(levels.shape, dtype=bool)
    for row, track in enumerate(session.tracks):
        regions = sorted(track.regions, key=lambda r: r.start)
        for column, (start, end, _name) in enumerate(windows):
            region = _region_at(regions, start)
            if region is None:
                continue
            file_info = session.file_by_id(region.ref)
            if file_info is None:
                continue
            path = locate(session, file_info, extra_dir)
            if not path:
                continue
            samples = cache.get(path)
            if samples is None:
                continue
            file_start = region.offset + (start - region.start)
            levels[row, column] = audio_io.dbfs(
                samples, file_start, file_start + (end - start)
            )
            measured[row, column] = True

    # Vain mitatut kilpailevat kovimman paikasta, ja mittaamatta jäänyt sana
    # jää: tiedon puute ei ole päätös vaientaa. Sama sääntö kuin
    # ``speech_intervals``issa puuttuvalle tiedostolle — liikaa vaimennettu
    # jakso on pahempi virhe kuin liian vähän vaimennettu, koska
    # jälkimmäisen kuulee kerran ja edellisestä puuttuu puhetta.
    loudest = np.where(measured, levels, -np.inf).max(axis=0)
    keep = ~measured | (levels >= loudest - settings.dominance)

    out = {}
    for row, track in enumerate(session.tracks):
        mine = [i for i, (_s, _e, name) in enumerate(windows) if name == track.name]
        out[track.name] = keep[row, mine]
    return out


def speech_intervals(
    session: Session,
    track: TrackInfo,
    settings,
    cache: AudioCache | None = None,
    extra_dir: str = "",
    dominance=None,
) -> TrackResult:
    """Yhden raidan puhejaksot aikajanalla.

    ``dominance`` on ``dominant_words``in tälle raidalle antama lista: tosi
    siellä missä sana on omaa puhetta. Ilman sitä käyttäydytään kuten ennen.
    """
    result = TrackResult(name=track.name)
    cache = cache or AudioCache()
    missing: set[str] = set()
    floors: dict[str, float] = {}

    for region in track.regions:
        for word, file_info, start, end in region_words(session, region):
            index = result.words_seen
            result.words_seen += 1

            # Vuototarkistus ennen kynnystä: se on tarkempi vastaus samaan
            # kysymykseen, ja lukema kertoo kumpi sanan pudotti.
            if dominance is not None and index < len(dominance) and not dominance[index]:
                result.words_bled += 1
                continue

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
                        # Pohja kerran per tiedosto: se ei riipu sanasta, ja
                        # koko raidan käyrän laskeminen tuhannesti olisi
                        # tunteja siinä missä kerran on sekunti.
                        if path not in floors:
                            floors[path] = noise_floor_of(samples)
                        level = audio_io.dbfs(samples, word.start, word.end)
                        if level < floors[path] + settings.sensitivity:
                            result.words_quiet += 1
                            continue

            result.intervals.append((start, end))

    result.intervals.sort()
    result.missing_audio = sorted(missing)
    return result
