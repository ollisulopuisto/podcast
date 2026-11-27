"""Directory event coalescing schedules stability checks without a redraw loop."""
from automixer import folder_events


def test_change_schedules_one_followup_and_stops():
    calls, scheduled = [], []
    adapter = folder_events.StabilityChecks(lambda **kw: calls.append(kw),
        later=lambda delay, callback: scheduled.append((delay, callback)), clock=lambda: 5)
    adapter.changed()
    adapter.changed()
    assert len(scheduled) == 1
    scheduled.pop()[1]()
    assert calls == [{'now': 5}]
    assert len(scheduled) == 1
    scheduled.pop()[1]()
    assert calls == [{'now': 5}, {'now': 5}]
    assert scheduled == []
    adapter.close()
    adapter.changed()
    assert scheduled == []
