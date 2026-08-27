"""Every knob that changes what the chain does, in one place.

The list matters as much as the values: ``fingerprint.FINGERPRINT_FIELDS`` is
written out by hand against this dataclass, and a test fails if the two drift.
A new setting that slips in unnoticed is a setting that does not invalidate an
"up to date" stamp, and then a processed file that is out of date says it is
current.
"""

from dataclasses import asdict, dataclass, replace

from . import ceiling as _ceiling
from . import debleed as _debleed
from . import declick as _declick
from . import dynamics as _dynamics
from . import envelopes as _envelopes
from . import rider as _rider


@dataclass(frozen=True)
class ChainSettings:
    """What the chain does to a track.  Host-agnostic: no paths, no timelines.

    The plug-in slot is flavour, not a replacement mechanism: one slot, it runs
    first, and it never stands in for a stage of the chain.  A
    speech-restoration model is the one thing this pipeline has no opinion
    about and cannot ship; everything after it was measured, and those numbers
    are the tool.  A second plug-in would quietly undo them -- someone loads a
    limiter in front of ours and the ceiling guarantee stops being true with
    nothing to say so.
    """

    # -- the one plug-in slot ------------------------------------------------
    plugin_path: str = ""
    #: Not everything that changes the result is an automatable parameter.
    #: dxRevive publishes four, and the model selector is not one of them -- it
    #: lives in the plug-in's own state.  Save the opaque state blob with the
    #: project and put it in the fingerprint.
    plugin_state_digest: str = ""
    #: Cutting a file into pieces for parallel plug-in runs changes the result
    #: (the pieces do not see each other's context: measured 25.7 dB below the
    #: signal in speech, -84 dBFS in the quiet parts), so the piece count is
    #: part of the fingerprint.
    plugin_pieces: int = 1

    # -- de-bleeding (raw audio, before the plug-in) -------------------------
    debleed_enabled: bool = True
    debleed_taps: int = _debleed.DEFAULT_TAPS
    debleed_min_preservation: float = _debleed.MIN_PRESERVATION

    # -- de-clicking ---------------------------------------------------------
    declick_enabled: bool = True
    declick_max_per_minute: float = _declick.DEFAULT_MAX_PER_MINUTE

    # -- the channel strip ---------------------------------------------------
    highpass_hz: float = 80.0
    rider_enabled: bool = True
    rider_window_sec: float = _rider.DEFAULT_WINDOW_SEC
    rider_max_boost_db: float = _rider.DEFAULT_MAX_BOOST_DB
    rider_max_cut_db: float = _rider.DEFAULT_MAX_CUT_DB
    deess_enabled: bool = True
    deess_threshold_db: float = -30.0
    peak_threshold_db: float = _dynamics.PEAK_THRESHOLD_DB
    leveler_threshold_db: float = _dynamics.LEVELER_THRESHOLD_DB
    peak_ratio: float = 2.5
    leveler_ratio: float = 1.5
    glue_ratio: float = 1.25
    max_gr_db: float = _dynamics.MAX_GR_DB

    # -- programme-level decisions -------------------------------------------
    duck_depth_db: float = _envelopes.DEFAULT_DEPTH_DB
    target_lufs: float = -16.0
    ceiling_dbfs: float = _ceiling.DEFAULT_CEILING_DBFS

    def as_dict(self):
        return asdict(self)

    def with_(self, **changes):
        return replace(self, **changes)
