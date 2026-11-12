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
    fps: float = 0.0  # lähteen oma ruutunopeus; 0 = projektin nopeus

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

    def card(
        card_settings: TitleCard | CreditsSettings,
        kind: str,
        start: Fraction,
        end_cap: Fraction | None = None,
    ) -> None:
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
        limit = program_end if end_cap is None else min(end_cap, program_end)
        end = min(start + _frac(length), limit)
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
    # Lopun järjestys on päätetty: tekijät ensin, outro viimeisenä. Ne eivät
    # jaa lopun kehyksiä samalla lanella vaan credits_end päättyy outron
    # alkuun (2026-11: päällekkäisyys olisi satunnaista pinoutumista).
    outro_len = _frac(
        durations.get(settings.outro.path, 0.0)
        if settings.outro.mode == "file"
        else settings.outro.duration
    ) if settings.outro.mode != "off" else Fraction(0)
    if settings.credits.mode != "off" and settings.credits.placement in ("end", "both"):
        length = (
            durations.get(settings.credits.path, 0.0)
            if settings.credits.mode == "file"
            else settings.credits.duration
        )
        # Tekstit+outro voivat olla ohjelmaa pidemmät: alku ripustetaan
        # ohjelman alkuun eikä miinukselle, ja loppu pysyy outron alussa.
        card(
            settings.credits,
            "credits_end",
            max(program_start, program_end - outro_len - _frac(length)),
            end_cap=program_end - outro_len,
        )
    if settings.outro.mode != "off":
        card(settings.outro, "outro", program_end - outro_len)
    return clips


def throughout_curve(
    start: float, end: float, speech: list[tuple[float, float]]
) -> list[tuple[float, float]]:
    """Koko jakson alla soivan pohjan vaimennus puheen mukaan.

    Puheen alkaessa pohja vaimenee TAIL_UNDER_DB:iin 0,4 s johdolla ja palaa
    1,34 s paluulla (musicbed-moduulin mittaamat arvot). Vaimennusikkunat
    (johdoineen ja paluineen) sulautetaan ennen pisteitä: muuten lähekkäiset
    puhejaksot tuottaisivat taaksepäin meneviä keyframe-aikoja ja musiikki
    palautuisi kesken seuraavan puhujan vuoron.
    """
    lead, release = 0.4, 1.34
    windows: list[list[float]] = []
    for span_start, span_end in sorted(speech):
        if span_end <= start or span_start >= end:
            continue
        low = max(start, span_start - lead)
        high = min(end, span_end + release)
        if windows and low <= windows[-1][1]:
            windows[-1][1] = max(windows[-1][1], high)
        else:
            windows.append([low, high])
    points: list[tuple[float, float]] = [(start, 0.0)]
    for low, high in windows:
        if low > points[-1][0]:
            points.append((low, 0.0))
        points.append((min(low + lead, high), TAIL_UNDER_DB))
        points.append((high, TAIL_UNDER_DB))
        points.append((min(high + release, end), 0.0))
    if points[-1] != (end, 0.0):
        points.append((end, points[-1][1]))
    times = [t for t, _ in points]
    assert times == sorted(times), "keyframet menevät taaksepäin"
    return points


def active_bed_paths(beds: BedSettings) -> list[str]:
    """Käytössä olevan pohjatilan tiedostot: mittaus ja varoitukset
    koskevat vain näitä, ei muistiin jääneitä polkuja toisesta tilasta."""
    if beds.mode == "off":
        return []
    if beds.mode == "throughout":
        return [beds.throughout_path] if beds.throughout_path else []
    return [p for p in (beds.intro_path, beds.outro_path) if p]


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

    def make(kind: str, path: str, start: Fraction, end: Fraction, cold_open: bool) -> None:
        if not path or end <= start:
            return
        # Klipin rajat pysyvät rationaaleina loppuun asti (repon
        # rationaaliaikasääntö); käyrän dB-pisteet ovat sekunteja ja
        # kvantisoituvat kirjoittajan to_frames:ssa.
        start_f, end_f = float(start), float(end)
        local_speech = [
            (max(start_f, s) - start_f, min(end_f, e) - start_f)
            for s, e in speech
            if e > start_f and s < end_f
        ]
        if kind == "bed_throughout":
            points = throughout_curve(0.0, end_f - start_f, local_speech)
        else:
            measured = bed_curve(0.0, end_f - start_f, local_speech, cold_open)
            # Mittausta ei aina ole (ei riittävää taukoa). Päätetty
            # varapolku (2026-11): sama puhetta seuraava vaimennus kuin
            # throughout-tilassa — litteä käyrä soittaisi musiikin
            # vaimentamatta puheen päälle.
            points = (
                measured
                if measured is not None
                else throughout_curve(0.0, end_f - start_f, local_speech)
            )
        clips.append(
            PackageAudioClip(
                kind=kind,
                name=f"{kind}: {Path(path).stem}",
                path=path,
                start=start,
                end=end,
                curve=[(t + start_f, db) for t, db in points],
                base_gain_db=gain(path),
            )
        )

    if beds.mode == "throughout":
        make("bed_throughout", beds.throughout_path, program_start, program_end, True)
    else:
        # Pohjat puristetaan ohjelmaan: pidempi tiedosto ei karkaa viennin
        # rajojen yli. Jos intro ja outro eivät mahdu molemmat, intro
        # lyhenee outron alkuun (2026-11: loppu on se mikä kuulija kuulee
        # viimeisenä, ja outron häivytys on sen oma).
        intro_dur = _frac(durations.get(beds.intro_path, 0.0))
        outro_dur = _frac(durations.get(beds.outro_path, 0.0))
        outro_start = max(program_end - outro_dur, program_start)
        intro_end = min(program_start + intro_dur, program_end, outro_start)
        if beds.intro_path and intro_dur > 0:
            make("bed_intro", beds.intro_path, program_start, intro_end, True)
        if beds.outro_path and outro_dur > 0:
            make("bed_outro", beds.outro_path, outro_start, program_end, False)
    return clips


def materialize_generated(
    settings: PackageSettings,
    work_dir: str,
    width: int = 1920,
    height: int = 1080,
    fps: float = 25.0,
) -> tuple["PackageSettings", list[str]]:
    """Generoidut kortit ajetuiksi alfa-elokuvoiksi Tekstityksen render-alphalla.

    Palauttaa (syvä kopio asetuksista, ongelmat). Onnistunut kortti on kopiossa
    file-tilassa tuotokseen osoittaen; epäonnistunut jää generated-tilaan ja
    ongelmat kertovat syyn. Tekstityksen alfa-vienti on erillinen PR
    (tekstitys #78): ilman sitä jokainen generoitu kortti on yksi ongelma
    eikä mitään ajeta.
    """
    import os
    import shutil
    import subprocess

    result = PackageSettings.from_json(settings.to_json())
    problems: list[str] = []
    exe = shutil.which("tekstitys")
    if exe is None or not generated_source_available():
        for card in (result.intro, result.outro, result.credits):
            if card.mode == "generated" and card.text.strip():
                problems.append("tekstitys render-alpha puuttuu")
        return result, problems

    os.makedirs(work_dir, exist_ok=True)
    for name in ("intro", "outro", "credits"):
        card = getattr(result, name)
        if card.mode != "generated" or not card.text.strip():
            continue
        duration_ms = round(card.duration * 1000)
        sidecar = os.path.join(work_dir, f"{name}.capslap.json")
        with open(sidecar, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "segments": [
                        {"startMs": 0, "endMs": duration_ms, "text": card.text}
                    ],
                    "style": {},
                },
                fh,
                ensure_ascii=False,
            )
        out = os.path.join(work_dir, f"{name}.mov")
        try:
            done = subprocess.run(
                [
                    exe,
                    "render-alpha",
                    "--captions",
                    sidecar,
                    "--size",
                    f"{width}x{height}",
                    "--fps",
                    str(fps),
                    "--duration",
                    str(card.duration),
                    "--out",
                    out,
                    "--json",
                ],
                capture_output=True,
                text=True,
                timeout=1200,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            problems.append(f"{name}: {exc}")
            continue
        if done.returncode != 0 or not os.path.exists(out):
            problems.append(f"{name}: {(done.stderr or done.stdout).strip()[:200]}")
            continue
        card.mode = "file"
        card.path = out
    return result, problems


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


def speech_spans(grid) -> list[tuple[float, float]]:
    """Jaksot, joilla joku puhuu, ohjelma-ajan sekunteina.

    Sama ruudukkoluku kuin hiljaisuuspassilla: pohjan vaimennus perustuu
    samaan puhetottumuuteen eikä omaan mittaukseen.
    """
    import numpy as np

    from speechmix.masks import HOP, runs

    speakers = getattr(grid, "speakers", ())
    n = int(getattr(grid, "n", 0))
    if n <= 0 or not speakers:
        return []
    talking = np.zeros(n, dtype=bool)
    for speaker in speakers:
        lane = np.asarray(speaker.on, dtype=bool)
        talking[: min(n, lane.size)] |= lane[:n]
    start = float(grid.program_start)
    return [
        (start + lo * HOP, start + hi * HOP)
        for lo, hi, is_talking in runs(talking.astype(np.int8))
        if is_talking
    ]


def parse_settings(text: str) -> PackageSettings:
    """Asetusten lukeminen projektin JSON:sta."""
    return PackageSettings.from_json(json.loads(text))
