"""Taustatyöt ja niiden edistyminen.

Litterointi kestää minuutteja. Sitä ei voi ajaa pyynnön käsittelyssä, koska
silloin käyttöliittymä jäätyy eikä kukaan tiedä eteneekö mikään — ja juuri
sen tietäminen on ainoa asia jota odottaessa haluaa.

Töitä ajetaan yksi kerrallaan. Kaksi rinnakkaista litterointia jakaisivat
saman näytönohjaimen ja valmistuisivat molemmat myöhemmin kuin peräkkäin
ajettuina, ja kaksi vaimennusajoa voisi kirjoittaa samaa tiedostoa.
"""

from __future__ import annotations

import threading
import time
import traceback
from dataclasses import dataclass, field
from typing import Callable

# Lokia näytetään käyttöliittymässä. Pitkä ajo tuottaa rivin per tiedosto ja
# muutaman per vaihe, joten katto on turva vuotavaa silmukkaa vastaan eikä
# odotettu raja.
MAX_LOG_LINES = 500


class Cancelled(RuntimeError):
    """Käyttäjä keskeytti työn."""


@dataclass
class Progress:
    """Työn kahva: tästä työ kertoo missä mennään ja kysyy saako jatkaa."""

    _job: "Job" = field(repr=False)

    def log(self, message: str) -> None:
        self._job.append_log(message)

    def step(self, label: str, done: int | None = None, total: int | None = None) -> None:
        """Vaihe vaihtui. Osuus nollataan, koska se koski edellistä vaihetta."""
        with self._job.lock:
            self._job.step_label = label
            if done is not None:
                self._job.steps_done = done
            if total is not None:
                self._job.steps_total = total
            self._job.fraction = None

    def fraction(self, value: float | None) -> None:
        """Nykyisen vaiheen osuus välillä 0–1, tai None jos ei tiedetä."""
        with self._job.lock:
            self._job.fraction = None if value is None else max(0.0, min(1.0, value))

    def check(self) -> None:
        """Nostaa ``Cancelled``in jos työ on peruttu. Kutsu silmukan alussa."""
        if self._job.cancel_requested:
            raise Cancelled()

    @property
    def cancelled(self) -> bool:
        return self._job.cancel_requested


@dataclass
class Job:
    id: int
    module: str
    label: str
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    running: bool = True
    ok: bool = False
    error: str = ""
    cancel_requested: bool = False
    cancelled: bool = False
    step_label: str = ""
    steps_done: int = 0
    steps_total: int = 0
    fraction: float | None = None
    log: list[str] = field(default_factory=list)
    result: dict = field(default_factory=dict)
    started: float = field(default_factory=time.time)
    finished: float = 0.0

    def append_log(self, message: str) -> None:
        with self.lock:
            self.log.append(message)
            if len(self.log) > MAX_LOG_LINES:
                del self.log[: len(self.log) - MAX_LOG_LINES]
        print(f"[{self.module}] {message}", flush=True)

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "id": self.id,
                "module": self.module,
                "label": self.label,
                "running": self.running,
                "ok": self.ok,
                "error": self.error,
                "cancelled": self.cancelled,
                "step": self.step_label,
                "stepsDone": self.steps_done,
                "stepsTotal": self.steps_total,
                "fraction": self.fraction,
                "log": list(self.log),
                "result": dict(self.result),
                "elapsed": (self.finished or time.time()) - self.started,
            }


class Runner:
    """Yksi työ kerrallaan, edellinen jää näkyviin tulokseksi."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._current: Job | None = None
        self._thread: threading.Thread | None = None
        self._counter = 0

    @property
    def busy(self) -> bool:
        with self._lock:
            return self._current is not None and self._current.running

    def current(self) -> Job | None:
        with self._lock:
            return self._current

    def start(self, module: str, label: str, work: Callable[[Progress], dict]) -> Job:
        """Käynnistää työn. Nostaa ``RuntimeError``in jos edellinen on kesken."""
        with self._lock:
            if self._current is not None and self._current.running:
                raise RuntimeError("Edellinen työ on vielä kesken.")
            self._counter += 1
            job = Job(id=self._counter, module=module, label=label)
            self._current = job

        progress = Progress(job)

        def run() -> None:
            try:
                result = work(progress)
                with job.lock:
                    job.result = result or {}
                    job.ok = True
            except Cancelled:
                with job.lock:
                    job.cancelled = True
                    job.error = "Keskeytetty."
                job.append_log("Keskeytetty.")
            except Exception as exc:  # noqa: BLE001 — virhe kuuluu käyttöliittymään
                with job.lock:
                    job.error = f"{type(exc).__name__}: {exc}"
                job.append_log(job.error)
                traceback.print_exc()
            finally:
                with job.lock:
                    job.running = False
                    job.finished = time.time()

        thread = threading.Thread(target=run, name=f"job-{job.id}", daemon=True)
        self._thread = thread
        thread.start()
        return job

    def cancel(self) -> bool:
        with self._lock:
            job = self._current
        if job is None or not job.running:
            return False
        job.cancel_requested = True
        job.append_log("Keskeytys pyydetty, odotetaan nykyisen vaiheen loppua…")
        return True


RUNNER = Runner()
