"""Whisper-moottorit.

Yksi rajapinta, monta toteutusta. Uusi moottori on yksi tiedosto ja yksi rivi
``BACKENDS``-listaan; kutsupaikat eivät muutu.

Valintajärjestys on nopeusjärjestys Apple Siliconilla. mlx-whisper ajaa mallin
Metalilla, faster-whisper ei: CTranslate2:ssa ei ole Metal-taustaa, joten se
pyörii Macilla suorittimella. Ero on kertaluokka, ja siksi mlx on oletus aina
kun se on asennettavissa. faster-whisper on silti mukana: se on sama moottori
kuin Colab-muistikirjassa, se toimii Intel-Macilla, ja kun tulos näyttää
oudolta on hyvä voida ajaa sama tiedosto toisella moottorilla.
"""

from __future__ import annotations

from .base import Backend, BackendInfo, TranscriptResult
from .faster import FasterWhisper
from .mlx import MlxWhisper

BACKENDS: tuple[Backend, ...] = (MlxWhisper(), FasterWhisper())


def infos() -> list[BackendInfo]:
    return [b.info() for b in BACKENDS]


def resolve(key: str) -> Backend:
    """Moottori avaimella. ``auto`` valitsee nopeimman asennetun.

    Tuntematon tai asentamaton nimi on virhe eikä hiljainen vaihto: väärällä
    moottorilla ajettu tunnin jakso on tunti hukkaan, ja se selviäisi vasta
    lopuksi.
    """
    if key in ("", "auto"):
        for backend in BACKENDS:
            if backend.info().available:
                return backend
        raise RuntimeError(
            "Yhtään Whisper-moottoria ei ole asennettu. Aja työtilan "
            "juuressa — Apple Silicon: uv sync --all-packages --extra mlx. "
            "Muut: uv sync --all-packages --extra faster."
        )
    for backend in BACKENDS:
        if backend.key == key:
            info = backend.info()
            if not info.available:
                raise RuntimeError(f"{info.label}: {info.reason}")
            return backend
    raise RuntimeError(f"Tuntematon moottori: {key}")


__all__ = ["BACKENDS", "Backend", "BackendInfo", "TranscriptResult", "infos", "resolve"]
