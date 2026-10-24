from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import xml_fixtures


@pytest.fixture(scope="session")
def fixture_dir(tmp_path_factory):
    """The synthetic episode as XML with placeholder media."""
    target = tmp_path_factory.mktemp("fixture")
    return Path(xml_fixtures.build(str(target))["sync"]).parent
