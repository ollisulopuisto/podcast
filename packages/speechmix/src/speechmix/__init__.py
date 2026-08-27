"""speechmix -- the shared speech-mixing pipeline.

Samples in, samples out.  This package has never heard of FCPXML, session
files, timelines or paths: everything a host knows lives on the host's side of
:func:`speechmix.chain.process_track`.  The one host-shaped idea it does carry
is "a track with a placement on a programme timeline"
(:mod:`speechmix.timeline`), because the conversion between programme time and
file time is the only timeline knowledge the pipeline needs.

Two seams:

* **Samples**: the chain takes an array and returns an array.
* **Decisions**: :func:`speechmix.envelopes.duck_envelopes` returns gain
  *decisions*, and the host decides whether they become samples or automation.
  Level decisions that come after the chain can be automation; level decisions
  that come before it must be baked in.

Every constant in here has a measured number next to it, in the comment where
it lives.  ``FINDINGS.md`` in the repository root carries the same numbers with
their stories, and ``tests/speechmix/`` is where they are enforced.  The
measurement tests are the real asset: they encode findings that each cost hours
to discover.

This directory is deliberately self-contained (numpy, scipy, pyloudnorm and
nothing else) so that it can be lifted wholesale into a shared
``packages/speechmix/`` when a second consumer wants it.
"""

from .ceiling import CeilingReport, programme_ceiling
from .chain import ChainReport, process_track
from .debleed import DebleedReport, debleed, estimate_bleed_filter
from .declick import DeclickReport, declick
from .dynamics import DynamicsReport, StageReport, compress, deess, multiband_compress, speech_dynamics
from .envelopes import DuckSettings, apply_envelope, duck_envelopes
from .errors import (
    EmptyResult,
    LengthChanged,
    Misaligned,
    NotMono,
    Refused,
    SpeechmixError,
)
from .fingerprint import FINGERPRINT_FIELDS, FINGERPRINT_VERSION, fingerprint, is_stale
from .grid import SpeechGrid, speech_grid
from .loudness import ProgrammeTarget, crest_db, integrated_lufs, normalise, programme_target
from .plugin import process_in_pieces
from .rider import RiderReport, ride
from .settings import ChainSettings
from .timeline import Span, Track
from .verify import assert_no_shift, assert_same_length, measure_shift

__all__ = [
    "CeilingReport",
    "ChainReport",
    "ChainSettings",
    "DebleedReport",
    "DeclickReport",
    "DuckSettings",
    "DynamicsReport",
    "EmptyResult",
    "FINGERPRINT_FIELDS",
    "FINGERPRINT_VERSION",
    "LengthChanged",
    "Misaligned",
    "NotMono",
    "ProgrammeTarget",
    "Refused",
    "RiderReport",
    "Span",
    "SpeechGrid",
    "SpeechmixError",
    "StageReport",
    "Track",
    "apply_envelope",
    "assert_no_shift",
    "assert_same_length",
    "compress",
    "crest_db",
    "debleed",
    "declick",
    "deess",
    "duck_envelopes",
    "estimate_bleed_filter",
    "fingerprint",
    "integrated_lufs",
    "is_stale",
    "measure_shift",
    "multiband_compress",
    "normalise",
    "process_in_pieces",
    "process_track",
    "programme_ceiling",
    "programme_target",
    "ride",
    "speech_dynamics",
    "speech_grid",
]
