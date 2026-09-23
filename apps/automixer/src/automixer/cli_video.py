"""Fix the sound of one video file without touching the picture.

The audio goes through the shared speech chain (`speechmix.chain.process`) —
restoration plug-in first, then clean-up, levelling and a true-peak ceiling
at the target loudness — and is muxed back next to the **copied** video
stream. The picture is never decoded.

Sync is the part that fails silently. ffmpeg moves each input's start to
zero, and the processed WAV always starts at zero, so an audio track that
began after the picture (camera files often do) would come out early by
exactly that much. The WAV is therefore put back at the source audio's own
offset with ``-itsoffset``.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

from automixer.domain.processor import SpeechSettings
from speechmix import chain, editor

TARGET_LUFS = -16.0
# Same limit as autoraffkat's `MAX_LAG_MS`: a plug-in that misreports its
# latency keeps the length but moves the sound, and 1 ms is already audible
# as lip-sync drift on plosives next to the picture.
MAX_LAG_MS = 1.0
# AAC at this rate is transparent for speech; the source's own bitrate is
# not a ceiling worth keeping once the audio has been re-encoded anyway.
AAC_BITRATE = "256k"


class VideoError(Exception):
    """Something about the file or the run that makes the result untrustworthy."""


def default_output(source: Path, lufs: float = TARGET_LUFS) -> Path:
    source = Path(source)
    return source.with_name(f"{source.stem} [{lufs:g} LUFS]{source.suffix}")


def find_plugin(name: str) -> str:
    """Path of the installed plug-in whose name contains ``name``.

    Not finding it is an error: running the chain without the restoration the
    user asked for would produce a valid, louder, wrong file.
    """
    wanted = name.lower()
    for found in chain.plugins():
        if wanted in found["name"].lower():
            return found["path"]
    raise VideoError(
        f"{name} is not installed (looked in {', '.join(chain.PLUGIN_DIRS)}). "
        "Pass --plugin PATH, or --no-plugin to skip restoration."
    )


def _probe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json",
         str(path)],
        check=True, capture_output=True, text=True,
    ).stdout
    return json.loads(out)


# What describes the picture outside its bitstream. The packets are copied
# byte for byte, but the container carries its own copy of the colour tags,
# the codec tag Apple players key on (hvc1 vs hev1), and records that exist
# only there — Dolby Vision's configuration record among them. A remux that
# drops one plays back as washed-out SDR with no error anywhere.
PICTURE_KEYS = (
    "codec_name", "codec_tag_string", "profile", "pix_fmt", "width", "height",
    "color_range", "color_space", "color_transfer", "color_primaries",
)


def _picture(info: dict) -> dict:
    video = [s for s in info["streams"] if s["codec_type"] == "video"]
    return {
        "streams": len(video),
        **{key: video[0].get(key) for key in PICTURE_KEYS if video},
        "side_data": sorted(
            d.get("side_data_type", "?")
            for d in (video[0].get("side_data_list", []) if video else [])
        ),
    }


def _ffmpeg(*args: str) -> None:
    done = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", *args],
        capture_output=True, text=True,
    )
    if done.returncode:
        raise VideoError(f"ffmpeg failed: {done.stderr.strip()}")


def fix_video(
    source,
    target,
    target_lufs: float = TARGET_LUFS,
    plugin=None,
    log=print,
) -> chain.ChainResult:
    """Process ``source``'s audio and write ``target`` with the video copied.

    ``plugin`` is anything `chain.apply_plugin` accepts, or ``None``.
    Nothing is written to ``target`` unless every check passes.
    """
    source, target = Path(source), Path(target)
    if source.resolve() == target.resolve():
        raise VideoError("Refusing to overwrite the source file.")

    info = _probe(source)
    audio_streams = [s for s in info["streams"] if s["codec_type"] == "audio"]
    if len(audio_streams) != 1:
        raise VideoError(
            f"Expected one audio stream, found {len(audio_streams)} audio streams."
        )
    stream = audio_streams[0]
    offset = float(stream.get("start_time", 0) or 0) - float(
        info["format"].get("start_time", 0) or 0
    )

    with tempfile.TemporaryDirectory(prefix="autovideo-") as work:
        raw = Path(work) / "in.wav"
        _ffmpeg("-i", str(source), "-map", "0:a:0", "-c:a", "pcm_f32le", str(raw))
        audio, rate = sf.read(raw, dtype="float32", always_2d=True)
        audio = np.ascontiguousarray(audio.T)
        log(f"Audio: {audio.shape[0]} ch, {rate} Hz, {audio.shape[1] / rate:.1f} s, "
            f"starts {offset * 1000:+.1f} ms from the file start")

        # Speech is processed as one mono channel and written back as the
        # source's layout. The chain measures the *mean* of its channels,
        # while BS.1770 sums the channels' power: the same speech on both
        # sides of a stereo file measured -13.0 LUFS against a -16 target.
        # Dual mono is therefore aimed 10·log10(channels) dB lower.
        channels = audio.shape[0]
        if channels > 2:
            raise VideoError(f"Only mono or stereo audio is supported, not {channels} channels.")
        mono = audio.mean(axis=0, keepdims=True)
        processed, result = chain.process(
            mono, rate, SpeechSettings(rider=False), gain_db=0.0, speech=True,
            target_lufs=target_lufs - 10 * np.log10(channels), plugin=plugin,
            stage=lambda name, share: log(f"  {name} ({share:.0%})"),
        )
        processed = np.repeat(processed, channels, axis=0)
        if abs(result.lag) > int(rate * MAX_LAG_MS / 1000):
            raise VideoError(
                f"The plug-in shifted the audio by {result.lag} samples "
                f"({result.lag / rate * 1000:.1f} ms); nothing was written."
            )

        fixed = Path(work) / "out.wav"
        sf.write(fixed, processed.T, rate, subtype="FLOAT")

        codec = stream["codec_name"]
        audio_codec = (
            ["-c:a", codec] if codec.startswith("pcm_")
            else ["-c:a", "aac", "-b:a", AAC_BITRATE]
        )
        partial = target.with_name(f".{target.name}.partial{target.suffix}")
        try:
            _ffmpeg(
                "-i", str(source),
                "-itsoffset", f"{offset:.6f}", "-i", str(fixed),
                "-map", "0:v", "-map", "1:a:0",
                "-c:v", "copy", *audio_codec,
                "-map_metadata", "0",
                str(partial),
            )
            after = _picture(_probe(partial))
        except Exception:
            partial.unlink(missing_ok=True)
            raise
        before = _picture(info)
        if before != after:
            partial.unlink()
            lost = sorted(set(before["side_data"]) - set(after["side_data"]))
            changed = [k for k in before if k != "side_data" and before[k] != after[k]]
            raise VideoError(
                "The remux changed the picture's metadata; nothing was written. "
                f"Lost: {', '.join(lost) or '-'}. Changed: {', '.join(changed) or '-'}."
            )
        os.replace(partial, target)

    log(f"Measured {result.measured_lufs:.1f} LUFS (mono), lifted {result.gain_db:+.1f} dB, "
        f"limiter {result.limiter_db:.1f} dB, PSR {result.psr_lu:.1f} LU")
    if not result.reached_target:
        log(f"Warning: did not reach {target_lufs:g} LUFS within the limiter budget.")
    return result


def _params(pairs: list[str]) -> dict:
    params = {}
    for pair in pairs:
        name, _, value = pair.partition("=")
        try:
            params[name] = float(value)
        except ValueError:
            params[name] = value
    return params


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="autovideo",
        description="Restore and level the audio of one video file; the video "
                    "stream is copied, not re-encoded.",
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("-o", "--output", type=Path,
                        help="default: '<name> [<lufs> LUFS].<ext>' next to the source")
    parser.add_argument("--lufs", type=float, default=TARGET_LUFS)
    parser.add_argument("--plugin", default="dxRevive",
                        help="installed plug-in name or a path (default: dxRevive)")
    parser.add_argument("--no-plugin", action="store_true")
    parser.add_argument("--param", action="append", default=[], metavar="NAME=VALUE",
                        help="plug-in parameter in its own units, e.g. mix=60")
    parser.add_argument("--state", type=Path,
                        help="file with the plug-in's saved state (base64); "
                             "dxRevive's model choice lives only here")
    parser.add_argument("--edit", action="store_true",
                        help="open the plug-in window first (pick the model); "
                             "the state is saved to --state if given")
    args = parser.parse_args(argv)

    try:
        plugin = None
        if not args.no_plugin:
            path = args.plugin if os.path.exists(args.plugin) else find_plugin(args.plugin)
            params = _params(args.param)
            state = args.state.read_text().strip() if args.state and args.state.exists() else None
            if args.edit:
                chosen = editor.open_editor(path, params, state)
                state, params = chosen.state or state, {**params, **chosen.params}
                if args.state and state:
                    args.state.write_text(state)
            elif not state:
                print("Note: no --state, so the plug-in runs its default model.")
            plugin = chain.load_pool(path, params, chain.worker_count(), state)
        output = args.output or default_output(args.source, args.lufs)
        try:
            fix_video(args.source, output, args.lufs, plugin)
        finally:
            if plugin is not None:
                plugin.close()
    except (VideoError, chain.ChainError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
