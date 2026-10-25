"""Jokainen työnkulku sanoo oikeutensa itse.

Ilman ``permissions``-lohkoa työnkulku perii arkiston oletuksen, ja se on
usein kirjoitusoikeus kaikkeen. Mikään näistä työnkuluista ei kirjoita
arkistoon, joten lukuoikeus riittää, ja CodeQL huomautti kahdesta jolla ei
ollut lohkoa lainkaan. Lohko on testi eikä tapa: uusi työnkulku ilman sitä
punastuu täällä.

Tarkistus on tekstiä eikä YAMLia: jäsennin ei ole työtilan riippuvuus, eikä
sitä kannata lisätä lukkoon yhden rivin etsimisen vuoksi.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

WORKFLOWS = sorted((Path(__file__).resolve().parents[1] / ".github" / "workflows").glob("*.yml"))
WORKFLOW_LEVEL = re.compile(r"^permissions:", re.MULTILINE)
JOB_LEVEL = re.compile(r"^    permissions:", re.MULTILINE)


def test_the_two_workflows_that_had_none_are_among_those_checked():
    names = {path.name for path in WORKFLOWS}
    assert {"check-colab-dependencies.yml", "viewer.yml"} <= names


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_a_workflow_declares_its_permissions(path):
    text = path.read_text(encoding="utf-8")
    assert WORKFLOW_LEVEL.search(text) or JOB_LEVEL.search(text), (
        f"{path.name} perii arkiston oletusoikeudet"
    )
