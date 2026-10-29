"""Äänen väliaikainen WAV-sovitus moottoreille, jotka ottavat tiedostopolun."""

from __future__ import annotations

import tempfile
import wave
from contextlib import contextmanager

import numpy as np

from ...audio import SAMPLE_RATE


@contextmanager
def wav_file(samples: np.ndarray):
    """Kirjoita monoääni väliaikaiseksi 16 kHz PCM16 WAViksi."""
    with tempfile.NamedTemporaryFile(suffix=".wav") as file:
        pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
        with wave.open(file.name, "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(SAMPLE_RATE)
            output.writeframes(pcm.tobytes())
        yield file.name
