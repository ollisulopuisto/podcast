import os
import mlx.core as mx
import numpy as np
import soundfile as sf
from .processor import Processor

class Track:
    def __init__(self, name: str, path: str, track_type: str = "speech", start_sec: float = 0.0, pan: float = 0.0):
        self.name = name
        self.path = path
        self.type = track_type
        self.start_sec = start_sec
        self.pan = pan
        self.signal = None
        self.sr = None
        
    def load(self, target_sr=48000):
        if not os.path.exists(self.path):
            raise FileNotFoundError(f"Track file not found: {self.path}")
            
        data, sr = sf.read(self.path)
        if sr != target_sr:
            # Note: For production, we should resample here!
            # For now, let's just use it and warn.
            print(f"Warning: {self.name} has SR {sr}, expected {target_sr}")
            
        self.sr = sr
        # Mono mix
        if len(data.shape) > 1:
            data = data.mean(axis=1)
            
        self.signal = mx.array(data)
        return self.signal

import os # Need to import os in the file
