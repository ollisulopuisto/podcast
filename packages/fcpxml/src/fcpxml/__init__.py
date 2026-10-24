"""Final Cut Pro XML: exact rational times and neutral types.

``read_fcpxml`` reads a ``.fcpxml`` file or a ``.fcpxmld`` bundle into a
``Timeline``. Every time is a ``Fraction`` of seconds; nothing here knows about
a user interface, and an error is a stable ``ReadError.code``.
"""

from .model import (
    Format,
    Marker,
    MediaItem,
    MulticamRef,
    Placement,
    SpineItem,
    Timeline,
    Track,
    Transition,
)
from .read import BUNDLE_INNER, ReadError, read_fcpxml
from .timeline import ZERO, format_time, parse_time
from .write import ConformError, conform, snap_pieces

__all__ = [
    "BUNDLE_INNER",
    "ZERO",
    "ConformError",
    "Format",
    "Marker",
    "MediaItem",
    "MulticamRef",
    "Placement",
    "ReadError",
    "SpineItem",
    "Timeline",
    "Track",
    "Transition",
    "conform",
    "format_time",
    "parse_time",
    "read_fcpxml",
    "snap_pieces",
]
