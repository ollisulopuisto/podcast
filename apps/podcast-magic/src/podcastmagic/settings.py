"""Viimeksi käytetyt asetukset levylle.

Asetukset ovat käyttäjäkohtaisia eivätkä projektikohtaisia: malli ja kynnys
ovat ominaisuuksia koneesta ja työtavasta, eivät jaksosta. Sarjan seuraava
jakso avautuu samoilla säädöillä kuin edellinen.
"""

from __future__ import annotations

import contextlib
import json
import threading

from .paths import state_dir

_LOCK = threading.Lock()
_FILE = "settings.json"


def _path():
    return state_dir() / _FILE


def load() -> dict:
    try:
        return json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save(section: str, values: dict) -> None:
    """Tallentaa yhden moduulin asetukset. Muut osiot jäävät koskematta."""
    with _LOCK:
        data = load()
        data[section] = values
        # Asetusten tallennus ei ole työn tulos. Jos kotihakemistoon ei
        # voi kirjoittaa, ohjelman pitää silti toimia.
        with contextlib.suppress(OSError):
            _path().write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def section(name: str) -> dict:
    value = load().get(name)
    return value if isinstance(value, dict) else {}
