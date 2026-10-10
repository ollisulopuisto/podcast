"""Automaattinen asettelu: kuvien kestoista jaksot, ei välkettä."""

from __future__ import annotations

import pytest

from autoraffkat import autolayout
from autoraffkat.layout import LAYOUT_SINGLE, LAYOUT_WIDE_TOP


@pytest.fixture(autouse=True)
def _numbers(monkeypatch):
    """Testit käyttävät omia luvuilla jotta ne eivät kaadu kun makuarvoja
    säädetään: pito 10 s, jakso vähintään 20 s."""
    monkeypatch.setattr(autolayout, "HOLD", 10.0)
    monkeypatch.setattr(autolayout, "MIN_RUN", 20.0)


def test_a_long_hold_is_one_picture_and_quick_exchange_is_the_wide_on_top():
    durations = [4.0, 5.0, 4.0, 6.0, 5.0, 30.0]    # vuorottelu 24 s, sitten pito
    assert autolayout.plan(durations) == [LAYOUT_WIDE_TOP] * 5 + [LAYOUT_SINGLE]


def test_a_short_run_takes_the_layout_of_its_longer_neighbour():
    """Kahden sekunnin pito kesken vuorottelun ei vaihda asettelua, eikä
    lyhyt vuorottelu pitkän pidon sisällä: se olisi välke."""
    inside_exchange = [5.0] * 6 + [12.0] + [5.0] * 6       # yksi 12 s pito
    assert set(autolayout.plan(inside_exchange)) == {LAYOUT_WIDE_TOP}
    inside_hold = [30.0, 5.0, 4.0, 30.0]                   # 9 s vuorottelua
    assert set(autolayout.plan(inside_hold)) == {LAYOUT_SINGLE}


def test_both_long_runs_are_kept_and_the_boundary_is_at_a_shot_edge():
    durations = [5.0] * 5 + [25.0] + [5.0] * 5             # 25 s, 25 s, 25 s
    plan = autolayout.plan(durations)
    assert plan == [LAYOUT_WIDE_TOP] * 5 + [LAYOUT_SINGLE] + [LAYOUT_WIDE_TOP] * 5


def test_nothing_in_nothing_out():
    assert autolayout.plan([]) == []
    assert autolayout.plan([3.0]) == [LAYOUT_WIDE_TOP]     # yksin jäävä lyhyt kuva


def test_the_plan_is_deterministic_and_has_one_entry_per_shot():
    durations = [2.0, 15.0, 3.0, 40.0, 4.0, 4.0, 9.0, 11.0]
    assert autolayout.plan(durations) == autolayout.plan(list(durations))
    assert len(autolayout.plan(durations)) == len(durations)


def test_the_boundaries_are_where_the_layout_changes():
    plan = [LAYOUT_WIDE_TOP] * 3 + [LAYOUT_SINGLE] * 2 + [LAYOUT_WIDE_TOP]
    assert autolayout.changes(plan) == [3, 5]
