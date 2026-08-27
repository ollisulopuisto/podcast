"""Hindenburgin istuntotiedosto (.nhsx).

Molempien moduulien yhteinen selkäranka: litterointi kirjoittaa sanat
äänipooliin, vaimennus lukee ne sieltä ja pilkkoo raidat.
"""

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
    "FileInfo",
    "NhsxError",
    "Session",
    "TrackInfo",
    "Word",
    "locate",
    "read",
    "seconds_to_time",
    "set_transcription",
    "time_to_seconds",
    "write",
]
