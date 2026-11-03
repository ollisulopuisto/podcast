"""Komentoriviltä pyydettyjen lähdevälien renderöinti pystyleikkeiksi."""

from __future__ import annotations

import csv
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from pathlib import Path
from urllib.parse import unquote, urlparse
from xml.etree import ElementTree as ET

from . import probe, render, reframe
from .finalcut.read import read_fcpxml
from speechmix.binaries import get_binary_path


@dataclass(frozen=True)
class ClipRange:
    name: str
    start: Fraction
    end: Fraction


def seconds(value: str) -> Fraction:
    """Muunna sekunnit tai MM:SS / HH:MM:SS tarkaksi murtoluvuksi."""
    raw = value.strip()
    if not raw:
        raise ValueError("empty timecode")
    parts = raw.split(":")
    if len(parts) == 1:
        try:
            decimal = Decimal(raw)
            if not decimal.is_finite():
                raise ValueError("timecode must be finite")
            result = Fraction(decimal)
        except (InvalidOperation, ValueError, ZeroDivisionError, OverflowError) as exc:
            raise ValueError(f"invalid timecode {value!r}") from exc
    elif len(parts) in (2, 3):
        try:
            decimal = Decimal(parts[-1])
            if not decimal.is_finite():
                raise ValueError("timecode must be finite")
            tail = Fraction(decimal)
            if tail < 0 or tail >= 60:
                raise ValueError("seconds in a timecode must be below 60")
            if len(parts) == 2:
                minutes = int(parts[0])
                if minutes < 0:
                    raise ValueError("timecodes cannot be negative")
                result = minutes * 60 + tail
            else:
                hours, minutes = int(parts[0]), int(parts[1])
                if hours < 0 or minutes < 0 or minutes >= 60:
                    raise ValueError("invalid hours or minutes in timecode")
                result = hours * 3600 + minutes * 60 + tail
        except (InvalidOperation, ValueError, ZeroDivisionError) as exc:
            raise ValueError(f"invalid timecode {value!r}: {exc}") from exc
    else:
        raise ValueError(f"invalid timecode {value!r}")
    if result < 0:
        raise ValueError("timecodes cannot be negative")
    return result


def read_ranges(path: str) -> list[ClipRange]:
    """Lue CSV:n välit sarakkeista ``name``, ``start`` ja ``end``."""
    out: list[ClipRange] = []
    names: set[str] = set()
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or not {"start", "end"}.issubset(
            {name.strip().lower() for name in reader.fieldnames if name}
        ):
            raise ValueError("cuts CSV needs a header with start,end columns")
        columns = {name.strip().lower(): name for name in reader.fieldnames if name}
        for row_number, row in enumerate(reader, start=2):
            start = seconds(row[columns["start"]] or "")
            end = seconds(row[columns["end"]] or "")
            if end <= start:
                raise ValueError(f"row {row_number}: end must be after start")
            label = (row.get(columns.get("name", ""), "") or "").strip()
            if not label:
                label = f"clip-{len(out) + 1:03d}"
            if label in names:
                raise ValueError(f"row {row_number}: duplicate clip name {label!r}")
            names.add(label)
            out.append(ClipRange(label, start, end))
    if not out:
        raise ValueError("cuts CSV has no clip ranges")
    return out


def _path_from_uri(value: str) -> Path:
    parsed = urlparse(value)
    if parsed.scheme == "file":
        if parsed.netloc not in ("", "localhost"):
            raise ValueError("file URL must refer to this computer")
        value = unquote(parsed.path)
    elif parsed.scheme:
        raise ValueError("source must be a local path or file:// URL")
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"video file not found: {path}")
    return path


def _time(value: Fraction) -> str:
    return f"{value.numerator}/{value.denominator}s"


def _fake_fcpxml(source: Path, clip: ClipRange, info: dict, path: Path) -> None:
    """Kirjoita yhdestä lähdevälistä yhden videon väliaikainen FCPXML."""
    video = info.get("video") or {}
    fps = Fraction(str(video.get("fps") or 25)).limit_denominator(100_000)
    frame = 1 / fps
    start_frame = round(clip.start / frame)
    end_frame = round(clip.end / frame)
    if end_frame <= start_frame:
        raise ValueError(f"{clip.name}: range is shorter than one source frame")
    start = start_frame * frame
    duration = (end_frame - start_frame) * frame
    media_duration = Fraction(str(info.get("duration") or float(clip.end)))
    width, height = int(video.get("width") or 1920), int(video.get("height") or 1080)
    has_audio = "audio" in info

    root = ET.Element("fcpxml", {"version": "1.10"})
    resources = ET.SubElement(root, "resources")
    ET.SubElement(resources, "format", {
        "id": "r1", "name": f"FFVideoFormat{width}x{height}",
        "frameDuration": _time(frame), "width": str(width), "height": str(height),
    })
    attrs = {
        "id": "r2", "name": source.name, "start": "0s",
        "duration": _time(media_duration), "hasVideo": "1",
        "videoSources": "1", "format": "r1",
    }
    if has_audio:
        audio = info.get("audio") or {}
        attrs.update({
            "hasAudio": "1", "audioSources": "1",
            "audioChannels": str(int(audio.get("channels") or 2)),
            "audioRate": str(int(audio.get("rate") or 48000)),
        })
    asset = ET.SubElement(resources, "asset", attrs)
    ET.SubElement(asset, "media-rep", {
        "kind": "original-media", "src": source.as_uri(),
    })
    library = ET.SubElement(root, "library")
    event = ET.SubElement(library, "event", {"name": "PyCapSlap clips"})
    project = ET.SubElement(event, "project", {"name": clip.name})
    ET.SubElement(project, "sequence", {
        "format": "r1", "duration": _time(duration), "tcStart": "0s",
        "tcFormat": "NDF", "audioLayout": "stereo", "audioRate": "48k",
    })
    sequence = project[-1]
    spine = ET.SubElement(sequence, "spine")
    ET.SubElement(spine, "asset-clip", {
        "ref": "r2", "offset": "0s", "name": clip.name,
        "start": _time(start), "duration": _time(duration), "format": "r1",
    })
    ET.ElementTree(root).write(path, encoding="UTF-8", xml_declaration=True)


def render_clips(source: str, cuts: str, output_dir: str, overwrite: bool = False,
                 center_crop: bool = False) -> list[Path]:
    """Tee lähdevideon jokaisesta CSV-välistä oma 9:16-MP4."""
    video_path = _path_from_uri(source)
    ranges = read_ranges(cuts)
    info = probe.info(str(video_path))
    if not info.get("video"):
        raise ValueError(f"no video stream found in {video_path}")
    source_duration = Fraction(str(info.get("duration") or 0))
    fps = Fraction(str(info["video"].get("fps") or 25)).limit_denominator(100_000)
    frame = 1 / fps
    for clip in ranges:
        if source_duration and clip.end > source_duration:
            raise ValueError(f"{clip.name}: end time exceeds video duration")

    destination = Path(output_dir).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    paths = []
    used_names: set[str] = set()
    for clip in ranges:
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", clip.name).strip("-.")
        if not safe_name:
            raise ValueError(f"clip name {clip.name!r} has no safe filename characters")
        if safe_name in used_names:
            raise ValueError(f"clip names collide after filename cleanup: {clip.name!r}")
        used_names.add(safe_name)
        target = destination / f"{safe_name}.mp4"
        if target.exists() and not overwrite:
            raise FileExistsError(f"output already exists: {target} (use --overwrite)")
        paths.append(target)

    # Sama koko lähteen mittaus palvelee kaikkia välejä ja tallentuu välimuistiin.
    detector = table = None
    if not center_crop:
        try:
            from .video import detect, measure

            detector = detect.load("vision")
            table = measure.table(str(video_path), detector)
        except Exception as exc:  # Kasvontunnistus puuttuu, keskitetty rajaus toimii.
            print(f"FACE_TRACKING unavailable ({exc}); using center crop", flush=True)

    from .reframe import Reframer

    rendered: list[Path] = []
    with tempfile.TemporaryDirectory(prefix="autoraffkat-clips-") as temporary:
        for index, (clip, target) in enumerate(zip(ranges, paths, strict=True), start=1):
            xml_path = Path(temporary) / f"clip-{index:04d}.fcpxml"
            _fake_fcpxml(video_path, clip, info, xml_path)
            timeline = read_fcpxml(str(xml_path))
            item = next(media for media in timeline.media if media.has_video)
            placement = item.placements[0]
            start = placement.start - item.asset_start
            duration = placement.duration
            frames = round(duration / frame)
            framing = None
            if table is not None:
                framing = Reframer({item.key: table}).from_item(
                    item, 0.0, float(duration), own=True
                )
            shot = render.Shot(
                start=0, end=frames, path=str(video_path),
                file_start=float(start), width=item.width or int(info["video"]["width"]),
                height=item.height or int(info["video"]["height"]), fill=True,
                scale0=framing.scale if framing else 1.0,
                scale1=framing.scale if framing else 1.0,
                pos_x=framing.pos_x if framing else 0.0,
                pos_y=framing.pos_y if framing else 0.0,
            )
            sources = []
            if "audio" in info:
                audio_path = Path(temporary) / f"audio-{index:04d}.wav"
                audio_cmd = [
                    get_binary_path("ffmpeg"), "-nostdin", "-v", "error", "-y",
                    "-ss", str(float(start)), "-i", str(video_path),
                    "-t", str(float(duration)), "-map", "0:a:0", "-vn", "-ac", "2",
                    "-ar", "48000", "-c:a", "pcm_s16le", str(audio_path),
                ]
                try:
                    audio_result = subprocess.run(
                        audio_cmd, stdin=subprocess.DEVNULL, capture_output=True,
                        text=True, check=False, timeout=3600,
                    )
                except subprocess.TimeoutExpired as exc:
                    raise RuntimeError(f"audio extraction timed out for {clip.name}") from exc
                if audio_result.returncode:
                    raise RuntimeError(
                        f"audio extraction failed for {clip.name}: "
                        f"{audio_result.stderr.strip()}"
                    )
                sources.append(render.AudioSource(
                    str(audio_path), [(0.0, float(duration), 0.0)], stereo=True,
                ))

            def report(fraction: float, clip=clip) -> None:
                print(f"PROGRESS\t{fraction:.4f}\t{clip.name}", flush=True)

            print(f"RENDER\t{clip.name}\t{target}", flush=True)
            render.render_program(
                [shot], sources, reframe.PROJECT_W, reframe.PROJECT_H,
                frame, frames, 0.0, str(target), progress=report,
            )
            rendered.append(target)
            print(f"OUTPUT\t{target}", flush=True)
    return rendered


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="autoraffkat render-clips",
        description=("Render selected ranges as separate 9:16 clips / "
                     "Renderöi valitut kohdat erillisiksi 9:16-pystyvideoiksi."),
    )
    parser.add_argument("source", help="local video path or file:// URL / paikallinen videotiedosto")
    parser.add_argument("--cuts", required=True,
                        help="CSV with name,start,end columns / CSV-sarakeotsikot")
    parser.add_argument("--output-dir", required=True, help="output folder / kohdekansio")
    parser.add_argument("--overwrite", action="store_true",
                        help="replace existing files / korvaa olemassa olevat tiedostot")
    parser.add_argument("--center-crop", action="store_true",
                        help="skip face measurement / ohita kasvontunnistus ja rajaa keskeltä")
    args = parser.parse_args(argv)
    try:
        render_clips(args.source, args.cuts, args.output_dir,
                     overwrite=args.overwrite, center_crop=args.center_crop)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"autoraffkat render-clips: {exc}", file=sys.stderr)
        return 1
    return 0
