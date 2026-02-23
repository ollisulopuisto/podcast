import os
import yaml
import sys
import soundfile as sf
import mlx.core as mx
import numpy as np
import pyloudnorm as pyln
from src.automixer.domain.track import Track
from src.automixer.domain.bus import Bus
from src.automixer.domain.processor import (
    DuckingProcessor, GainProcessor, HighPassProcessor, CompressorProcessor
)

class Mixer:
    def __init__(self, config):
        if isinstance(config, str):
            with open(config, "r") as f:
                self.config = yaml.safe_load(f)
        else:
            self.config = config
        self.sr = 48000
        
    def _create_processor(self, p_cfg):
        p_type = p_cfg["type"]
        if p_type == "highpass":
            return HighPassProcessor(cut_freq=p_cfg.get("freq", 100))
        elif p_type == "compressor":
            return CompressorProcessor(threshold_db=p_cfg.get("threshold", -20), ratio=p_cfg.get("ratio", 4.0))
        elif p_type == "gain":
            return GainProcessor(gain_db=p_cfg.get("db", 0.0))
        return None

    def run(self):
        project = self.config.get("project", "My Podcast")
        print(f"Mixing {project}...")
        
        speech_bus = Bus("speech")
        music_bus = Bus("music")
        
        # Add bus processors
        buses_cfg = self.config.get("buses", {})
        for bus_name, bus_cfg in buses_cfg.items():
            bus = speech_bus if bus_name == "speech" else (music_bus if bus_name == "music" else None)
            if bus:
                for p_cfg in bus_cfg.get("processors", []):
                    proc = self._create_processor(p_cfg)
                    if proc:
                        bus.add_processor(proc)
        
        # Load tracks
        for t_cfg in self.config.get("tracks", []):
            t = Track(t_cfg["name"], t_cfg["path"], t_cfg["type"])
            t.load(self.sr)
            if t.type == "speech":
                speech_bus.add_track(t)
            elif t.type == "music":
                music_bus.add_track(t)
        
        # 1. Process buses
        print("Processing buses...")
        ad_spot = self.config.get("ad_spot", 0.0)
        ad_duration = self.config.get("ad_duration", 30.0)
        
        speech_sig = speech_bus.process(self.sr, ad_spot=ad_spot, ad_duration=ad_duration)
        music_sig = music_bus.process(self.sr) # Music doesn't shift by default
        
        # 2. Apply auto-ducking to music bus
        print("Applying auto-ducking to music...")
        ducker = DuckingProcessor(trigger_signal=speech_sig, threshold_db=-30, ratio=8.0)
        music_sig = ducker.process(music_sig, self.sr)
        
        # 3. Sum final mix
        print("Summing master...")
        max_len = max(speech_sig.shape[0], music_sig.shape[0])
        speech_sig = mx.pad(speech_sig, [(0, max_len - speech_sig.shape[0])])
        music_sig = mx.pad(music_sig, [(0, max_len - music_sig.shape[0])])
        
        final_mix_mx = speech_sig + (music_sig * 0.4)
        
        # 4. LUFS Normalization
        final_mix_np = np.array(final_mix_mx)
        target_lufs = self.config.get("target_lufs", -16.0)
        print(f"Normalizing to {target_lufs} LUFS...")
        
        meter = pyln.Meter(self.sr)
        loudness = meter.integrated_loudness(final_mix_np)
        normalized_mix = pyln.normalize.loudness(final_mix_np, loudness, target_lufs)
        
        # Final Peak Check
        peak = np.max(np.abs(normalized_mix))
        if peak > 0.99:
            print(f"Warning: Clipping detected (peak: {peak:.2f}). Reducing gain.")
            normalized_mix /= (peak + 0.01)
            
        output_path = self.config.get("output_path", "final_mix.wav")
        sf.write(output_path, normalized_mix, self.sr, subtype='PCM_24')
        print(f"Done! Saved to {output_path}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m src.automixer.cli_mix <config_file>")
        sys.exit(1)
    
    mixer = Mixer(sys.argv[1])
    mixer.run()
