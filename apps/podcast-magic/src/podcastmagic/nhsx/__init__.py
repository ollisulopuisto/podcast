"""Hindenburgin istuntotiedosto (.nhsx).

Molempien moduulien yhteinen selkäranka: litterointi kirjoittaa sanat
äänipooliin, vaimennus lukee ne sieltä ja pilkkoo raidat.

Lukemisen ja kirjoittamisen rinnalla istunnon voi myös **kuulla**:
``mix`` sijoittaa alueet ohjelma-aikajanalle tasoineen, häivytyksineen ja
panorointeineen, ``render`` summaa ne WAViksi ja ``cli`` on se komento joka
tekee sen ilman Hindenburgia. ``prospect`` kertoo mitä istunnossa on niiltä
osin kuin sitä ei vielä osata lukea.
"""

from .mix import Clip, Mix, plan
from .read import (
    FileInfo,
    NhsxError,
    Session,
    TrackInfo,
    Word,
    locate,
    read,
    seconds_to_time,
    time_to_seconds,
)
from .write import set_transcription, write

__all__ = [
    "Clip",
    "FileInfo",
    "Mix",
    "NhsxError",
    "Session",
    "TrackInfo",
    "Word",
    "locate",
    "plan",
    "read",
    "seconds_to_time",
    "set_transcription",
    "time_to_seconds",
    "write",
]
