"""Jakson paketti: alkutekstit, musiikkipohjat ja lopputekstit.

Paketti rakentaa yhden klippisuunnitelman, jota sekä FCPXML-kirjoitin että
Render-viedä käyttävät — Render ei päätä mitään itse. Tekstit ovat valmiita
alfa-elokuvia (ProRes 4444) tai Tekstitys-työkalun tuottamia; musiikkipohjien
nousu, lasku ja tasonvaimennus puheen alle noudattavat automikserin
mittaamia käyriä (nhsx.musicbed).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from fractions import Fraction
from pathlib import Path

from nhsx.musicbed import curve as bed_curve

# Musiikkipohjan äänekkäin hetki jää tämän verran käsitellyn puheen alle
# (automikserin stems_mix.py:n BED_UNDER_SPEECH_DB).
BED_UNDER_SPEECH_DB = 1.0

# Puheen aikana jatkuva pohja vaimenee tasoonsa nähden näin paljon.
TAIL_UNDER_DB = -8.0

# FCPXML-lanen numerot: reaktiot istuvat laneilla 1-2, paketin kuva niiden
# yläpuolella ja pohjat mikkien kanssa negatiivisilla laneilla.
TITLE_LANE = 3
BED_LANE = -4

TITLE_ROLE = "titles.Tekstit"
BED_ROLE = "music.Musiikkipohja"

# Tekstityksen render-alpha-vientipääte (tekstitys PR #78, tarvitaan vasta kun
# se on mergetty; siihen asti generoitu tila raportoidaan käyttökelvottomaksi).
TEKSTITYS_RENDER_ALPHA = "render-alpha"


@dataclass
class TitleCard:
    """Yksi tekstikortti (alku- tai lopputeksti)."""

    mode: str = "off"  # "off" | "file" | "generated"
    path: str = ""  # valmis alfa-elokuva, kun mode == "file"
    text: str = ""  # generoitu teksti, kun mode == "generated"
    duration: float = 5.0  # sekuntia; vain generoidulle, tiedoston kesto luetaan

    def to_json(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_json(data: dict | None) -> "TitleCard":
        if not data:
            return TitleCard()
        return TitleCard(**{k: v for k, v in data.items() if k in TitleCard.__dataclass_fields__})


@dataclass
class BedSettings:
    """Musiikkipohjat: johdanto + loppu tai koko jakson alla."""

    mode: str = "intro_outro"  # "off" | "intro_outro" | "throughout"
    intro_path: str = ""
    outro_path: str = ""
    throughout_path: str = ""
    # Pidä tiedoston oma taso; muuten sovitetaan puheen alle (BED_UNDER_SPEECH_DB).
    keep_music_level: bool = False

    def to_json(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_json(data: dict | None) -> "BedSettings":
        if not data:
            return BedSettings()
        return BedSettings(**{k: v for k, v in data.items() if k in BedSettings.__dataclass_fields__})


@dataclass
class CreditsSettings:
    """Lopputekstit: jakson alussa, lopussa tai molemmissa."""

    mode: str = "off"  # "off" | "file" | "generated"
    placement: str = "end"  # "start" | "end" | "both"
    path: str = ""
    text: str = ""
    duration: float = 8.0

    def to_json(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_json(data: dict | None) -> "CreditsSettings":
        if not data:
            return CreditsSettings()
        return CreditsSettings(
            **{k: v for k, v in data.items() if k in CreditsSettings.__dataclass_fields__}
        )


@dataclass
class PackageSettings:
    """Koko paketin asetukset; tallentuu projektin JSON:iin sellaisenaan."""

    intro: TitleCard = field(default_factory=TitleCard)
    outro: TitleCard = field(default_factory=TitleCard)
    credits: CreditsSettings = field(default_factory=CreditsSettings)
    beds: BedSettings = field(default_factory=BedSettings)

    def to_json(self) -> dict:
        return {
            "intro": self.intro.to_json(),
            "outro": self.outro.to_json(),
            "credits": self.credits.to_json(),
            "beds": self.beds.to_json(),
        }

    @staticmethod
    def from_json(data: dict | None) -> "PackageSettings":
        if not data:
            return PackageSettings()
        return PackageSettings(
            intro=TitleCard.from_json(data.get("intro")),
            outro=TitleCard.from_json(data.get("outro")),
            credits=CreditsSettings.from_json(data.get("credits")),
            beds=BedSettings.from_json(data.get("beds")),
        )


@dataclass
class PackageVideoClip:
    """Yksi kuvaklippi (tekstikortti) paketin lanella."""

    kind: str  # "intro" | "outro" | "credits_start" | "credits_end"
    name: str
    path: str
    start: Fraction  # ohjelma-aika
    end: Fraction
    lane: int = TITLE_LANE
    role: str = TITLE_ROLE
    width: int = 1920  # mitattu tiedostosta; assetin formaattia varten
    height: int = 1080

    @property
    def duration(self) -> Fraction:
        return self.end - self.start


@dataclass
class PackageAudioClip:
    """Yksi musiikkipohjaklippi äänilanella, vaimennuskäyrä mukana."""

    kind: str  # "bed_intro" | "bed_outro" | "bed_throughout"
    name: str
    path: str
    start: Fraction
    end: Fraction
    lane: int = BED_LANE
    role: str = BED_ROLE
    # (ohjelma-aika sekunteina, dB suhteessa perustasoon) nousevassa järjestyksessä.
    curve: list[tuple[float, float]] = field(default_factory=list)
    base_gain_db: float = 0.0  # tasonsovitus ennen käyrää
    channels: int = 2
    rate: int = 48000

    @property
    def duration(self) -> Fraction:
        return self.end - self.start


def _frac(seconds: float) -> Fraction:
    return Fraction(seconds).limit_denominator(1000)


def video_clips(
    settings: PackageSettings,
    program_start: Fraction,
    program_end: Fraction,
    durations: dict[str, float] | None = None,
) -> list[PackageVideoClip]:
    """Tekstikorttien sijoittelu ohjelma-aikajanaan.

    ``durations`` antaa valmiiden tiedostojen kestot sekunteina poluittain;
    generoiduille käytetään asetusten kestoa. Kortit, joiden mode on "off"
    tai joilta puuttuu lähde, jätetään pois.
    """
    durations = durations or {}
    clips: list[PackageVideoClip] = []

    def card(card_settings: TitleCard | CreditsSettings, kind: str, start: Fraction) -> None:
        if card_settings.mode == "off":
            return
        if card_settings.mode == "file":
            if not card_settings.path:
                return
            length = durations.get(card_settings.path)
            if length is None or length <= 0:
                return  # kestoa ei ole mitattu vielä — ei arvata
        else:  # generated
            if not card_settings.text.strip():
                return
            length = card_settings.duration
        end = min(start + _frac(length), program_end)
        if end <= start:
            return
        clips.append(
            PackageVideoClip(
                kind=kind,
                name=f"{kind}: {Path(card_settings.path).stem if card_settings.mode == 'file' else 'generoitu'}",
                path=card_settings.path,
                start=start,
                end=end,
            )
        )

    card(settings.intro, "intro", program_start)
    if settings.credits.mode != "off" and settings.credits.placement in ("start", "both"):
        after_intro = clips[-1].end if clips else program_start
        card(settings.credits, "credits_start", after_intro)
    if settings.credits.mode != "off" and settings.credits.placement in ("end", "both"):
        length = (
            durations.get(settings.credits.path, 0.0)
            if settings.credits.mode == "file"
            else settings.credits.duration
        )
        card(settings.credits, "credits_end", program_end - _frac(length))
    if settings.outro.mode != "off":
        length = (
            durations.get(settings.outro.path, 0.0)
            if settings.outro.mode == "file"
            else settings.outro.duration
        )
        card(settings.outro, "outro", program_end - _frac(length))
    return clips


def throughout_curve(
    start: float, end: float, speech: list[tuple[float, float]]
) -> list[tuple[float, float]]:
    """Koko jakson alla soivan pohjan vaimennus puheen mukaan.

    Puheen alkaessa pohja vaimenee TAIL_UNDER_DB:iin 0,4 s johdolla ja palaa
    1,34 s paluulla (musicbed-moduulin mittaamat arvot).
    """
    points: list[tuple[float, float]] = [(start, 0.0)]
    lead, release = 0.4, 1.34
    for span_start, span_end in sorted(speech):
        if span_end <= start or span_start >= end:
            continue
        dip_start = max(start, span_start - lead)
        dip_end = min(end, span_end + release)
        if dip_start > points[-1][0]:
            points.append((dip_start, 0.0))
        points.append((min(dip_start + lead, end), TAIL_UNDER_DB))
        points.append((dip_end, TAIL_UNDER_DB))
        points.append((min(dip_end + release, end), 0.0))
    if points[-1] != (end, 0.0):
        points.append((end, points[-1][1]))
    return points


def audio_clips(
    settings: PackageSettings,
    program_start: Fraction,
    program_end: Fraction,
    speech: list[tuple[float, float]],
    durations: dict[str, float] | None = None,
    bed_loudness: dict[str, float] | None = None,
    speech_lufs: float | None = None,
) -> list[PackageAudioClip]:
    """Musiikkipohjien sijoittelu ja vaimennuskäyrät.

    ``bed_loudness`` antaa pohjien mitatut äänekkyydet (LUFS) poluittain;
    ``speech_lufs`` on käsitellyn puheen äänekkyys. Ilman keep_music_leveliä
    pohjan perustaso sovitetaan niin, että sen äänekkäin hetki jää
    BED_UNDER_SPEECH_DB:n verran puheen alle. Käyrät tulevat
    nhsx.musicbed.curve:lla (intro/outro) tai throughout_curve:lla.
    """
    durations = durations or {}
    bed_loudness = bed_loudness or {}
    clips: list[PackageAudioClip] = []
    beds = settings.beds
    if beds.mode == "off":
        return clips

    def gain(path: str) -> float:
        if beds.keep_music_level or speech_lufs is None or path not in bed_loudness:
            return 0.0
        return (speech_lufs - BED_UNDER_SPEECH_DB) - bed_loudness[path]

    def make(kind: str, path: str, start: float, end: float, cold_open: bool) -> None:
        if not path or end <= start:
            return
        local_speech = [
            (max(start, s) - start, min(end, e) - start)
            for s, e in speech
            if e > start and s < end
        ]
        if kind == "bed_throughout":
            points = throughout_curve(0.0, end - start, local_speech)
        else:
            measured = bed_curve(0.0, end - start, local_speech, cold_open)
            points = measured if measured is not None else [(0.0, 0.0)]
        clips.append(
            PackageAudioClip(
                kind=kind,
                name=f"{kind}: {Path(path).stem}",
                path=path,
                start=_frac(start),
                end=_frac(end),
                curve=[(t + start, db) for t, db in points],
                base_gain_db=gain(path),
            )
        )

    start_f = float(program_start)
    end_f = float(program_end)
    if beds.mode == "throughout":
        make("bed_throughout", beds.throughout_path, start_f, end_f, True)
    else:
        intro_dur = durations.get(beds.intro_path, 0.0)
        outro_dur = durations.get(beds.outro_path, 0.0)
        if beds.intro_path and intro_dur > 0:
            make("bed_intro", beds.intro_path, start_f, start_f + intro_dur, True)
        if beds.outro_path and outro_dur > 0:
            make("bed_outro", beds.outro_path, end_f - outro_dur, end_f, False)
    return clips


def generated_source_available() -> bool:
    """Onko generoitujen tekstien lähde (Tekstitys render-alpha) käytettävissä?

    Tekstityksen alfa-vienti on erillisessä PR:ssä; siihen asti kutsuja
    raportoi generoidun tilan käyttökelvottomaksi eikä yritä ajaa mitään.
    """
    import shutil
    import subprocess

    exe = shutil.which("tekstitys")
    if exe is None:
        return False
    try:
        out = subprocess.run(
            [exe, "--help"], capture_output=True, text=True, timeout=15
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return TEKSTITYS_RENDER_ALPHA in out.stdout


def parse_settings(text: str) -> PackageSettings:
    """Asetusten lukeminen projektin JSON:sta."""
    return PackageSettings.from_json(json.loads(text))
