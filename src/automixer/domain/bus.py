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
        
    def process(self, sr: int) -> mx.array:
        # 1. Sum tracks with offsets
        if not self.tracks:
            return mx.zeros((1,))
            
        # Compute total duration
        max_len = 0
        for t in self.tracks:
            if t.signal is not None:
                offset_samples = int(t.start_sec * sr)
                total_len = offset_samples + t.signal.shape[0]
                if total_len > max_len:
                    max_len = total_len
        
        sum_signal = mx.zeros((max_len,))
        
        for t in self.tracks:
            if t.signal is not None:
                offset = int(t.start_sec * sr)
                # Pad to max_len
                # In MLX, we can't just do `sum_signal[offset:offset+len] += sig` 
                # because arrays are immutable.
                # We need to construct the full signal.
                
                # Construct an array of zeros, pad t.signal to match, and sum.
                # Actually, a more efficient way to "scatter" in MLX:
                # We'll just pad the front and back of each track to match max_len.
                padded_sig = mx.pad(t.signal, [(offset, max_len - (offset + t.signal.shape[0]))])
                sum_signal += padded_sig
                
        # 2. Run processors
        for p in self.processors:
            sum_signal = p.process(sum_signal, sr)
            
        return sum_signal
