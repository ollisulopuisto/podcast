import os
import yaml
import sys
import soundfile as sf
import mlx.core as mx
import numpy as np
import pyloudnorm as pyln
from src.automixer.domain.track import Track
from src.automixer.domain.bus import Bus
from src.automixer.domain.processor import DuckingProcessor

class Mixer:
    def __init__(self, config_path):
        with open(config_path, "r") as f:
            self.config = yaml.safe_load(f)
        self.sr = 48000
        
    def run(self):
        project = self.config.get("project", "My Podcast")
        print(f"Mixing {project}...")
        
        speech_bus = Bus("speech")
        music_bus = Bus("music")
        
        # Load tracks
        for t_cfg in self.config.get("tracks", []):
            t = Track(t_cfg["name"], t_cfg["path"], t_cfg["type"])
            t.load(self.sr)
            if t.type == "speech":
                speech_bus.add_track(t)
            elif t.type == "music":
                music_bus.add_track(t)
        
        # 1. Process speech bus
        print("Processing speech bus...")
        speech_sig = speech_bus.process(self.sr)
        
        # 2. Process music bus
        print("Processing music bus...")
        music_sig = music_bus.process(self.sr)
        
        # 3. Apply auto-ducking to music bus based on speech
        # We'll add the ducker directly to the music_sig
        print("Applying auto-ducking to music...")
        ducker = DuckingProcessor(trigger_signal=speech_sig, threshold_db=-30, ratio=8.0)
        music_sig = ducker.process(music_sig, self.sr)
        
        # 4. Sum final mix
        print("Summing master...")
        max_len = max(speech_sig.shape[0], music_sig.shape[0])
        speech_sig = mx.pad(speech_sig, [(0, max_len - speech_sig.shape[0])])
        music_sig = mx.pad(music_sig, [(0, max_len - music_sig.shape[0])])
        
        # Combine: speech is 100%, music is background (reduced)
        final_mix_mx = speech_sig + (music_sig * 0.4)
        
        # 5. LUFS Normalization
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
        # Save as 24-bit PCM
        sf.write(output_path, normalized_mix, self.sr, subtype='PCM_24')
        print(f"Done! Saved to {output_path}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m src.automixer.cli_mix <config_file>")
        sys.exit(1)
    
    mixer = Mixer(sys.argv[1])
    mixer.run()
