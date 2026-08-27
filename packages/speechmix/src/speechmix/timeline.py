"""The one piece of host knowledge the pipeline needs.

The abstraction is "a track with a placement on a programme timeline" -- not
"an FCPXML asset".  An FCPXML asset is that.  An automixer session track is
that.  Whatever the host's session format is, it is that.

The conversion between programme time and file time is linear inside each
span, and that single formula is all the timeline knowledge the pipeline
needs.
"""

from dataclasses import dataclass, field
from typing import List, Optional

from .errors import NotMono


@dataclass(frozen=True)
class Span:
    """A contiguous placement of a file on the programme timeline.

    Attributes:
        programme_start: Where the span begins on the programme timeline, in seconds.
        programme_end: Where it ends, in seconds.
        file_offset: The time in the *file* that lines up with ``programme_start``.
    """

    programme_start: float
    programme_end: float
    file_offset: float = 0.0

    def __post_init__(self):
        if self.programme_end < self.programme_start:
            raise ValueError(
                f"span ends before it starts: {self.programme_start} -> {self.programme_end}"
            )

    @property
    def duration(self) -> float:
        return self.programme_end - self.programme_start

    def contains(self, programme_time: float) -> bool:
        return self.programme_start <= programme_time < self.programme_end

    def to_file_time(self, programme_time: float) -> float:
        """Convert a programme time to a time in the file.

        The mapping is linear inside a span -- the whole of the pipeline's
        timeline knowledge is this one line.
        """
        return self.file_offset + (programme_time - self.programme_start)


@dataclass
class Track:
    """A microphone track with its placement on the programme timeline.

    Attributes:
        path: Where the audio lives.
        speaker: Who this microphone belongs to.  Two tracks may share a
            speaker; the pipeline keys its masks and envelopes on this.
        spans: The placements of this file on the programme timeline.
        mono: Always True for microphones.  See ``NotMono``.
        bit_depth: Source bit depth, carried so a host can write the same back.
    """

    path: str
    speaker: str
    spans: List[Span] = field(default_factory=list)
    mono: bool = True
    bit_depth: int = 24

    def __post_init__(self):
        if not self.mono:
            raise NotMono(
                f"{self.path}: a microphone is always mono out, even from a stereo "
                "source; two channels break de-bleeding, the programme ceiling and "
                "panning, all three silently"
            )

    def span_at(self, programme_time: float) -> Optional[Span]:
        """The span covering ``programme_time``, or None if the track is not there."""
        for span in self.spans:
            if span.contains(programme_time):
                return span
        return None

    def to_file_time(self, programme_time: float) -> Optional[float]:
        """File time for a programme time, or None where this track is not placed."""
        span = self.span_at(programme_time)
        return None if span is None else span.to_file_time(programme_time)
