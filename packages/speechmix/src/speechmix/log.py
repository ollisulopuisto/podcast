"""Tarkempi loki: vaiheiden sisäiset askeleet ja niiden kestot.

Isännän oma loki kertoo vaiheen («dynamics 506 s»), mutta ei sitä mikä sen
sisällä vei ajan (käyttäjä, 2026-10-07). Tämä kertoo, **vain pyydettäessä**:
``SPEECHMIX_VERBOSE=1`` ympäristössä tai ``enable()``. Ympäristömuuttuja on
se joka kulkee myös autoraffkatin käsittelyn lapsiprosessiin.

Rivit menevät ``logging``in kautta (``speechmix``-loggeri, DEBUG), joten
testi tai isäntä voi kuunnella niitä ilman tulostusta.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from contextlib import contextmanager

LOGGER = logging.getLogger("speechmix")
_handler: logging.Handler | None = None


def enable() -> None:
    """Askeleet terminaaliin, kuten isännän oma ``[ääni]``-loki."""
    global _handler
    LOGGER.setLevel(logging.DEBUG)
    if _handler is None:
        _handler = logging.StreamHandler(sys.stdout)
        _handler.setFormatter(logging.Formatter("[ääni]       · %(message)s"))
        LOGGER.addHandler(_handler)
        LOGGER.propagate = False


def disable() -> None:
    global _handler
    if _handler is not None:
        LOGGER.removeHandler(_handler)
        _handler = None
    LOGGER.setLevel(logging.WARNING)
    LOGGER.propagate = True


def debug(message: str) -> None:
    LOGGER.debug(message)


@contextmanager
def step(name: str):
    """Askel ja sen kesto: ``with step("deess"): ...``."""
    if not LOGGER.isEnabledFor(logging.DEBUG):
        yield
        return
    started = time.perf_counter()
    try:
        yield
    finally:
        LOGGER.debug(f"{name} {time.perf_counter() - started:.1f}s")


if os.environ.get("SPEECHMIX_VERBOSE"):
    enable()
