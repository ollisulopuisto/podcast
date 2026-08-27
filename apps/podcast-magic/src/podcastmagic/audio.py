"""Äänen luku levyltä: ffmpeg sisään, numpy ulos.

Sama purku palvelee molempia moduuleja. Litterointi tarvitsee 16 kHz monon,
koska Whisper haluaa juuri sitä; vaimennus tarvitsee tason sanan kohdalta,
mihin 16 kHz riittää yhtä hyvin. Kun tiedosto puretaan kerran ja
molemmat lukevat samaa taulukkoa, pitkä jakso ei mene levyltä läpi kahdesti.

Purku tehdään itse eikä jätetä kirjaston tehtäväksi, koska mlx-whisperin oma
``load_audio`` kutsuu ffmpegiä PATHista. Pakatussa sovelluksessa PATHissa ei
ole mitään — binääri on paketin sisällä.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

from .binaries import get_binary_path

SAMPLE_RATE = 16000

# Mitä Hindenburgin äänipooliin voi päätyä.
AUDIO_EXTENSIONS = (".wav", ".aiff", ".aif", ".flac", ".m4a", ".mp4", ".mp3")


class DecodeError(RuntimeError):
    """ffmpeg ei saanut tiedostosta ääntä."""


def is_audio(path: str | Path) -> bool:
    return str(path).lower().endswith(AUDIO_EXTENSIONS)


def decode_pcm(path: str | Path, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Purkaa tiedoston monoksi int16-taulukoksi.

    int16 eikä float32, koska tämä jää muistiin: tunnin jakso on 16 kHz:llä
    115 MB int16:na ja 230 MB float32:na, ja monoraitaisessa istunnossa niitä
    on useita. Whisper haluaa liukuluvut, joten ``decode`` muuntaa — mutta
    tasoa mittaava välimuisti pitää raa'an muodon.
    """
    cmd = [
        get_binary_path("ffmpeg"),
        "-nostdin",
        "-threads", "0",
        "-i", str(path),
        "-f", "s16le",
        "-ac", "1",
        "-acodec", "pcm_s16le",
        "-ar", str(sample_rate),
        "-",
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, check=True).stdout
    except subprocess.CalledProcessError as exc:
        tail = exc.stderr.decode("utf-8", "replace").strip().splitlines()[-3:]
        raise DecodeError(f"{Path(path).name}: {' '.join(tail)}") from exc
    return np.frombuffer(out, np.int16)


def decode(path: str | Path, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Purkaa tiedoston monoksi float32-taulukoksi välillä [-1, 1]."""
    return decode_pcm(path, sample_rate).astype(np.float32) / 32768.0


def duration(samples: np.ndarray, sample_rate: int = SAMPLE_RATE) -> float:
    return float(len(samples)) / sample_rate


def dbfs(samples: np.ndarray, start: float, end: float, sample_rate: int = SAMPLE_RATE) -> float:
    """Jakson RMS desibeleinä täydestä asteikosta.

    Tyhjä jakso on -inf eikä nolla: nolla olisi täysi taso ja päästäisi
    pituudeltaan pyöristyneen sanan läpi kuuluvana.
    """
    a = max(0, int(start * sample_rate))
    b = min(len(samples), int(end * sample_rate))
    if b <= a:
        return float("-inf")
    chunk = samples[a:b].astype(np.float64)
    if samples.dtype == np.int16:
        chunk /= 32768.0
    rms = float(np.sqrt(np.mean(np.square(chunk))))
    if rms <= 0.0:
        return float("-inf")
    return 20.0 * np.log10(rms)
