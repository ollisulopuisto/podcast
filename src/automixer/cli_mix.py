import os
import yaml
import sys
import time
import psutil
import soundfile as sf
import mlx.core as mx
import numpy as np
import pyloudnorm as pyln
from src.automixer.domain.track import Track
from src.automixer.domain.bus import Bus
from src.automixer.domain.processor import (
    DuckingProcessor, GainProcessor, HighPassProcessor, CompressorProcessor, 
    SpectralCarverProcessor, LimiterProcessor, MultibandCompressorProcessor, ExternalPluginProcessor
)

from concurrent.futures import ThreadPoolExecutor

class Mixer:
    def __init__(self, config):
        if isinstance(config, str):
            with open(config, "r") as f:
                self.config = yaml.safe_load(f)
        else:
            self.config = config
        self.sr = 48000
        
    def log_perf(self, msg):
        mem = psutil.Process().memory_info().rss / (1024 * 1024)
        timestamp = time.strftime("%H:%M:%S")
        print(f"[{timestamp}] [MEM: {mem:.0f}MB] {msg}")

    def _create_processor(self, p_cfg):
        p_type = p_cfg["type"]
        if p_type == "highpass":
            return HighPassProcessor(cut_freq=p_cfg.get("freq", 100))
        elif p_type == "compressor":
            return CompressorProcessor(
                threshold_db=p_cfg.get("threshold", -20), 
                ratio=p_cfg.get("ratio", 4.0),
                window_sec=p_cfg.get("window", 0.1)
            )
        elif p_type == "gain":
            return GainProcessor(gain_db=p_cfg.get("db", 0.0))
        elif p_type == "plugin":
            return ExternalPluginProcessor(
                plugin_path=p_cfg["path"],
                parameters=p_cfg.get("params", {})
            )
        return None

    def run(self, progress_callback=None):
        def update_progress(val, msg):
            self.log_perf(msg)
            if progress_callback:
                progress_callback(val, msg)

        start_time = time.time()
        project = self.config.get("project", "My Podcast")
        update_progress(5, f"🚀 STARTING MIX: {project}")
        
        speech_bus = Bus("speech")
        music_bus = Bus("music")
        
        # 1. Parallel Track Loading
        tracks_to_load = []
        for t_cfg in self.config.get("tracks", []):
            t = Track(t_cfg["name"], t_cfg["path"], t_cfg["type"])
            tracks_to_load.append(t)
            
        update_progress(10, f"Loading and profiling {len(tracks_to_load)} tracks...")
        with ThreadPoolExecutor() as executor:
            list(executor.map(lambda t: t.load(self.sr), tracks_to_load))
            
        speech_track_list = []
        for t in tracks_to_load:
            if t.type == "speech":
                speech_track_list.append(t)
                speech_bus.add_track(t)
                update_progress(15, f"  - SPEECH '{t.name}': {t.loudness:.2f} LUFS ({t.signal.shape[0]/self.sr/60:.1f} min)")
            elif t.type == "music":
                music_bus.add_track(t)
                update_progress(15, f"  - MUSIC '{t.name}': {t.loudness:.2f} LUFS")

        # 2. Intelligent Auto-Thresholding & Gain Normalization
        update_progress(20, "Auto-configuring channel strips...")
        reference_lufs = -23.0
        buses_cfg = self.config.get("buses", {})
        speech_cfg = buses_cfg.get("speech", {})
        
        for t in speech_track_list:
            for p_cfg in speech_cfg.get("processors", []):
                if p_cfg["type"] == "plugin":
                    t.add_processor(self._create_processor(p_cfg))

            if speech_cfg.get("hp_enabled", True):
                t.add_processor(HighPassProcessor(cut_freq=80))

            if speech_cfg.get("multiband_enabled", False):
                t.add_processor(MultibandCompressorProcessor(
                    peak_enabled=speech_cfg.get("peak_enabled", True),
                    lev_enabled=speech_cfg.get("lev_enabled", True)
                ))
            else:
                gain_offset = reference_lufs - t.loudness
                t.add_processor(GainProcessor(gain_db=gain_offset))
                if speech_cfg.get("peak_enabled", True):
                    t.add_processor(CompressorProcessor(threshold_db=-15, ratio=2.5, window_sec=0.03))
                if speech_cfg.get("lev_enabled", True):
                    t.add_processor(CompressorProcessor(threshold_db=-26, ratio=1.5, window_sec=0.3))

        for t in music_bus.tracks:
            t.add_processor(GainProcessor(gain_db=-30.0 - t.loudness))
            music_cfg = buses_cfg.get("music", {})
            for p_cfg in music_cfg.get("processors", []):
                if p_cfg["type"] == "plugin":
                    t.add_processor(self._create_processor(p_cfg))

        # 3. Apply delicate panning to speakers
        update_progress(30, "Applying spatial separation...")
        if len(speech_track_list) > 1:
            pan_range = 0.2
            step = pan_range / (len(speech_track_list) - 1)
            for i, t in enumerate(speech_track_list):
                t.pan = - (pan_range / 2) + (i * step)

        # 4. Parallel Bus Processing
        def process_bus_parallel(bus, ad_spot, ad_duration, msg_prefix):
            def proc_track(t):
                self.log_perf(f"[{msg_prefix}] Processing strip: {t.name}...")
                return t.process(self.sr)
            with ThreadPoolExecutor() as bus_executor:
                list(bus_executor.map(proc_track, bus.tracks))
            return bus.process(self.sr, ad_spot=ad_spot, ad_duration=ad_duration)

        update_progress(40, "Engine: Running Speech Bus...")
        speech_sig = process_bus_parallel(speech_bus, self.config.get("ad_spot", 0.0), self.config.get("ad_duration", 30.0), "Speech")
        
        update_progress(55, "Engine: Running Music Bus...")
        music_sig = process_bus_parallel(music_bus, 0, 0, "Music")
        
        # 5. Cross-Bus Dynamic Processing
        update_progress(65, "Engine: Dynamic sidechaining...")
        speech_mono_trigger = mx.mean(speech_sig, axis=-1)
        
        if buses_cfg.get("music", {}).get("carve_enabled", True):
            strength = buses_cfg.get("music", {}).get("carve_strength", 0.5)
            carver = SpectralCarverProcessor(trigger_signal=speech_mono_trigger, strength=strength)
            music_sig = carver.process(music_sig, self.sr, progress_callback=lambda p: update_progress(65 + int(p * 10), "Spectral Carving (GPU)..."))

        duck_cfg = buses_cfg.get("music", {})
        if duck_cfg.get("duck_enabled", True):
            thresh = duck_cfg.get("duck_threshold", -30)
            update_progress(75, "Applying Sidechain Ducking...")
            ducker = DuckingProcessor(trigger_signal=speech_mono_trigger, threshold_db=thresh, ratio=8.0)
            music_sig = ducker.process(music_sig, self.sr)

        # 6. Master Sum & Normalize
        update_progress(80, "Summing master...")
        max_len = max(speech_sig.shape[0], music_sig.shape[0])
        speech_sig = mx.pad(speech_sig, [(0, max_len - speech_sig.shape[0]), (0, 0)])
        music_sig = mx.pad(music_sig, [(0, max_len - music_sig.shape[0]), (0, 0)])
        
        final_mix_mx = speech_sig + music_sig
        
        # Free up memory
        del speech_sig
        del music_sig
        
        update_progress(85, "Normalizing to target LUFS...")
        final_mix_np = np.array(final_mix_mx)
        meter = pyln.Meter(self.sr)
        current_loudness = meter.integrated_loudness(final_mix_np)
        target_lufs = self.config.get("target_lufs", -16.0)
        makeup_gain_db = target_lufs - current_loudness
        
        update_progress(90, f"Limiting to {target_lufs} LUFS...")
        final_mix_mx = final_mix_mx * (10**(makeup_gain_db / 20))
        
        limiter = LimiterProcessor(threshold_db=-1.0)
        master_output = limiter.process(final_mix_mx, self.sr)
        
        update_progress(95, "Exporting 24-bit WAV...")
        output_path = self.config.get("output_path", "final_mix.wav")
        sf.write(output_path, np.array(master_output), self.sr, subtype='PCM_24')
        
        elapsed = time.time() - start_time
        update_progress(100, f"✅ FINISHED in {elapsed/60:.1f}m: {output_path}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m src.automixer.cli_mix <config_file>")
        sys.exit(1)
    
    mixer = Mixer(sys.argv[1])
    mixer.run()
