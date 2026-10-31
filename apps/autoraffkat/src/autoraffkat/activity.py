"""macOS-aktiviteetit pitkiä, käyttäjän käynnistämiä töitä varten."""

from __future__ import annotations

import sys
from contextlib import contextmanager
from functools import wraps
from typing import Callable, Iterator, TypeVar

F = TypeVar("F", bound=Callable)


@contextmanager
def prevent_app_nap(reason: str) -> Iterator[None]:
    """Estä App Nap työn ajaksi, mutta salli järjestelmän joutokäyntilepo.

    Aktiviteetti on prosessikohtainen, joten myös äänen lapsiprosessi käyttää
    tätä itse. Muilla alustoilla ympäristö on tarkoituksella tyhjä.
    """
    if sys.platform != "darwin":
        yield
        return

    from Foundation import (  # pyobjc-framework-AVFoundationin riippuvuus
        NSActivityUserInitiatedAllowingIdleSystemSleep,
        NSProcessInfo,
    )

    process = NSProcessInfo.processInfo()
    token = process.beginActivityWithOptions_reason_(
        NSActivityUserInitiatedAllowingIdleSystemSleep, reason
    )
    try:
        yield
    finally:
        process.endActivity_(token)


def app_activity(reason: str) -> Callable[[F], F]:
    """Kääri pitkä työ App Nap -aktiviteettiin ja säilytä funktion metadata."""

    def decorate(function: F) -> F:
        @wraps(function)
        def guarded(*args, **kwargs):
            with prevent_app_nap(reason):
                return function(*args, **kwargs)

        guarded.__app_nap_reason__ = reason
        return guarded

    return decorate
