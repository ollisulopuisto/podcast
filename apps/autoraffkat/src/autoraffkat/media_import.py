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
# Tämän alle jäävä korrelaatio on epäilyttävä: "auto"-ikkuna laajentaa
# haun koko aineistoon. BBC:n audio-offset-finder tekee saman luottamus-
# rajalla kiinteän ikkunan sijaan. Haku on vektorointi jälkeen halpaa,
# joten ikkuna on tarkkuuspriori, ei suorituskykykysymys.
SYNC_AUTO_THRESHOLD = 0.4
PREVIEW_ALL_SECONDS = 10.0
PREVIEW_SPEAKER_SECONDS = 5.0


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


def _full_window_seconds(reference: "MediaSource", source: "MediaSource") -> float:
    """Koko aineiston haku: viive voi olla enintään pitemmän tiedoston pituus."""
    return float(max(reference.duration, source.duration))


def estimate_sync(
    paths: list[str],
    *,
    reference_path: str | None = None,
    envelope_loader=None,
    progress=None,
    window: str | float = "auto",
) -> dict:
    """Mittaa erilliset mikrofonit valitun kameran ääneen nähden.

    Pisteytys näkyy käyttöliittymässä arviona, ei automaattisena hyväksyntänä.
    ``envelope_loader`` on testiraja; normaalisti verhokäyrä puretaan ffmpegillä
    ja säilötään sovelluksen omaan välimuistiin.

    ``window`` on etsintäikkuna: ``"auto"`` (oletus) hakee ensin
    ±MAX_SYNC_SHIFT_S ja laajentaa koko aineistoon jos osuman korrelaatio
    jää alle SYNC_AUTO_THRESHOLDin, ``"full"`` hakee suoraan koko
    aineistosta, ja lukuarvo on kiinteä ikkuna sekunteina.
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
            full = _full_window_seconds(reference, source)
            if window == "full":
                max_shift = full
            elif window == "auto":
                max_shift = MAX_SYNC_SHIFT_S
            else:
                max_shift = float(window)
                if max_shift <= 0:
                    raise MediaImportError("Sync window must be positive.")
            estimate = estimate_offset(
                reference_envelope,
                source_envelope,
                hop_seconds=HOP,
                max_shift_seconds=max_shift,
                min_overlap_seconds=MIN_SYNC_OVERLAP_S,
            )
            expanded = False
            if window == "auto" and (
                estimate is None or estimate.correlation < SYNC_AUTO_THRESHOLD
            ) and full > max_shift:
                retry = estimate_offset(
                    reference_envelope,
                    source_envelope,
                    hop_seconds=HOP,
                    max_shift_seconds=full,
                    min_overlap_seconds=MIN_SYNC_OVERLAP_S,
                )
                # Laajennus korvaa vain aidosti paremman osuman: heikko
                # osuma kapealla ikkunalla voi olla sattumaa, mutta vielä
                # heikompi täydestä aineistosta ei ole parannus.
                if retry is not None and (
                    estimate is None or retry.correlation > estimate.correlation
                ):
                    estimate = retry
                    expanded = True
        except MediaImportError:
            raise
        except Exception as exc:
            tracks.append(
                {"path": source.path, "name": source.name,
                 "shift_seconds": None, "correlation": None,
                 "error": str(exc), "window_expanded": False}
            )
            continue
        tracks.append(
            {
                "path": source.path,
                "name": source.name,
                "shift_seconds": estimate.shift_seconds if estimate else None,
                "correlation": estimate.correlation if estimate else None,
                "error": "" if estimate else "Not enough matching audio to estimate a shift.",
                "window_expanded": expanded,
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


# --- Esikatselu (kuuntele synkkaus ennen tuontia) ---


def _activity_mask(envelope) -> object:
    """Ääniaktiivisuus verhokäyrästä: yli keskitason + puoli hajontaa.

    Yksinkertainen energiakynnys riittää tähän: tarkoitus on vain löytää
    kohta, jossa puhutaan, ei tarkkaa puhesegmentointia.
    """
    mean = envelope.mean()
    std = envelope.std()
    return envelope > (mean + 0.5 * std)


def _best_window(cum, length: int, width: int):
    """Leveän ikkunan paras sijainti summataulukosta; palauttaa (summa, alku)."""
    if length <= width:
        return (float(cum[length - 1] if length else 0), 0)
    sums = cum[width:] - cum[:-width]
    index = int(sums.argmax())
    return (float(sums[index]), index)


def pick_preview_spans(
    envelopes: dict,
    reference_path: str,
    tracks: list,
    *,
    hop_seconds: float = HOP,
    all_seconds: float = PREVIEW_ALL_SECONDS,
    speaker_seconds: float = PREVIEW_SPEAKER_SECONDS,
) -> dict:
    """Valitsee esikatselupätkät viiteaikajanalla.

    ``tracks`` on estimate_sync:in track-rivit (path + shift_seconds).
    Kaikki-puhuvat-pätkä valitaan niin, että mahdollisimman moni raita on
    samaan aikaan aktiivinen; kaiutinraadalle valitaan kohta, jossa juuri
    se raita on aktiivisempi kuin muut. Puutteellisen aineiston tapauksessa
    otetaan paras saatavilla oleva hetki (fallback keskelle).
    """
    import numpy

    spans: dict = {"all_seconds": all_seconds, "speaker_seconds": speaker_seconds}
    reference_envelope = envelopes[reference_path]
    ref_len = len(reference_envelope)
    if ref_len == 0:
        spans["all"] = 0.0
        spans["per_speaker"] = {}
        return spans

    masks = {}
    durations = {}
    for path, envelope in envelopes.items():
        masks[path] = numpy.asarray(_activity_mask(numpy.asarray(envelope)), dtype=numpy.float64)
        durations[path] = len(envelope) * hop_seconds

    def aligned_mask(path: str, shift: float) -> object:
        """Raidan aktiviteettimaski viiteajan ruudukossa (raita + shift = viiteaika)."""
        ref = masks[path]
        offset = int(round(shift / hop_seconds))
        aligned = numpy.zeros(ref_len, dtype=numpy.float64)
        if offset >= 0:
            src_end = min(len(ref), ref_len - offset)
            aligned[offset:offset + src_end] = ref[:src_end]
        else:
            src_start = -offset
            take = min(ref_len, len(ref) - src_start)
            if take > 0:
                aligned[:take] = ref[src_start:src_start + take]
        return aligned

    ref_mask = masks[reference_path]
    shifted = {t["path"]: aligned_mask(t["path"], t["shift_seconds"]) for t in tracks}

    all_width = max(1, int(round(all_seconds / hop_seconds)))
    spk_width = max(1, int(round(speaker_seconds / hop_seconds)))

    # Yhteinen hetki: vain kohdat joissa kaikki raadat ovat läsnä (maski > 0),
    # ja niistä ikkuna jolla suurin samaan-aikainen aktiivisuus.
    presence = numpy.minimum.reduce([ref_mask > 0, *[(m > 0) for m in shifted.values()]]) if shifted else ref_mask > 0
    if not presence.any():
        center = max(0.0, (ref_len * hop_seconds - all_seconds) / 2)
        spans["all"] = center
        spans["per_speaker"] = {t["path"]: center for t in tracks}
        return spans

    stacked = numpy.minimum.reduce([ref_mask, *shifted.values()])
    cum = numpy.cumsum(stacked)
    _, start = _best_window(cum, ref_len, all_width)
    spans["all"] = start * hop_seconds

    per_speaker = {}
    other_sum = ref_mask
    for path, mask in shifted.items():
        own = mask
        others = other_sum + sum(m for p, m in shifted.items() if p != path)
        # Pieni ylipaino omalle aktiivisuudelle: tasatilanteessa valitaan
        # kohta, jossa raita edes puhuu, ei täysi hiljaisuus.
        score = own * 1.01 - numpy.minimum(others, 1.0)
        cum = numpy.cumsum(score)
        _, start = _best_window(cum, ref_len, spk_width)
        per_speaker[path] = start * hop_seconds
    spans["per_speaker"] = per_speaker
    return spans


def render_preview_clip(
    paths: list,
    reference_path: str,
    shifts: dict,
    start_seconds: float,
    duration_seconds: float,
    output_path: str,
    *,
    runner=None,
) -> str:
    """Rendaa yhden esikatselupätkän: kaikki raadat samaan videoon viiteaikana.

    ``shifts`` on polku -> sekuntiviive (viiteaika = raidan aika + viive).
    Jokainen raita leikataan kohdasta start - shift; negatiivinen loppuosa
    (raita alkaa myöhemmin) peitetään ffmpeg:n adelay/alla olevala -it -offsetilla.
    """
    import subprocess
    import tempfile

    if runner is None:
        def runner(cmd, **kw):
            return subprocess.run(cmd, check=True, capture_output=True, **kw)

    ordered = [reference_path, *[p for p in paths if p != reference_path]]
    inputs = []
    filters = []
    mix_inputs = []
    vid_labels = []
    for i, path in enumerate(ordered):
        shift = float(shifts.get(path, 0.0))
        seek = max(0.0, start_seconds - shift)
        delay_ms = int(round(max(0.0, shift - start_seconds) * 1000))
        inputs += ["-ss", f"{seek:.3f}", "-t", f"{duration_seconds:.3f}", "-i", path]
        filters.append(f"[{i}:a]aresample=48000,adelay={delay_ms}:all=1[a{i}]")
        mix_inputs.append(f"[a{i}]")
        try:
            has_video = bool(probe.info(path).get("video"))
        except Exception:
            has_video = False
        if has_video:
            filters.append(f"[{i}:v]scale=320:-2[v{i}]")
        else:
            # Pelkkä ääniraita: piirrä tumma ruutu, jotta pinotussa kuvassa
            # jokainen raita näkyy omassa sarakkeessaan.
            filters.append(
                f"color=c=0x202020:s=320x240:d={duration_seconds:.3f}[v{i}]"
            )
        vid_labels.append(f"[v{i}]")
    n = len(mix_inputs)
    filters.append(f"{''.join(mix_inputs)}amix=inputs={n}:normalize=0,alimiter[aout]")
    filters.append(f"{''.join(vid_labels)}hstack=inputs={n}[vout]")

    cmd = [
        "ffmpeg", "-y", *inputs,
        "-filter_complex", ";".join(filters),
        "-map", "[vout]", "-map", "[aout]",
        "-t", f"{duration_seconds:.3f}",
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-movflags", "+faststart",
        output_path,
    ]
    try:
        runner(cmd)
    except Exception:
        # Laatikossa/libx264-puutteessa putoa mpeg4:ään; esikatselulle riittää.
        fallback = [c if c != "libx264" else "mpeg4" for c in cmd]
        runner(fallback)
    return output_path


def preview_cache_key(paths: list, shifts: dict, kind: str, target: str, start: float, duration: float) -> str:
    """Vakaa avain esikatseluvälimuistiin parametreista."""
    import hashlib
    import json
    payload = json.dumps(
        {"paths": sorted(paths), "shifts": {k: round(float(v), 3) for k, v in sorted(shifts.items())},
         "kind": kind, "target": target, "start": round(start, 2), "duration": round(duration, 2)},
        sort_keys=True,
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()
