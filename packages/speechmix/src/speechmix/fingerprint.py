'''"Up to date" is a fingerprint, not a modification time.

A processed file newer than its source proves nothing: the plug-in, its
controls, the target level and the ducking depth never touch the source.
Comparing times alone made the button skip every file and return before the
first log line -- indistinguishable from a broken button.

The field list is written out by hand so that a new setting cannot slip in or
out unnoticed, and ``tests/speechmix/test_fingerprint.py`` fails if it drifts
from :class:`~speechmix.settings.ChainSettings`.

The fingerprint describes *what the chain does*, so it belongs to the chain.
*Where the stamp file lives* is per-app.  Get that backwards and every app
invents its own idea of "up to date", which is the bug class this pipeline has
paid for repeatedly.
'''

import hashlib
import json

from .settings import ChainSettings

#: Bump when the meaning of a field changes, or when a stage starts doing
#: something different with the same settings.  Everything stamped with an
#: older version is stale.
FINGERPRINT_VERSION = 1

#: Written out by hand.  Do not generate this from the dataclass -- the point
#: is that adding a field is a decision someone makes twice.
FINGERPRINT_FIELDS = (
    "plugin_path",
    "plugin_state_digest",
    "plugin_pieces",
    "debleed_enabled",
    "debleed_taps",
    "debleed_min_preservation",
    "declick_enabled",
    "declick_max_per_minute",
    "highpass_hz",
    "rider_enabled",
    "rider_window_sec",
    "rider_max_boost_db",
    "rider_max_cut_db",
    "deess_enabled",
    "deess_threshold_db",
    "peak_threshold_db",
    "leveler_threshold_db",
    "peak_ratio",
    "leveler_ratio",
    "glue_ratio",
    "max_gr_db",
    "duck_depth_db",
    "target_lufs",
    "ceiling_dbfs",
)


def fingerprint(settings, extra=None):
    """A stable stamp of everything that changes the result.

    Args:
        settings: A :class:`~speechmix.settings.ChainSettings` or a mapping.
        extra: Per-run values the host wants in the stamp -- the source file's
            content hash, for instance.  Where the stamp is *stored* is the
            host's business; what goes in it is not.

    Returns:
        A hex digest.
    """
    values = settings.as_dict() if isinstance(settings, ChainSettings) else dict(settings)
    missing = [f for f in FINGERPRINT_FIELDS if f not in values]
    if missing:
        raise KeyError(
            f"settings are missing fields the fingerprint names: {missing}; an "
            "unlisted setting is a setting that cannot invalidate a stamp"
        )
    payload = {
        "version": FINGERPRINT_VERSION,
        "fields": {name: values[name] for name in FINGERPRINT_FIELDS},
        "extra": dict(extra or {}),
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


def is_stale(stamp, settings, extra=None):
    """True if the stamp does not match, is missing, or cannot be read.

    An unknown stamp counts as stale.  The alternative -- treating an
    unreadable stamp as current -- is the failure that made a button skip every
    file in silence.
    """
    if not stamp or not isinstance(stamp, str):
        return True
    return stamp != fingerprint(settings, extra)
