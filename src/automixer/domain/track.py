import os
import mlx.core as mx
import numpy as np
import soundfile as sf
from .processor import Processor

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
        self.processors: List[Processor] = []
        self.loudness = None # Integrated LUFS
        
    def add_processor(self, processor: Processor):
        self.processors.append(processor)

    def process(self, sr: int) -> mx.array:
        if self.signal is None:
            return None
            
        for p in self.processors:
            self.signal = p.process(self.signal, sr)
        return self.signal

    def load(self, target_sr=48000):
        if not os.path.exists(self.path):
            raise FileNotFoundError(f"Track file not found: {self.path}")
            
        data, sr = sf.read(self.path)
        # Mix to mono for processing
        if len(data.shape) > 1:
            data_mono = data.mean(axis=1)
        else:
            data_mono = data
            
        # Analysis
        meter = pyln.Meter(sr)
        self.loudness = meter.integrated_loudness(data_mono)
        
        self.sr = sr
        self.signal = mx.array(data_mono)
        return self.signal

import os # Need to import os in the file
