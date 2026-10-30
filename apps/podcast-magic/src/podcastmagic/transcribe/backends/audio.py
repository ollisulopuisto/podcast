"""Äänen väliaikainen WAV-sovitus moottoreille, jotka ottavat tiedostopolun."""

from __future__ import annotations

import tempfile
import wave
from contextlib import contextmanager
from pathlib import Path

import numpy as np

from ...audio import SAMPLE_RATE


@contextmanager
def wav_file(samples: np.ndarray):
    """Kirjoita monoääni väliaikaiseksi 16 kHz PCM16 WAViksi."""
    with tempfile.TemporaryDirectory(prefix="podcast-magic-audio-") as directory:
        path = Path(directory) / "audio.wav"
        pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
        with wave.open(str(path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(SAMPLE_RATE)
            output.writeframes(pcm.tobytes())
        yield str(path)
