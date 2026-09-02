"""NHSX parser — Hindenburg .nhsx session reader.

This package provides the NHSX parser and the pipeline seam that converts
a Hindenburg session into `speechmix.timeline.Track`/`Span` objects.
"""

from .pipeline import tracks
from .read import (
    FileInfo,
    NhsxError,
    RegionInfo,
    Session,
    TrackInfo,
    Word,
    locate,
    read,
    seconds_to_time,
    time_to_seconds,
)

__all__ = [
    "FileInfo",
    "NhsxError",
    "RegionInfo",
    "Session",
    "TrackInfo",
    "Word",
    "locate",
    "read",
    "seconds_to_time",
    "time_to_seconds",
    "tracks",
]

__version__ = "2026.8.31.1"
