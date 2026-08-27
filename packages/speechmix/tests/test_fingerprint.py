'''"Up to date" is a fingerprint, not a modification time.

A processed file newer than its source proves nothing: the plug-in, its
controls, the target level and the ducking depth never touch the source.
Comparing times alone made the button skip every file and return before the
first log line -- indistinguishable from a broken button.
'''

import pytest

from speechmix import fingerprint

SETTINGS = dict.fromkeys(fingerprint.FINGERPRINT_FIELDS, 0)


def test_every_named_field_changes_the_stamp():
    """If a field can change the result but not the stamp, it is not in the list."""
    base = fingerprint.fingerprint(SETTINGS)
    for field in fingerprint.FINGERPRINT_FIELDS:
        changed = dict(SETTINGS, **{field: "different"})
        assert fingerprint.fingerprint(changed) != base, f"{field} does not reach the stamp"


def test_a_settings_object_missing_a_named_field_is_refused():
    """An unlisted setting is a setting that cannot invalidate a stamp."""
    short = dict(SETTINGS)
    del short[fingerprint.FINGERPRINT_FIELDS[0]]
    with pytest.raises(KeyError):
        fingerprint.fingerprint(short)


def test_an_unknown_stamp_counts_as_stale():
    """The alternative -- treating an unreadable stamp as current -- is the
    failure that made a button skip every file in silence.
    """
    good = fingerprint.fingerprint(SETTINGS)
    assert not fingerprint.is_stale(good, SETTINGS)
    assert fingerprint.is_stale(None, SETTINGS)
    assert fingerprint.is_stale("", SETTINGS)
    assert fingerprint.is_stale(12345, SETTINGS)
    assert fingerprint.is_stale("not-a-real-digest", SETTINGS)


def test_the_version_is_part_of_the_stamp():
    """Bumping it must invalidate everything stamped before, even if no setting moved."""
    before = fingerprint.fingerprint(SETTINGS)
    original = fingerprint.FINGERPRINT_VERSION
    try:
        fingerprint.FINGERPRINT_VERSION = original + 1
        assert fingerprint.fingerprint(SETTINGS) != before
    finally:
        fingerprint.FINGERPRINT_VERSION = original


def test_per_run_extras_reach_the_stamp():
    """The host owns where the stamp lives and what else goes in it -- the
    source file's content hash, for instance -- but not which settings count.
    """
    base = fingerprint.fingerprint(SETTINGS)
    assert fingerprint.fingerprint(SETTINGS, {"source": "abc"}) != base
    assert fingerprint.is_stale(base, SETTINGS, {"source": "abc"})


def test_the_field_list_is_written_out_by_hand():
    """Not generated from a dataclass: adding a field is a decision made twice."""
    assert len(set(fingerprint.FINGERPRINT_FIELDS)) == len(fingerprint.FINGERPRINT_FIELDS)
    assert all(isinstance(name, str) for name in fingerprint.FINGERPRINT_FIELDS)
