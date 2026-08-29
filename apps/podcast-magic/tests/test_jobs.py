"""Työjono: yksi kerrallaan, edistyminen, peruutus."""

from __future__ import annotations

import threading
import time

from podcastmagic import jobs
from podcastmagic.jobs import Runner


def test_a_finished_job_reports_its_result():
    runner = Runner()
    job = runner.start("t", "nimi", lambda progress: {"written": "x"})
    _wait(job)
    snapshot = job.snapshot()
    assert snapshot["ok"] and snapshot["result"] == {"written": "x"}


def test_an_exception_becomes_a_message_not_a_crash():
    runner = Runner()

    def boom(progress):
        raise ValueError("meni pieleen")

    job = runner.start("t", "nimi", boom)
    _wait(job)
    assert "meni pieleen" in job.snapshot()["error"]
    assert not job.snapshot()["ok"]


def test_a_second_job_is_refused_while_the_first_runs():
    """Kaksi litterointia jakaisi saman näytönohjaimen ja molemmat hidastuisivat."""
    runner = Runner()
    gate = threading.Event()
    runner.start("t", "eka", lambda progress: gate.wait(5) and {})
    try:
        with pytest.raises(RuntimeError):
            runner.start("t", "toka", lambda progress: {})
    finally:
        gate.set()


def test_cancel_stops_the_work_at_the_next_check():
    runner = Runner()
    started = threading.Event()

    def loop(progress):
        started.set()
        for _ in range(10000):
            progress.check()
            time.sleep(0.001)
        return {}

    job = runner.start("t", "nimi", loop)
    started.wait(2)
    assert runner.cancel()
    _wait(job)
    assert job.snapshot()["cancelled"]


def test_a_new_step_clears_the_previous_fraction():
    """Edellisen vaiheen osuus jäisi muuten palkkiin seuraavan alkuun."""
    runner = Runner()
    seen = []

    def work(progress):
        progress.step("eka", 0, 2)
        progress.fraction(0.9)
        seen.append(progress._job.fraction)
        progress.step("toka", 1, 2)
        seen.append(progress._job.fraction)
        return {}

    _wait(runner.start("t", "nimi", work))
    assert seen == [0.9, None]


def test_the_log_does_not_grow_without_bound():
    runner = Runner()

    def noisy(progress):
        for i in range(1500):
            progress.log(str(i))
        return {}

    job = runner.start("t", "nimi", noisy)
    _wait(job)
    log = job.snapshot()["log"]
    assert len(log) == 500
    assert log[-1] == "1499"


def _wait(job, timeout=5.0):
    deadline = time.time() + timeout
    while job.running and time.time() < deadline:
        time.sleep(0.005)
    assert not job.running, "työ ei päättynyt"


def test_step_carries_its_own_clock():
    """Kaksi arviota tarvitsee kaksi kelloa.

    Työn `elapsed` kertoo koko ajon iän, mutta «kauanko tämä tiedosto vielä
    kestää» lasketaan vaiheen omasta iästä: tiedostot ovat eri mittaisia,
    joten koko ajon keskinopeus ei kerro tästä tiedostosta mitään.
    """
    job = jobs.Job(id=1, module="testi", label="")
    progress = jobs.Progress(job)

    progress.step("eka.wav", done=0, total=2)
    job.step_started -= 30.0
    first = job.snapshot()["stepElapsed"]
    assert first >= 30.0

    progress.step("toka.wav", done=1, total=2)
    assert job.snapshot()["stepElapsed"] < first
