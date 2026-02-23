from typing import List
import mlx.core as mx
from .track import Track
from .processor import Processor

class Bus:
    def __init__(self, name: str):
        self.name = name
        self.tracks: List[Track] = []
        self.processors: List[Processor] = []
        
    def add_track(self, track: Track):
        self.tracks.append(track)
        
    def add_processor(self, processor: Processor):
        self.processors.append(processor)
        
    def process(self, sr: int, ad_spot: float = 0.0, ad_duration: float = 30.0, progress_callback=None) -> mx.array:
        # 1. Sum tracks with offsets and panning
        if not self.tracks:
            return mx.zeros((1, 2))
            
        # 1a. Identify total duration (with ad)
        max_len = 0
        for t in self.tracks:
            if t.signal is not None:
                offset_samples = int(t.start_sec * sr)
                orig_len = t.signal.shape[0]
                
                if ad_spot > 0 and t.type == "speech" and (offset_samples + orig_len) > (ad_spot * sr):
                    total_len = offset_samples + orig_len + int(ad_duration * sr)
                else:
                    total_len = offset_samples + orig_len
                    
                if total_len > max_len:
                    max_len = total_len
        
        # Now we produce a STEREO signal: [length, 2]
        sum_signal = mx.zeros((max_len, 2))
        
        for i, t in enumerate(self.tracks):
            if progress_callback:
                progress_callback(0.1 + 0.4 * (i / len(self.tracks)), f"Processing track {t.name}...")
                
            if t.signal is not None:
                # 1b. Per-track processing (e.g. individual compression)
                sig = t.process(sr) # This applies track-level processors
                
                offset = int(t.start_sec * sr)
                
                pan = getattr(t, 'pan', 0.0)
                left_gain = mx.sqrt(mx.array(0.5 * (1.0 - pan)))
                right_gain = mx.sqrt(mx.array(0.5 * (1.0 + pan)))
                sig_stereo = mx.stack([sig * left_gain, sig * right_gain], axis=-1)
                
                if ad_spot > 0 and t.type == "speech" and (offset + sig.shape[0]) > (ad_spot * sr):
                    ad_spot_samples = int(ad_spot * sr)
                    part1_len = ad_spot_samples - offset
                    if part1_len > 0:
                        part1 = sig_stereo[:part1_len]
                        padded_part1 = mx.pad(part1, [(offset, max_len - (offset + part1.shape[0])), (0, 0)])
                        sum_signal += padded_part1
                    
                    part2 = sig_stereo[part1_len:]
                    if part2.shape[0] > 0:
                        part2_offset = ad_spot_samples + int(ad_duration * sr)
                        padded_part2 = mx.pad(part2, [(part2_offset, max_len - (part2_offset + part2.shape[0])), (0, 0)])
                        sum_signal += padded_part2
                else:
                    padded_sig = mx.pad(sig_stereo, [(offset, max_len - (offset + sig_stereo.shape[0])), (0, 0)])
                    sum_signal += padded_sig
                
        # 2. Run processors
        total_procs = len(self.processors)
        for i, p in enumerate(self.processors):
            def p_cb(p_val):
                if progress_callback:
                    # Map processor internal progress (0-1) to bus progress (0.5-1.0)
                    bus_p = 0.5 + 0.5 * ((i + p_val) / total_procs)
                    progress_callback(bus_p, f"Running {p.__class__.__name__} on {self.name} bus...")

            sum_signal = p.process(sum_signal, sr, progress_callback=p_cb if total_procs > 0 else None)
            
        return sum_signal
