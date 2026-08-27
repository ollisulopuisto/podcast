"""Hindenburgin istuntotiedosto (.nhsx).

Molempien moduulien yhteinen selkäranka: litterointi kirjoittaa sanat
äänipooliin, vaimennus lukee ne sieltä ja pilkkoo raidat.
"""

from .read import (
    NhsxError,
    Session,
    TrackInfo,
    FileInfo,
    Word,
    locate,
    read,
    seconds_to_time,
    time_to_seconds,
)
from .write import set_transcription, write

__all__ = [
    "NhsxError",
    "Session",
    "TrackInfo",
    "FileInfo",
    "Word",
    "read",
    "locate",
    "seconds_to_time",
    "time_to_seconds",
    "set_transcription",
    "write",
]
