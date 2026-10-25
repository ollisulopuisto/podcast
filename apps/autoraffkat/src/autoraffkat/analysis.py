"""Kerrosten liitos: verhokäyristä ruudukoksi.

Hidas osa (ffmpeg + RMS) on ``speechmix.rms``. Tämä moduuli kohdistaa valmiit
verhokäyrät aikajanan ruudukolle ja soveltaa raitakohtaiset säätimet. Kohdistus
on pelkkää numpy-indeksointia, joten se kestää roolimuutoksenkin ilman uutta
purkua.
"""

from __future__ import annotations

import dataclasses
import os
from dataclasses import dataclass, field
from fractions import Fraction

import numpy as np

from speechmix import grid as grid_lib
from speechmix.errors import EnvelopeError
from speechmix.rms import FLOOR_DB, envelope_for

from .audio import cache_dir
from .decide import Grid, GroupShot, ShotLanes, SpeakerLanes
from .fcpxml.read import Timeline
from .i18n import t
from .model import (
    HOP,
    ROLE_CLOSE,
    ROLE_GROUP,
    ROLE_MIC,
    ROLE_SHOT,
    ROLE_WIDE,
    MediaItem,
    TrackConfig,
)
from .video import speech as visual_speech

# Tasoitus, pohjan persentiili ja kynnys ovat kirjastossa: automixer kysyy
# saman kysymyksen samasta aineistosta, ja kaksi vastausta siihen on juuri se
# ajautuminen jota vastaan `packages/speechmix` on. Nämä nimet jäävät, koska
# tämä moduuli on niiden mitattu koti — arvot tulevat sieltä.
SMOOTH_SECONDS = grid_lib.SMOOTH_SECONDS
NOISE_PERCENTILE = grid_lib.NOISE_PERCENTILE


class AnalysisError(Exception):
    """Aineisto ei riitä päätökseen."""


def _smooth(db: np.ndarray, seconds: float) -> np.ndarray:
    """Liukuva keskiarvo. Tasoittaa tavuvälit, joita ei haluta leikkauksiksi.

    Kirjastossa, koska automixer tasoittaa saman käyrän — ja koska tässä oli
    vika jota kumpikaan ei nähnyt: ``np.convolve(..., "same")`` täyttää reunat
    nollalla, ja nolla on desibeleissä **täysi asteikko**. Ohjelman ensimmäiset
    ja viimeiset 40 ms lukivat 96 dB liian kovaa, eli mikki näytti olevan
    äänessä siellä. Ks. ``grid.smooth``.
    """
    return grid_lib.smooth(db, seconds, hop_sec=HOP)


def align(
    item: MediaItem, envelope: np.ndarray, program_start: Fraction, n: int
) -> tuple[np.ndarray, np.ndarray]:
    """Verhokäyrä aikajanan ruudukolle. Palauttaa (dB, onko mediaa)."""
    out = np.full(n, FLOOR_DB, dtype=np.float32)
    valid = np.zeros(n, dtype=bool)
    if n <= 0 or envelope.size == 0:
        return out, valid
    start_f = float(program_start)
    program_end = program_start + Fraction(n) * Fraction(HOP).limit_denominator(1000)

    for p in item.placements:
        lo = max(p.offset, program_start)
        hi = min(p.end, program_end)
        if hi <= lo:
            continue
        i0 = max(0, int(np.ceil((float(lo) - start_f) / HOP)))
        i1 = min(n, int(np.floor((float(hi) - start_f) / HOP)))
        if i1 <= i0:
            continue
        idx = np.arange(i0, i1)
        # tiedostoaika = klipin start - assetin start + (aikajana - klipin offset)
        base = float(p.start - item.asset_start - p.offset)
        file_t = base + start_f + idx * HOP
        e = np.rint(file_t / HOP).astype(np.int64)
        ok = (e >= 0) & (e < envelope.size)
        out[idx[ok]] = envelope[e[ok]]
        valid[idx[ok]] = True
    return out, valid


def availability(
    items: MediaItem | list[MediaItem], program_start: Fraction, n: int
) -> np.ndarray:
    """Missä ruudukon kohdissa raidalla on kuvaa.

    Raita voi koostua useasta assetista — monikamerassa sama kulma on oma
    tiedostonsa joka osassa — joten peitto on niiden yhdiste.
    """
    if isinstance(items, MediaItem):
        items = [items]
    mask = np.zeros(n, dtype=bool)
    start_f = float(program_start)
    for item in items:
        for p in item.placements:
            i0 = max(0, int(np.ceil((float(p.offset) - start_f) / HOP)))
            i1 = min(n, int(np.floor((float(p.end) - start_f) / HOP)))
            if i1 > i0:
                mask[i0:i1] = True
    return mask


@dataclass
class Analysis:
    """Kerran laskettu hidas osa: verhokäyrä per media."""

    timeline: Timeline
    envelopes: dict[str, np.ndarray] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    _aligned: dict[tuple, tuple[np.ndarray, np.ndarray, float]] = field(
        default_factory=dict
    )

    def media_by_key(self) -> dict[str, MediaItem]:
        """Mediat avaimella haettavina."""
        return {m.key: m for m in self.timeline.media}

    def aligned(self, item: MediaItem, program_start: Fraction, n: int):
        """Kohdistettu käyrä välimuistista: ``(dB, onko mediaa, pohjakohina)``.

        Välimuisti on avainnettu ohjelman rajoilla, koska roolin vaihto siirtää
        niitä. Pohjakohina lasketaan tässä eikä säätimien yhteydessä, koska se
        ei riipu säätimistä.
        """
        cache_key = (item.key, program_start, n)
        hit = self._aligned.get(cache_key)
        if hit is None:
            env = self.envelopes.get(item.key)
            if env is None:
                hit = (
                    np.full(n, FLOOR_DB, dtype=np.float32),
                    np.zeros(n, dtype=bool),
                    FLOOR_DB,
                )
            else:
                db, valid = align(item, env, program_start, n)
                db = _smooth(db, SMOOTH_SECONDS)
                # Pohjakohina riippuu vain verhokäyrästä, ei säätimistä, joten
                # se lasketaan kerran tähän välimuistiin.
                floor = grid_lib.noise_floor(db, valid, NOISE_PERCENTILE)
                hit = (db, valid, floor)
            self._aligned[cache_key] = hit
        return hit


#: Rinnakkaiset verhokäyrät. Jokainen on oma ffmpeg-prosessinsa, joka purkaa
#: yhdellä ytimellä; monikamerajaksossa tiedostoja on 6–10. Puolet ytimistä,
#: jotta kone ja levy jaksavat vielä käyttöliittymän ja muun työn.
ENVELOPE_WORKERS = max(2, (os.cpu_count() or 4) // 2)


def analyze(
    timeline: Timeline, progress=None, keys: list[str] | None = None
) -> Analysis:
    """Laskee tai lukee välimuistista verhokäyrät. Hidas — ajetaan kerran.

    Tiedostot rinnakkain: kukin on yksisäikeinen ffmpeg-purku, ja yksi
    kerrallaan laskettuna kymmenestä ytimestä käytettiin yhtä.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    analysis = Analysis(timeline=timeline)
    targets = [
        m for m in timeline.media if m.has_audio and (keys is None or m.key in keys)
    ]
    if progress is not None and targets:
        progress(0, len(targets), targets[0].name)
    done = 0
    with ThreadPoolExecutor(max_workers=min(ENVELOPE_WORKERS, max(1, len(targets)))) as pool:
        futures = {
            pool.submit(envelope_for, item.path, cache_dir=cache_dir()): item
            for item in targets
        }
        for future in as_completed(futures):
            item = futures[future]
            try:
                analysis.envelopes[item.key] = future.result()
            except EnvelopeError as exc:
                analysis.errors[item.key] = str(exc)
            done += 1
            if progress is not None and done < len(targets):
                progress(done, len(targets), item.name)
    if progress is not None:
        progress(len(targets), len(targets), "")
    return analysis


# ------------------------------------------------------------------ ruudukko


@dataclass
class ShotConfig:
    """Kuva ja siinä näkyvät puhujat raitajärjestyksessä."""

    key: str
    covers: list[str]
    context: bool = False


@dataclass
class Roles:
    """Roolituksesta johdettu rakenne.

    Avaimet ovat raita-avaimia (``Timeline.tracks``), eivät media-avaimia:
    monikamerassa yksi raita kokoaa saman kulman kaikista osista.
    """

    wide_key: str = ""
    speakers: list[str] = field(default_factory=list)
    mics: dict[str, list[str]] = field(default_factory=dict)  # puhuja -> mikit
    closes: dict[str, str] = field(default_factory=dict)  # puhuja -> lähikuva
    # ryhmäkuva -> puhujat, järjestyksessä jossa ne valittiin
    groups: dict[str, list[str]] = field(default_factory=dict)
    # Puhuja jolla on lähikuva mutta ei mikkiä: puhe luetaan kuvasta
    # (``video/speech.py``), jos se on sallittu.
    visual_speakers: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    shots: list[ShotConfig] = field(default_factory=list)


def resolve_roles(
    timeline: Timeline, tracks: dict[str, TrackConfig], visual: bool = True
) -> Roles:
    """Kääntää raitakohtaiset roolit puhujiksi ja kerää puutteet.

    Puutteet palautetaan listana eikä nosteta poikkeuksena: käyttöliittymässä
    ollaan jatkuvasti puolivalmiissa tilassa, ja puute on näytettävä ilman että
    edellinen tulos katoaa.
    """
    roles = Roles()
    pending = []
    legacy_groups = set()
    for track in timeline.tracks:
        cfg = tracks.get(track.key)
        if cfg is None:
            continue
        name = cfg.speaker.strip()
        if cfg.role == ROLE_MIC:
            if not name:
                roles.problems.append(t("roles.mic_without_speaker", name=track.name))
                continue
            if name not in roles.speakers:
                roles.speakers.append(name)
            roles.mics.setdefault(name, []).append(track.key)
            continue
        if cfg.role not in (ROLE_SHOT, ROLE_CLOSE, ROLE_GROUP, ROLE_WIDE):
            continue
        names = ([name] if name else []) if cfg.role == ROLE_CLOSE else list(
            dict.fromkeys(n.strip() for n in cfg.covers if n.strip()))
        if not names and cfg.role != ROLE_WIDE and not cfg.context:
            key = "roles.close_without_speaker" if cfg.role == ROLE_CLOSE else "roles.group_without_speakers"
            roles.problems.append(t(key, name=track.name))
            continue
        if cfg.role == ROLE_GROUP:
            legacy_groups.add(track.key)
        if cfg.role in (ROLE_CLOSE, ROLE_SHOT):
            for person in names:
                if person not in roles.speakers:
                    roles.speakers.append(person)
        pending.append((track.key, cfg, names))

    for key, cfg, names in pending:
        if cfg.role == ROLE_WIDE:
            names = list(roles.speakers)
        roles.shots.append(ShotConfig(key, names, cfg.context or cfg.role == ROLE_WIDE))
    roles.wide_key = next((shot.key for shot in roles.shots if shot.context), "")
    if not roles.wide_key and len(roles.speakers) >= 2:
        roles.wide_key = next((shot.key for shot in roles.shots
                               if set(roles.speakers) <= set(shot.covers)), "")
    track_names = {track.key: track.name for track in timeline.tracks}
    for shot in roles.shots:
        if len(shot.covers) == 1:
            roles.closes.setdefault(shot.covers[0], shot.key)
        elif shot.key != roles.wide_key:
            roles.groups[shot.key] = list(shot.covers)
        if shot.key in legacy_groups:
            for name in shot.covers:
                if name not in roles.mics:
                    roles.problems.append(t("roles.group_unknown_speaker",
                                            name=track_names[shot.key], speaker=name))

    for name in roles.speakers:
        if name not in roles.mics:
            if visual and name in roles.closes:
                roles.visual_speakers.append(name)
            else:
                roles.problems.append(t("roles.speaker_without_mic", name=name))
    if not roles.mics and not roles.visual_speakers:
        roles.problems.append(t("roles.no_mic"))
    # Ilman yhtäkään lähikuvaa päätös on kelvollinen mutta hyödytön: koko
    # ohjelma olisi yhtä laajaa kuvaa (tai ilman kuvaa lainkaan). Se on roolituksen puute eikä tulos,
    # joten se sanotaan ääneen eikä viedä XML:ksi.
    only_legacy_wide = bool(roles.shots) and all(
        tracks[shot.key].role == ROLE_WIDE for shot in roles.shots)
    if (roles.mics or roles.visual_speakers) and (not roles.shots or only_legacy_wide):
        roles.problems.append(t("roles.no_closeups"))
    return roles


def program_range(timeline: Timeline, roles: Roles) -> tuple[Fraction, Fraction]:
    """Ohjelman rajat: laaja kuva ja mikit rajaavat, lähikuvat eivät.

    Raidan väli on ensimmäisestä osasta viimeiseen. Kahdessa osassa kuvattu
    mikki alkaa siis osan A alusta eikä osan B alusta, vaikka jälkimmäinen
    onkin oma assettinsa.

    Mikit rajaavat yhdessä, eivät kukin erikseen: ohjelma on siellä missä
    *jokin* mikki on. Mikki joka puuttuu yhdestä osasta tarkoittaa että
    puhuja on siellä hiljaa. Jokaisen mikin leikkaus katkaisi ohjelman
    ensimmäisen osan loppuun, ja toinen osa putosi viennistä sanomatta.
    """
    spans = [timeline.track_span(roles.wide_key)] if roles.wide_key else []
    # Kuvasta puhuvan «mikki» on hänen lähikuvansa.
    mic_keys = [k for keys in roles.mics.values() for k in keys]
    mic_keys += [roles.closes[name] for name in roles.visual_speakers]
    mics = [timeline.track_span(k) for k in mic_keys]
    mics = [s for s in mics if s is not None]
    if mics:
        spans.append((min(s[0] for s in mics), max(s[1] for s in mics)))
    spans = [s for s in spans if s is not None]
    if not spans:
        return timeline.start, timeline.end
    return max(s[0] for s in spans), min(s[1] for s in spans)


def _source_edits(
    timeline: Timeline, program_start: Fraction, program_end: Fraction
) -> tuple[float, ...]:
    """Lähde-XML:n omat leikkaukset: ``<mc-clip>``-osien saumat joissa lähde hyppää.

    Käyttäjä on leikannut materiaalia (poistanut kohdan) ja jatkuvuus katkeaa
    tässä: kuva ei saa jatkua samalla kameralla hypyn yli. Sauma jossa osa
    jatkaa edellistä (lähdeaika täsmää puolentoista ruudun tarkkuudella) ei
    ole hyppy eikä leikkaus.
    """
    slack = Fraction(3, 2) * timeline.frame_duration
    found = []
    for prev, nxt in zip(timeline.multicams, timeline.multicams[1:], strict=False):
        if abs(nxt.start - prev.source_at(nxt.offset)) <= slack:
            continue
        if program_start < nxt.offset < program_end:
            found.append(float(nxt.offset - program_start))
    return tuple(sorted(found))


def build_grid(
    analysis: Analysis, tracks: dict[str, TrackConfig], roles: Roles | None = None
) -> tuple[Grid, Fraction, Fraction]:
    """Ruudukko päätöskerrokselle. Ajetaan joka säädöllä — pysyttävä millisekunneissa."""
    timeline = analysis.timeline
    roles = roles or resolve_roles(timeline, tracks)
    program_start, program_end = program_range(timeline, roles)
    span = float(program_end - program_start)
    if span <= 1.0:
        raise AnalysisError(t("analysis.no_overlap"))
    n = int(span / HOP)

    lanes: list[SpeakerLanes] = []
    for name in roles.speakers:
        mic_keys = roles.mics.get(name, [])
        parts = []
        if not mic_keys and name in roles.visual_speakers:
            # Ei mikkiä: puhe huulten liikkeestä. Sama ``grid.lane``, mutta
            # kynnys on kuvalle mitattu (``VISUAL_MARGIN_DB``) ja siirtyy
            # lähikuvan herkkyysasetuksen mukana. Ennen mittausta ei ole
            # käyrää, eikä kaistaa tehdä: mittaamaton ei ole hiljaisuutta.
            close = roles.closes[name]
            cfg = tracks.get(close, TrackConfig())
            margin = max(3.0, visual_speech.VISUAL_MARGIN_DB
                         + (cfg.sensitivity_db - grid_lib.FLOOR_MARGIN_DB))
            for item in timeline.track_media(close):
                twin = dataclasses.replace(item, key=item.key + visual_speech.SUFFIX)
                if twin.key not in analysis.envelopes:
                    continue
                db, valid, floor = analysis.aligned(twin, program_start, n)
                parts.append((db, valid, floor, margin, 0.0))
            if not parts:
                continue
        elif not mic_keys:
            continue
        for key in mic_keys:
            cfg = tracks.get(key, TrackConfig())
            # Raidan osat ovat eri tiedostoja mutta sama mikki: sama säädin,
            # sama puhuja, eri kohta aikajanaa.
            for item in timeline.track_media(key):
                db, valid, floor = analysis.aligned(item, program_start, n)
                parts.append((db, valid, floor, cfg.sensitivity_db, cfg.gain_db))
        # Kynnyssääntö on kirjastossa. Herkkyys on kynnys pohjakohinan yli;
        # vahvistus siirtää sekä signaalin että pohjan, joten se ei vaikuta
        # kynnykseen — vain mikkien keskinäiseen vertailuun päällekkäispuheessa.
        heard = grid_lib.lane(name, parts)

        close_key = roles.closes.get(name)
        avail = None
        if close_key:
            items = timeline.track_media(close_key)
            if items:
                avail = availability(items, program_start, n)
        lanes.append(
            SpeakerLanes(
                name=name, level=heard.level, on=heard.on,
                close_key=close_key, available=avail,
            )
        )

    index_of = {lane.name: i for i, lane in enumerate(lanes)}
    groups = []
    for key, names in roles.groups.items():
        covers = tuple(index_of[name] for name in names if name in index_of)
        if not covers:
            continue
        items = timeline.track_media(key)
        groups.append(GroupShot(
            key=key,
            label=" & ".join(n for n in names if n in index_of),
            covers=covers,
            available=availability(items, program_start, n) if items else None,
        ))

    shots = []
    for shot in roles.shots:
        items = timeline.track_media(shot.key)
        names = [name for name in shot.covers if name in index_of]
        shots.append(ShotLanes(
            key=shot.key, label=" & ".join(shot.covers),
            covers=tuple(index_of[name] for name in names),
            context=shot.key == roles.wide_key,
            available=availability(items, program_start, n) if items else None,
        ))

    grid = Grid(
        n=n, program_start=float(program_start), speakers=lanes,
        wide_key=roles.wide_key, groups=groups, shots=shots,
        edits=_source_edits(timeline, program_start, program_end),
    )
    return grid, program_start, program_end
