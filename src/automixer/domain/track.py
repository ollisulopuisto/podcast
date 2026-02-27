import os
import mlx.core as mx
import numpy as np
import soundfile as sf
import hashlib
import json
from pathlib import Path
from typing import List, Optional
import pyloudnorm as pyln

CACHE_DIR = Path(".automixer/cache")

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
        
    def _get_file_hash(self) -> str:
        """Computes a hash of the file based on path, size and mtime."""
        stat = os.stat(self.path)
        # Combine path, size, and mtime for a fast "is this the same file" check
        hasher = hashlib.sha256()
        hasher.update(f"{self.path}|{stat.st_size}|{stat.st_mtime}".encode())
        return hasher.hexdigest()

    def _get_cache_path(self) -> Path:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        return CACHE_DIR / f"{self._get_file_hash()}.json"

    def _load_cache(self) -> bool:
        cache_path = self._get_cache_path()
        if cache_path.exists():
            try:
                with open(cache_path, "r") as f:
                    data = json.load(f)
                    self.loudness = data.get("loudness")
                    return True
            except Exception:
                pass
        return False

    def _save_cache(self):
        cache_path = self._get_cache_path()
        try:
            with open(cache_path, "w") as f:
                json.dump({"loudness": self.loudness}, f)
        except Exception:
            pass

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
            
        # Try loading metadata from cache first if we are doing a full load
        is_full_load = (duration < 0)
        if is_full_load:
            self._load_cache()

        # Segment loading
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
        if is_full_load and self.loudness is None:
            meter = pyln.Meter(sr)
            self.loudness = meter.integrated_loudness(data_mono)
            self._save_cache()
        
        self.sr = sr
        self.signal = mx.array(data_mono.astype(np.float32))
        return self.signal
