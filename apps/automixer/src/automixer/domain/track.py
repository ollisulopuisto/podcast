"""
Module representing a track of audio.

A track wraps an audio file, loads its contents (either fully or partially for preview),
applies its track-specific processors, and tracks loudness and caching.
"""

import hashlib
import json
import os
from pathlib import Path
from typing import List

import mlx.core as mx
import numpy as np
import pyloudnorm as pyln
import soundfile as sf

CACHE_DIR = Path(".automixer/cache")


class Track:
    """
    Represents an individual audio track in the mixing session.

    Attributes:
        name (str): The display name of the track.
        path (str): The file path to the audio source.
        type (str): The track role (e.g., "speech", "music").
        start_sec (float): Offset in seconds where the track should start in the mix.
        pan (float): Panning value from -1.0 (left) to 1.0 (right).
        signal (mx.array): The loaded and processed audio signal.
        sr (int): The sample rate of the loaded audio.
        processors (List[Processor]): List of processors applied to this track.
        loudness (float): The measured integrated loudness in LUFS.
    """

    def __init__(
        self,
        name: str,
        path: str,
        track_type: str = "speech",
        start_sec: float = 0.0,
        pan: float = 0.0,
    ):
        """
        Initializes a new Track.

        Args:
            name (str): The track name.
            path (str): The path to the audio file.
            track_type (str, optional): The type/role of the track. Defaults to "speech".
            start_sec (float, optional): Offset time in seconds. Defaults to 0.0.
            pan (float, optional): Panning position. Defaults to 0.0.
        """
        self.name = name
        self.path = path
        self.type = track_type
        self.start_sec = start_sec
        self.pan = pan
        self.signal = None
        self._samples = None
        self.sr = None
        from .processor import Processor

        self.processors: List[Processor] = []
        self.loudness = None  # Integrated LUFS

    def _get_file_hash(self) -> str:
        """
        Computes a hash of the file based on path, size, and modification time.

        Returns:
            str: The computed SHA256 hash.
        """
        stat = os.stat(self.path)
        # Combine path, size, and mtime for a fast "is this the same file" check
        hasher = hashlib.sha256()
        hasher.update(f"{self.path}|{stat.st_size}|{stat.st_mtime}".encode())
        return hasher.hexdigest()

    def _get_cache_path(self) -> Path:
        """
        Gets the path to the cache file for this track.

        Returns:
            Path: The cache file path.
        """
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        return CACHE_DIR / f"{self._get_file_hash()}.json"

    def _load_cache(self) -> bool:
        """
        Attempts to load track metadata (like loudness) from the cache.

        Returns:
            bool: True if cache was successfully loaded, False otherwise.
        """
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
        """
        Saves track metadata (like loudness) to the cache.
        """
        cache_path = self._get_cache_path()
        try:
            with open(cache_path, "w") as f:
                json.dump({"loudness": self.loudness}, f)
        except Exception:
            pass

    def add_processor(self, processor):
        """
        Adds a processor to the track's processing chain.

        Args:
            processor: The processor instance to add.
        """
        self.processors.append(processor)

    def process(self, sr: int) -> mx.array:
        """
        Applies all assigned processors to the track's signal.

        Args:
            sr (int): The sample rate.

        Returns:
            mx.array: The processed audio signal, or None if signal is not loaded.
        """
        if self.signal is None:
            return None

        for p in self.processors:
            self.signal = p.process(self.signal, sr)
        return self.signal

    def read(self, start_time: float = 0.0, duration: float = -1.0):
        """
        Reads the audio data from disk into memory, as numpy samples.

        Safe to run in a thread pool -- it touches no mlx.  Call `to_mlx` on
        the thread that will use the signal afterwards; `load` does both.

        There is no target sample rate, because nothing here resamples.  The
        signature used to take one and ignore it, and the caller passed the
        mixer's rate into it -- which reads as a promise that the file is
        converted, when in fact `self.sr` comes back as whatever the file is.
        A mismatched rate is the silent kind of bug this codebase collects:
        the mix renders, and it renders at the wrong speed.

        Args:
            start_time (float, optional): Time in seconds to start reading. Defaults to 0.0.
            duration (float, optional): Duration in seconds to read. Negative means full track. Defaults to -1.0.

        Returns:
            mx.array: The loaded mono signal array.

        Raises:
            FileNotFoundError: If the track file does not exist.
        """

        if not os.path.exists(self.path):
            raise FileNotFoundError(f"Track file not found: {self.path}")

        # Try loading metadata from cache first if we are doing a full load
        is_full_load = duration < 0
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
        data_mono = data.mean(axis=1) if len(data.shape) > 1 else data

        # Analysis (Only if loading full track or if we want local loudness)
        if is_full_load and self.loudness is None:
            meter = pyln.Meter(sr)
            self.loudness = meter.integrated_loudness(data_mono)
            self._save_cache()

        self.sr = sr
        self._samples = data_mono.astype(np.float32)
        return self._samples

    def load(self, start_time: float = 0.0, duration: float = -1.0) -> mx.array:
        """
        Reads the file and converts it, both on the calling thread.

        Args:
            start_time (float, optional): Time in seconds to start reading. Defaults to 0.0.
            duration (float, optional): Duration in seconds to read. Negative means full track. Defaults to -1.0.

        Returns:
            mx.array: The loaded mono signal array.
        """
        self.read(start_time=start_time, duration=duration)
        return self.to_mlx()

    def to_mlx(self) -> mx.array:
        """
        Turns the samples read by `read` into this track's mlx signal.

        Must run on the thread that will use the signal.  mlx's default
        stream is thread-local, so an `mx.array` built on a worker carries
        that worker's stream and the first use of it elsewhere raises
        `RuntimeError: There is no Stream(gpu, 3) in current thread` -- from
        wherever the signal is next touched, not from the thread that made
        it.  `read` is separate from this for exactly that reason: the file
        reading parallelises, the conversion does not.

        Returns:
            mx.array: The mono signal, or None if nothing has been read.
        """
        if self._samples is None:
            return None
        self.signal = mx.array(self._samples)
        return self.signal
