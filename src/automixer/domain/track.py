import os
import mlx.core as mx
import numpy as np
import soundfile as sf
from typing import List, Optional
import pyloudnorm as pyln

class Track:
    def __init__(self, name: str, path: str, track_type: str = "speech", start_sec: float = 0.0, pan: float = 0.0):
        self.name = name
        self.path = path
        self.type = track_type
        self.start_sec = start_sec
        self.pan = pan
        self.signal = None
        self.sr = None
        from .processor import Processor
        self.processors: List[Processor] = []
        self.loudness = None # Integrated LUFS
        
    def add_processor(self, processor):
        self.processors.append(processor)

    def process(self, sr: int) -> mx.array:
        if self.signal is None:
            return None
            
        for p in self.processors:
            self.signal = p.process(self.signal, sr)
        return self.signal

    def load(self, target_sr=48000, start_time: float = 0.0, duration: float = -1.0):
        if not os.path.exists(self.path):
            raise FileNotFoundError(f"Track file not found: {self.path}")
            
        # Segment loading
        start_frame = int(start_time * 48000) # soundfile will use original SR, we will convert
        # But wait, soundfile uses frames of the original file. 
        # Let's get original SR first.
        info = sf.info(self.path)
        orig_sr = info.samplerate
        
        frames_to_read = -1
        if duration > 0:
            frames_to_read = int(duration * orig_sr)
        
        start_frame_orig = int(start_time * orig_sr)
        
        data, sr = sf.read(self.path, start=start_frame_orig, frames=frames_to_read)
        
        # Mix to mono for processing
        if len(data.shape) > 1:
            data_mono = data.mean(axis=1)
        else:
            data_mono = data
            
        # Analysis (Only if loading full track or if we want local loudness)
        if duration < 0:
            meter = pyln.Meter(sr)
            self.loudness = meter.integrated_loudness(data_mono)
        else:
            # For preview, we might not have pre-calculated loudness. 
            # We'll assume full-track loudness was already calculated if needed.
            pass
        
        self.sr = sr
        self.signal = mx.array(data_mono.astype(np.float32))
        return self.signal
