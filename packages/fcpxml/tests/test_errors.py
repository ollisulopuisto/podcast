"""A failure is a stable ``code``, never a text a person is meant to read.

A host (autoraffkat, kuulas) translates the code. ``str(error)`` is for a log.
"""

from __future__ import annotations

import pytest
import xml_builders as xb
from fcpxml import ReadError, read_fcpxml


def _code(path) -> str:
    with pytest.raises(ReadError) as caught:
        read_fcpxml(str(path))
    return caught.value.code


def test_garbage_is_bad_xml(tmp_path):
    path = tmp_path / "garbage.fcpxml"
    path.write_text("this is not xml <<<")
    assert _code(path) == "bad_xml"


def test_an_empty_file_is_bad_xml(tmp_path):
    path = tmp_path / "empty.fcpxml"
    path.write_text("")
    assert _code(path) == "bad_xml"


def test_a_missing_file_is_unreadable(tmp_path):
    assert _code(tmp_path / "nowhere.fcpxml") == "unreadable"


def test_a_bundle_without_info_is_its_own_code(tmp_path):
    bundle = tmp_path / "episode.fcpxmld"
    bundle.mkdir()
    assert _code(bundle) == "bundle_without_info"


def test_a_time_that_is_not_a_time_is_bad_time(tmp_path):
    spine = '<asset-clip ref="a1" offset="soon" duration="5s" start="0s"/>'
    assert _code(xb.write(tmp_path, xb.project(spine))) == "bad_time"


def test_a_time_with_a_zero_denominator_is_bad_time(tmp_path):
    spine = '<asset-clip ref="a1" offset="1/0s" duration="5s" start="0s"/>'
    assert _code(xb.write(tmp_path, xb.project(spine))) == "bad_time"


def test_a_timeline_with_nothing_on_it_is_no_media(tmp_path):
    assert _code(xb.write(tmp_path, xb.project(""))) == "no_media"


def test_the_message_names_the_code_and_the_detail():
    error = ReadError("bad_root", "notfcpxml")
    assert error.code == "bad_root" and error.detail == "notfcpxml"
    assert "bad_root" in str(error) and "notfcpxml" in str(error)
    assert str(ReadError("no_project")) == "no_project"
