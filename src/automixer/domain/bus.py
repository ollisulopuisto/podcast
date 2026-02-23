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
        
    def process(self, sr: int, ad_spot: float = 0.0, ad_duration: float = 30.0) -> mx.array:
        # 1. Sum tracks with offsets
        if not self.tracks:
            return mx.zeros((1,))
            
        # Ad insertion: If any speech track is longer than ad_spot, split it
        # Note: This is a bit complex for a simple bus. Let's do it simple:
        # Each track after ad_spot gets shifted.
        
        # 1a. Identify total duration (with ad)
        max_len = 0
        for t in self.tracks:
            if t.signal is not None:
                offset_samples = int(t.start_sec * sr)
                orig_len = t.signal.shape[0]
                
                # Simple logic: If we have an ad spot, 
                # we'll create a gap.
                if ad_spot > 0 and t.type == "speech" and (offset_samples + orig_len) > (ad_spot * sr):
                    # For a single host file:
                    # [part1] [30s gap] [part2]
                    total_len = offset_samples + orig_len + int(ad_duration * sr)
                else:
                    total_len = offset_samples + orig_len
                    
                if total_len > max_len:
                    max_len = total_len
        
        sum_signal = mx.zeros((max_len,))
        
        for t in self.tracks:
            if t.signal is not None:
                offset = int(t.start_sec * sr)
                sig = t.signal
                
                # Split speech at ad spot
                if ad_spot > 0 and t.type == "speech" and (offset + sig.shape[0]) > (ad_spot * sr):
                    ad_spot_samples = int(ad_spot * sr)
                    # Part before ad
                    part1_len = ad_spot_samples - offset
                    if part1_len > 0:
                        part1 = sig[:part1_len]
                        padded_part1 = mx.pad(part1, [(offset, max_len - (offset + part1.shape[0]))])
                        sum_signal += padded_part1
                    
                    # Part after ad
                    part2 = sig[part1_len:]
                    if part2.shape[0] > 0:
                        part2_offset = ad_spot_samples + int(ad_duration * sr)
                        padded_part2 = mx.pad(part2, [(part2_offset, max_len - (part2_offset + part2.shape[0]))])
                        sum_signal += padded_part2
                else:
                    padded_sig = mx.pad(sig, [(offset, max_len - (offset + sig.shape[0]))])
                    sum_signal += padded_sig
                
        # 2. Run processors
        for p in self.processors:
            sum_signal = p.process(sum_signal, sr)
            
        return sum_signal
