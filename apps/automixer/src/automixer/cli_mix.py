"""
Command-line interface and core mixing logic for Automixer.

This module provides the `Mixer` class which orchestrates the loading,
processing, routing, and exporting of audio tracks. It also includes a
command-line entry point for executing mixes from the terminal.
"""

import argparse
import glob
import os
import time
from concurrent.futures import ThreadPoolExecutor

import mlx.core as mx
import numpy as np
import psutil
import pyloudnorm as pyln
import soundfile as sf
import yaml

from automixer.domain.bus import Bus
from automixer.domain.processor import (
    CompressorProcessor,
    DeSmackProcessor,
    DuckingProcessor,
    ExternalPluginProcessor,
    GainProcessor,
    HighPassProcessor,
    LimiterProcessor,
    MultibandCompressorProcessor,
    SpectralCarverProcessor,
)
from automixer.domain.track import Track


class Mixer:
    """
    Core mixing engine that processes and combines audio tracks based on a configuration.

    Attributes:
        config (dict): The configuration dictionary detailing tracks, buses, and settings.
        sr (int): The target sample rate (defaults to 48000).
    """

    def __init__(self, config):
        """
        Initializes the Mixer.

        Args:
            config (dict or str): Either a parsed dictionary or a path to a YAML configuration file.
        """
        if isinstance(config, str):
            with open(config, "r") as f:
                self.config = yaml.safe_load(f)
        else:
            self.config = config
        self.sr = 48000

    def log_perf(self, msg):
        """
        Logs a performance message with current memory usage and timestamp.

        Args:
            msg (str): The message to log.
        """
        mem = psutil.Process().memory_info().rss / (1024 * 1024)
        timestamp = time.strftime("%H:%M:%S")
        print(f"[{timestamp}] [MEM: {mem:.0f}MB] {msg}")

    def _create_processor(self, p_cfg):
        """
        Creates a processor instance based on configuration dictionary.

        Args:
            p_cfg (dict): The processor configuration dictionary.

        Returns:
            Processor: An instance of a Processor subclass, or None if unknown type.
        """
        p_type = p_cfg["type"]
        if p_type == "highpass":
            return HighPassProcessor(cut_freq=p_cfg.get("freq", 100))
        if p_type == "compressor":
            return CompressorProcessor(
                threshold_db=p_cfg.get("threshold", -20),
                ratio=p_cfg.get("ratio", 4.0),
                window_sec=p_cfg.get("window", 0.1),
            )
        if p_type == "gain":
            return GainProcessor(gain_db=p_cfg.get("db", 0.0))
        if p_type == "plugin":
            return ExternalPluginProcessor(
                plugin_path=p_cfg["path"], parameters=p_cfg.get("params", {})
            )
        return None

    def run(self, progress_callback=None, preview_start=None, preview_duration=None):
        """
        Executes the mixing process.

        Can run in full mix mode (exporting a file) or preview mode (returning an array).

        Args:
            progress_callback (callable, optional): Callback for progress updates.
            preview_start (float, optional): Start time for a preview segment.
            preview_duration (float, optional): Duration for a preview segment.

        Returns:
            np.ndarray or None: Returns the final mix array in preview mode, None in full mode.
        """

        def update_progress(val, msg):
            self.log_perf(msg)
            if progress_callback:
                progress_callback(val, msg)

        start_time = time.time()
        is_preview = preview_start is not None

        project = self.config.get("project", "My Podcast")
        mode_str = f"PREVIEW @ {preview_start}s" if is_preview else "FULL MIX"
        update_progress(5, f"🚀 STARTING {mode_str}: {project}")

        speech_bus = Bus("speech")
        music_bus = Bus("music")

        # 1. Parallel Track Loading
        # If previewing, we only load the segment.
        tracks_to_load = []
        for t_cfg in self.config.get("tracks", []):
            t = Track(t_cfg["name"], t_cfg["path"], t_cfg["type"])
            tracks_to_load.append(t)

        update_progress(10, f"Loading and profiling {len(tracks_to_load)} tracks...")

        # We need full loudness even for preview?
        # Actually, for auto-gain to work correctly in preview,
        # we ideally need the full track's LUFS.
        # But that's slow. Let's assume the UI might provide it, or we do a quick scan.
        # For now, let's scan the segment and hope it's representative,
        # OR we could have a pre-analysis step.
        # Let's do: if full loudness not in config, do a full load once and cache?
        # For now, just load the segment and use local loudness for the preview.

        load_start = preview_start if is_preview else 0.0
        load_dur = preview_duration if is_preview else -1.0

        # Reading the files parallelises -- it is disk and a loudness
        # measurement.  Building the mlx signal does not: mlx's default
        # stream is thread-local, and an array made on a worker raises
        # `There is no Stream(gpu, 3) in current thread` the first time the
        # mix touches it.  So the pool reads, and this thread converts.
        with ThreadPoolExecutor() as executor:
            list(
                executor.map(
                    lambda t: t.read(start_time=load_start, duration=load_dur),
                    tracks_to_load,
                )
            )
        for t in tracks_to_load:
            t.to_mlx()

        speech_track_list = []
        for t in tracks_to_load:
            if t.type == "speech":
                speech_track_list.append(t)
                speech_bus.add_track(t)
                update_progress(
                    15,
                    f"  - SPEECH '{t.name}': {t.loudness if t.loudness else 0:.2f} LUFS",
                )
            elif t.type == "music":
                music_bus.add_track(t)
                update_progress(
                    15,
                    f"  - MUSIC '{t.name}': {t.loudness if t.loudness else 0:.2f} LUFS",
                )

        # 2. Channel Strip Config
        update_progress(20, "Auto-configuring dynamics...")
        reference_lufs = -23.0
        buses_cfg = self.config.get("buses", {})
        speech_cfg = buses_cfg.get("speech", {})

        for t in speech_track_list:
            # Use 0 if loudness is unknown
            l_val = t.loudness if t.loudness is not None else reference_lufs

            # 2a. Pre-processing: De-Smacker (Option 1: Spectral Interpolation style)
            if speech_cfg.get("desmack_enabled", True):
                sensitivity = float(speech_cfg.get("desmack_sensitivity", 0.5))
                t.add_processor(DeSmackProcessor(sensitivity=sensitivity))

            # 2b. External Plugins next
            for p_cfg in speech_cfg.get("processors", []):
                if p_cfg["type"] == "plugin":
                    t.add_processor(self._create_processor(p_cfg))

            if speech_cfg.get("hp_enabled", True):
                t.add_processor(HighPassProcessor(cut_freq=80))

            if speech_cfg.get("multiband_enabled", False):
                t.add_processor(
                    MultibandCompressorProcessor(
                        peak_enabled=speech_cfg.get("peak_enabled", True),
                        lev_enabled=speech_cfg.get("lev_enabled", True),
                    )
                )
            else:
                gain_offset = reference_lufs - l_val
                t.add_processor(GainProcessor(gain_db=gain_offset))
                if speech_cfg.get("peak_enabled", True):
                    t.add_processor(
                        CompressorProcessor(
                            threshold_db=-15, ratio=2.5, window_sec=0.03
                        )
                    )
                if speech_cfg.get("lev_enabled", True):
                    t.add_processor(
                        CompressorProcessor(threshold_db=-26, ratio=1.5, window_sec=0.3)
                    )

        for t in music_bus.tracks:
            l_val = t.loudness if t.loudness is not None else -30.0
            t.add_processor(GainProcessor(gain_db=-30.0 - l_val))
            music_cfg = buses_cfg.get("music", {})
            for p_cfg in music_cfg.get("processors", []):
                if p_cfg["type"] == "plugin":
                    t.add_processor(self._create_processor(p_cfg))

        # 3. Spatial
        update_progress(30, "Applying spatial separation...")
        if len(speech_track_list) > 1:
            pan_range = 0.2
            step = pan_range / (len(speech_track_list) - 1)
            for i, t in enumerate(speech_track_list):
                t.pan = -(pan_range / 2) + (i * step)

        # 4. Bus Processing
        # Ad spot logic needs to be aware of the preview window
        ad_spot = self.config.get("ad_spot", 0.0)
        ad_duration = self.config.get("ad_duration", 30.0)

        # Adjust ad_spot for preview
        # If we are previewing at 40m, and the ad is at 41m, it's not in the window.
        # If the ad is at 39m, and we preview at 40m, the audio we loaded is ALREADY the post-ad part.
        # This is complex. For preview simplicity, let's disable ad shifting logic
        # unless the ad spot falls INSIDE the preview window.

        effective_ad_spot = 0.0
        if is_preview:
            if ad_spot >= load_start and ad_spot < (load_start + load_dur):
                effective_ad_spot = ad_spot - load_start
        else:
            effective_ad_spot = ad_spot

        def process_bus_parallel(bus, a_spot, a_dur, msg_prefix):
            def p_cb(val, msg):
                # Map 0-1 to a segment of the overall progress
                # Speech bus is 40-55, Music bus is 55-65
                start_p = 40 if msg_prefix == "Speech" else 55
                end_p = 55 if msg_prefix == "Speech" else 65
                overall_p = start_p + val * (end_p - start_p)
                update_progress(overall_p, f"{msg_prefix}: {msg}")

            return bus.process(
                self.sr, ad_spot=a_spot, ad_duration=a_dur, progress_callback=p_cb
            )

        update_progress(40, "Engine: Running Speech Bus...")
        speech_sig = process_bus_parallel(
            speech_bus, effective_ad_spot, ad_duration, "Speech"
        )

        update_progress(55, "Engine: Running Music Bus...")
        music_sig = process_bus_parallel(music_bus, 0, 0, "Music")

        # 5. Dynamic sidechain
        update_progress(65, "Engine: Dynamic sidechaining...")
        speech_mono_trigger = mx.mean(speech_sig, axis=-1)

        if buses_cfg.get("music", {}).get("carve_enabled", True):
            strength = buses_cfg.get("music", {}).get("carve_strength", 0.5)
            carver = SpectralCarverProcessor(
                trigger_signal=speech_mono_trigger, strength=strength
            )
            music_sig = carver.process(music_sig, self.sr)

        duck_cfg = buses_cfg.get("music", {})
        if duck_cfg.get("duck_enabled", True):
            thresh = duck_cfg.get("duck_threshold", -30)
            ducker = DuckingProcessor(
                trigger_signal=speech_mono_trigger, threshold_db=thresh, ratio=8.0
            )
            music_sig = ducker.process(music_sig, self.sr)

        # 6. Master Sum & Normalize
        update_progress(80, "Summing master...")
        max_len = max(speech_sig.shape[0], music_sig.shape[0])
        speech_sig = mx.pad(speech_sig, [(0, max_len - speech_sig.shape[0]), (0, 0)])
        music_sig = mx.pad(music_sig, [(0, max_len - music_sig.shape[0]), (0, 0)])

        final_mix_mx = speech_sig + music_sig

        update_progress(85, "Normalizing to target LUFS...")
        final_mix_np = np.array(final_mix_mx)
        meter = pyln.Meter(self.sr)
        try:
            current_loudness = meter.integrated_loudness(final_mix_np)
        except Exception:
            current_loudness = -23.0  # Fallback

        target_lufs = self.config.get("target_lufs", -16.0)
        makeup_gain_db = target_lufs - current_loudness
        final_mix_mx = final_mix_mx * (10 ** (makeup_gain_db / 20))

        limiter = LimiterProcessor(threshold_db=-1.0)
        master_output = limiter.process(final_mix_mx, self.sr)

        master_np = np.array(master_output)

        if not is_preview:
            update_progress(95, "Exporting 24-bit WAV...")
            output_path = self.config.get("output_path", "final_mix.wav")
            sf.write(output_path, master_np, self.sr, subtype="PCM_24")
            elapsed = time.time() - start_time
            update_progress(100, f"✅ FINISHED in {elapsed / 60:.1f}m: {output_path}")
            return None
        update_progress(100, "✅ Preview Render Ready")
        return master_np


def detect_tracks(paths):
    """
    Attempts to guess track types based on filenames.

    Args:
        paths (list[str]): List of file paths.

    Returns:
        list[dict]: List of configuration dictionaries for each track.
    """
    music_keywords = [
        "MUSIC",
        "THEME",
        "TUNNARI",
        "MUSA",
        "MUSIIKKI",
        "TUNNUS",
        "JINGLE",
    ]
    tracks = []
    for path in paths:
        name = os.path.basename(path).upper()
        is_music = any(kw in name for kw in music_keywords)
        track_type = "music" if is_music else "speech"
        tracks.append(
            {"name": os.path.basename(path), "path": path, "type": track_type}
        )
    return tracks


def main():
    """
    Main entry point for the Automixer CLI.

    Parses arguments, configures the Mixer instance, and runs the mix process.
    """
    parser = argparse.ArgumentParser(description="Automixer CLI")
    parser.add_argument(
        "tracks",
        nargs="*",
        help="Audio files to mix (will be auto-detected if --speech/--music not used)",
    )
    parser.add_argument("--speech", nargs="+", help="Explicitly specify speech tracks")
    parser.add_argument("--music", nargs="+", help="Explicitly specify music tracks")
    parser.add_argument(
        "--output", "-o", default="final_mix.wav", help="Output filename"
    )
    parser.add_argument(
        "--target-lufs", type=float, default=-16.0, help="Target loudness (LUFS)"
    )
    parser.add_argument(
        "--ad-spot", type=float, default=0.0, help="Ad spot time (seconds)"
    )
    parser.add_argument(
        "--ad-duration", type=float, default=30.0, help="Ad duration (seconds)"
    )

    # New options: Speech Bus
    parser.add_argument(
        "--no-speech-hp",
        action="store_false",
        dest="speech_hp",
        help="Disable High-Pass (80Hz) on speech",
    )
    parser.add_argument(
        "--no-speech-peak",
        action="store_false",
        dest="speech_peak",
        help="Disable Peak Tamer on speech",
    )
    parser.add_argument(
        "--no-speech-lev",
        action="store_false",
        dest="speech_lev",
        help="Disable Leveler on speech",
    )
    parser.add_argument(
        "--speech-multiband",
        action="store_true",
        help="Enable Multiband Mode on speech",
    )
    parser.add_argument(
        "--no-speech-desmack",
        action="store_false",
        dest="speech_desmack",
        help="Disable De-Smacker on speech",
    )
    parser.add_argument(
        "--speech-desmack-sensitivity",
        type=float,
        default=0.5,
        help="De-Smacker sensitivity (0.0-1.0)",
    )
    parser.set_defaults(
        speech_hp=True, speech_peak=True, speech_lev=True, speech_desmack=True
    )

    # New options: Music Bus
    parser.add_argument(
        "--no-music-carve",
        action="store_false",
        dest="music_carve",
        help="Disable Spectral Carve on music",
    )
    parser.add_argument(
        "--music-carve-strength",
        type=float,
        default=0.5,
        help="Spectral Carve strength (0.0-1.0)",
    )
    parser.add_argument(
        "--no-music-duck",
        action="store_false",
        dest="music_duck",
        help="Disable Auto-Ducking on music",
    )
    parser.add_argument(
        "--music-duck-threshold",
        type=float,
        default=-30.0,
        help="Auto-Ducking threshold (dB)",
    )
    parser.set_defaults(music_carve=True, music_duck=True)

    # New options: Plugins
    parser.add_argument(
        "--speech-plugins", nargs="+", help="Plugin paths for speech tracks"
    )
    parser.add_argument("--music-plugins", nargs="+", help="Plugin paths for music bus")
    parser.add_argument(
        "--plugin-params", help="Plugin parameters (e.g. WavesNS1: threshold=0.5)"
    )

    parser.add_argument(
        "--minimal",
        action="store_true",
        help="Disable all optional processors (HP, Peak, Leveler, De-Smack, Carve, Duck)",
    )

    args = parser.parse_args()

    if args.minimal:
        args.speech_hp = False
        args.speech_peak = False
        args.speech_lev = False
        args.speech_desmack = False
        args.music_carve = False
        args.music_duck = False

    config_tracks = []

    if args.speech:
        for p in args.speech:
            config_tracks.append(
                {"name": os.path.basename(p), "path": p, "type": "speech"}
            )

    if args.music:
        for p in args.music:
            config_tracks.append(
                {"name": os.path.basename(p), "path": p, "type": "music"}
            )

    if not args.speech and not args.music:
        # If no explicit tracks, use positional tracks or all wav files in current dir
        paths = args.tracks
        if not paths:
            paths = glob.glob("*.wav") + glob.glob("*.mp3")

        config_tracks = detect_tracks(paths)

    if not config_tracks:
        print("No tracks found or specified.")
        return

    # Log detected roles
    print("Detected Track Roles:")
    for t in config_tracks:
        icon = "🎤" if t["type"] == "speech" else "🎵"
        print(f"  {icon} {t['type'].upper()}: {t['name']}")

    # Parse plugin parameters
    parsed_params = {}
    if args.plugin_params:
        for part in args.plugin_params.split(";"):
            if ":" in part:
                p_name, p_vals = part.split(":", 1)
                p_name = p_name.strip().lower()
                kv_pairs = {}
                for kv in p_vals.split(","):
                    if "=" in kv:
                        k, v = kv.split("=", 1)
                        try:
                            kv_pairs[k.strip()] = float(v.strip())
                        except Exception:
                            kv_pairs[k.strip()] = v.strip()
                parsed_params[p_name] = kv_pairs

    def build_proc_list(paths):
        if not paths:
            return []
        procs = []
        for p in paths:
            p_n = os.path.basename(p).lower()
            params = {}
            for key, val in parsed_params.items():
                if key in p_n:
                    params = val
                    break
            procs.append({"type": "plugin", "path": p, "params": params})
        return procs

    config = {
        "project": "CLI Mix",
        "target_lufs": args.target_lufs,
        "output_path": args.output,
        "ad_spot": args.ad_spot,
        "ad_duration": args.ad_duration,
        "tracks": config_tracks,
        "buses": {
            "speech": {
                "hp_enabled": args.speech_hp,
                "peak_enabled": args.speech_peak,
                "lev_enabled": args.speech_lev,
                "multiband_enabled": args.speech_multiband,
                "desmack_enabled": args.speech_desmack,
                "desmack_sensitivity": args.speech_desmack_sensitivity,
                "processors": build_proc_list(args.speech_plugins),
            },
            "music": {
                "carve_enabled": args.music_carve,
                "carve_strength": args.music_carve_strength,
                "duck_enabled": args.music_duck,
                "duck_threshold": args.music_duck_threshold,
                "processors": build_proc_list(args.music_plugins),
            },
        },
    }

    mixer = Mixer(config)
    mixer.run()


if __name__ == "__main__":
    main()
