"""Muodosta alkuperäisistä videoista ja mikrofoneista FCPXML-lähdeprojekti."""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from xml.sax.saxutils import quoteattr

from fcpxml.timeline import format_time

from speechmix.rms import envelope_for

from . import probe
from .audio import cache_dir
from .audio.sync import estimate_offset
from .model import HOP
from .timeline import ZERO

MAX_SYNC_SHIFT_S = 300.0
MIN_SYNC_OVERLAP_S = 5.0


class MediaImportError(ValueError):
    """Lähdemateriaalia ei voi muodostaa aikajanaksi."""


@dataclass(frozen=True)
class MediaSource:
    """Mediatiedoston kesto ja ääni-/kuvaraidat ffprobesta."""

    path: str
    name: str
    duration: Fraction
    has_video: bool
    has_audio: bool
    width: int = 0
    height: int = 0
    frame_duration: Fraction | None = None
    audio_channels: int = 0
    audio_rate: int = 0


def inspect_media(paths: list[str]) -> list[MediaSource]:
    """Tarkista valitut mediat ja vaaditut tahdistusraidat."""
    unique = list(dict.fromkeys(os.path.abspath(os.path.expanduser(p)) for p in paths))
    if len(unique) < 2:
        raise MediaImportError("Choose at least one camera and one microphone file.")

    sources: list[MediaSource] = []
    for path in unique:
        if not os.path.isfile(path):
            raise MediaImportError(f"Media file not found: {path}")
        info = probe.info(path)
        duration = info.get("duration")
        if duration is None or not math.isfinite(duration) or duration <= 0:
            raise MediaImportError(f"Could not read media duration: {path}")
        video = info.get("video") or {}
        audio = info.get("audio") or {}
        fps = video.get("fps")
        frame_duration = (
            Fraction(1, 1) / Fraction(str(fps)).limit_denominator(1_000_000)
            if fps and fps > 0
            else None
        )
        if not video and not audio:
            raise MediaImportError(f"Media has no usable audio or video: {path}")
        sources.append(
            MediaSource(
                path=path,
                name=Path(path).stem,
                duration=Fraction(str(duration)).limit_denominator(1_000_000),
                has_video=bool(video),
                has_audio=bool(audio),
                width=int(video.get("width") or 0),
                height=int(video.get("height") or 0),
                frame_duration=frame_duration,
                audio_channels=int(audio.get("channels") or 0),
                audio_rate=int(audio.get("rate") or 0),
            )
        )

    if not any(source.has_video and source.has_audio for source in sources):
        raise MediaImportError("Choose a camera file with reference audio.")
    if not any(source.has_audio and not source.has_video for source in sources):
        raise MediaImportError("Choose at least one separate microphone recording.")
    return sources


def estimate_sync(
    paths: list[str],
    *,
    reference_path: str | None = None,
    envelope_loader=None,
    progress=None,
) -> dict:
    """Mittaa erilliset mikrofonit valitun kameran ääneen nähden.

    Pisteytys näkyy käyttöliittymässä arviona, ei automaattisena hyväksyntänä.
    ``envelope_loader`` on testiraja; normaalisti verhokäyrä puretaan ffmpegillä
    ja säilötään sovelluksen omaan välimuistiin.
    """
    sources = inspect_media(paths)
    references = [source for source in sources if source.has_video and source.has_audio]
    if reference_path:
        ref_path = os.path.abspath(os.path.expanduser(reference_path))
        reference = next((source for source in references if source.path == ref_path), None)
        if reference is None:
            raise MediaImportError("Selected sync reference must be a camera with audio.")
    else:
        reference = max(references, key=lambda source: source.duration)

    tracks_to_measure = [
        source for source in sources
        if source.path != reference.path and source.has_audio
    ]
    inputs = [reference, *tracks_to_measure]
    source_by_path = {source.path: source for source in inputs}
    envelopes = {}
    loader = envelope_loader or (
        lambda path, report: envelope_for(
            path,
            progress=lambda elapsed: report(
                elapsed,
                elapsed / float(source_by_path[path].duration),
            ),
            cache_dir=cache_dir(),
        )
    )
    for index, source in enumerate(inputs):
        def report(_done, fraction, *, index=index, source=source):
            if progress:
                progress(
                    source.name,
                    (index + min(1.0, max(0.0, fraction))) / len(inputs),
                )

        try:
            if envelope_loader:
                envelopes[source.path] = loader(source.path)
            else:
                envelopes[source.path] = loader(source.path, report)
        except Exception:
            if source is reference:
                raise
            continue
        report(1, 1.0)
    reference_envelope = envelopes[reference.path]
    tracks = []
    for source in tracks_to_measure:
        try:
            source_envelope = envelopes[source.path]
            estimate = estimate_offset(
                reference_envelope,
                source_envelope,
                hop_seconds=HOP,
                max_shift_seconds=MAX_SYNC_SHIFT_S,
                min_overlap_seconds=MIN_SYNC_OVERLAP_S,
            )
        except Exception as exc:
            tracks.append(
                {"path": source.path, "name": source.name,
                 "shift_seconds": None, "correlation": None,
                 "error": str(exc)}
            )
            continue
        tracks.append(
            {
                "path": source.path,
                "name": source.name,
                "shift_seconds": estimate.shift_seconds if estimate else None,
                "correlation": estimate.correlation if estimate else None,
                "error": "" if estimate else "Not enough matching audio to estimate a shift.",
            }
        )
    return {"reference": reference.path, "tracks": tracks}


def _role_name(name: str) -> str:
    clean = re.sub(r"[^\w.-]+", "-", name, flags=re.UNICODE).strip("-.")
    return clean or "Microphone"


def _source_path(sources: list[MediaSource], destination: str | None) -> Path:
    folder = Path(destination).expanduser().resolve() if destination else Path(sources[0].path).parent
    folder.mkdir(parents=True, exist_ok=True)
    candidate = folder / "autoraffkat-source.fcpxml"
    suffix = 2
    while candidate.exists():
        candidate = folder / f"autoraffkat-source v{suffix}.fcpxml"
        suffix += 1
    return candidate


def write_source_project(
    paths: list[str],
    shifts: dict[str, float] | None = None,
    *,
    destination: str | None = None,
) -> str:
    """Kirjoita uusi FCPXML, jossa jokainen kamera ja mikki on omalla raidallaan.

    ``shifts`` kertoo aikajanalle lisättävän siirron lähdetiedostoittain.
    Kaikkia raitoja siirretään lisäksi samalla alkuosalla, jotta FCPXML:n
    aikajanaan ei kirjoiteta negatiivisia offset-aikoja.
    """
    sources = inspect_media(paths)
    shifts = shifts or {}
    source_by_path = {source.path: source for source in sources}
    normalized_shifts: dict[str, Fraction] = {}
    for path, seconds in shifts.items():
        key = os.path.abspath(os.path.expanduser(path))
        if key not in source_by_path or not math.isfinite(seconds):
            raise MediaImportError(f"Invalid sync shift for media: {path}")
        normalized_shifts[key] = Fraction(str(seconds)).limit_denominator(1_000_000)

    origin = max(ZERO, -min(normalized_shifts.values(), default=ZERO))
    placed = [
        (source, origin + normalized_shifts.get(source.path, ZERO))
        for source in sources
    ]
    duration = max(offset + source.duration for source, offset in placed)
    video_sources = [source for source in sources if source.has_video]
    frame_duration = next(
        (source.frame_duration for source in video_sources if source.frame_duration),
        Fraction(1, 25),
    )
    format_attrs = (
        'id="r1" name="Autoraffkat" '
        f'frameDuration={quoteattr(format_time(frame_duration))} '
        f'width="{next((s.width for s in video_sources if s.width), 1920)}" '
        f'height="{next((s.height for s in video_sources if s.height), 1080)}"'
    )

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<!DOCTYPE fcpxml>",
        '<fcpxml version="1.10">',
        "  <resources>",
        f"    <format {format_attrs}/>",
    ]
    resource_ids: dict[str, str] = {}
    for index, source in enumerate(sources, 2):
        rid = f"r{index}"
        resource_ids[source.path] = rid
        attrs = [
            f'id="{rid}"',
            f"name={quoteattr(source.name)}",
            'start="0s"',
            f'duration={quoteattr(format_time(source.duration))}',
        ]
        if source.has_video:
            attrs += [
                'hasVideo="1"',
                'videoSources="1"',
                'format="r1"',
            ]
        if source.has_audio:
            attrs += [
                'hasAudio="1"',
                'audioSources="1"',
                f'audioChannels="{source.audio_channels or 1}"',
                f'audioRate="{source.audio_rate or 48000}"',
            ]
        lines += [
            f"    <asset {' '.join(attrs)}>",
            f'      <media-rep kind="original-media" src={quoteattr(Path(source.path).as_uri())}/>',
            "    </asset>",
        ]

    lines += [
        "  </resources>",
        "  <library>",
        f"    <event name={quoteattr(Path(sources[0].path).parent.name or 'Media')}>",
        f"      <project name={quoteattr(Path(sources[0].path).parent.name or 'Autoraffkat') }>",
        f'        <sequence format="r1" duration={quoteattr(format_time(duration))} '
        'tcStart="0s" tcFormat="NDF">',
        "          <spine>",
        f'            <gap name="Source media" offset="0s" start="0s" '
        f'duration={quoteattr(format_time(duration))}>',
    ]
    video_lane = 0
    audio_lane = 0
    for source, offset in placed:
        if source.has_video:
            video_lane += 1
            lane = video_lane
            source_enable = ' srcEnable="video"' if source.has_audio else ""
            audio_role = ""
        else:
            audio_lane += 1
            lane = -audio_lane
            source_enable = ""
            audio_role = f' audioRole="dialogue.{_role_name(source.name)}"'
        lines.append(
            f'              <asset-clip ref="{resource_ids[source.path]}" lane="{lane}" '
            f"offset={quoteattr(format_time(offset))} name={quoteattr(source.name)} "
            f'start="0s" duration={quoteattr(format_time(source.duration))}'
            f"{audio_role}{source_enable}/>"
        )
    lines += [
        "            </gap>",
        "          </spine>",
        "        </sequence>",
        "      </project>",
        "    </event>",
        "  </library>",
        "</fcpxml>",
    ]

    path = _source_path(sources, destination)
    with path.open("x", encoding="utf-8") as output:
        output.write("\n".join(lines) + "\n")
    return str(path)
