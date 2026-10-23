"""Jäsennelty edistyminen kuulakselle: ``--events``.

Lipun kanssa jokaisesta tapahtumasta tulostuu tekstirivien rinnalle yksi rivi
stdoutiin: ``@@kuulas `` ja yksi JSON-olio samalla rivillä, heti huuhdeltuna.
stdout siksi, että se kulkee kuulakselle samalla tavalla paikallisesti ja
ssh:n yli; tekstirivit eivät muutu. Sama sopimus kuin automixerin
``--events`` (``apps/automixer/src/automixer/events.py``) ja sama etuliite,
jotta yksi lukija riittää molempiin. Kopio eikä tuonti, koska tämä sovellus ei
tunne muita työtilan jäseniä.

Jokaisella oliolla on ``schema`` ja ``event``; kenttiä voi lisätä, ei nimetä
uudelleen. Tapahtumat on lueteltu ``docs/KUULAS-COLAB.md``:ssä.
"""

from __future__ import annotations

import json
import math
import threading

PREFIX = "@@kuulas "
SCHEMA = 1

_lock = threading.Lock()
_enabled = False


def enable(on: bool = True) -> None:
    global _enabled
    _enabled = bool(on)


def _clean(value):
    """JSONissa ei ole infiä eikä nania: ne muuttuvat nulliksi."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    return value


def emit(event: str, **fields) -> None:
    if not _enabled:
        return
    line = PREFIX + json.dumps(
        {"schema": SCHEMA, "event": event, **_clean(fields)}, ensure_ascii=False
    )
    # Yksi kirjoitus lukon alla: ajurin rivit ja pääsäie eivät saa mennä
    # toistensa päälle.
    with _lock:
        print(line, flush=True)


class StageTrail:
    """``stage``-tapahtumat: vaihe alkaa kun seuraava alkaa tai ajo päättyy.

    Ajuri tietää vain minkä vaiheen se aloittaa; edellisen päättyminen on
    sama hetki, ja ``colab exec`` ei erottele pilvipään vaiheita muuten kuin
    riveillään. Siksi ``enter`` sulkee edellisen itse. Sama vaihe samalla
    indeksillä ja nimellä ei tule kahdesti (``[ääni (1/2)]`` voi toistua
    riveissä). ``current`` on vaihe joka on alkanut mutta ei päättynyt:
    kaatuneen ajon kohta, ``error``-tapahtumaa varten.

    ``name`` on äänitiedoston nimi (kuulaksen toast: «Take 1-Mic.wav»,
    ei vain «tiedosto 1/2»). ``via`` ja ``size`` kuuluvat siirtovaiheelle:
    ``drive`` tai ``direct``, ja tavut. ``size`` tulee tapahtumaan nimellä
    ``total`` (kuten ``transfer``-tapahtumassa), ja päättyvässä tapahtumassa
    ``done`` on sama luku: vaihe päättyi, joten kaikki lähti. ``total`` on
    siis tavuja siirtovaiheessa ja tiedostojen lukumäärä ``transcribe``- ja
    ``align``-vaiheissa, joissa on ``index``.
    """

    def __init__(self) -> None:
        self.current: str | None = None
        self._key: tuple | None = None
        self._fields: dict = {}
        self._sized = False

    def enter(
        self,
        stage: str,
        index: int | None = None,
        total: int | None = None,
        name: str | None = None,
        via: str | None = None,
        size: int | None = None,
    ) -> None:
        # Tiedostovaiheen identiteetti on (vaihe, indeksi, yhteensä): sama rivi voi
        # tulla kahdesti, vain toisessa nimi. Siirrolla ei ole indeksiä, ja siellä
        # identiteetti on tiedosto.
        key = (stage, index, total) if index is not None else (stage, name, via, size)
        if key == self._key:
            return
        self._close()
        fields: dict = {}
        if index is not None:
            fields.update(index=index, total=total)
        if name:
            fields["name"] = name
        if via:
            fields["via"] = via
        if size is not None:
            fields["total"] = size
        emit("stage", stage=stage, state="start", **fields)
        self.current, self._key, self._fields = stage, key, fields
        self._sized = size is not None

    def finish(self) -> None:
        self._close()

    def _close(self) -> None:
        if self.current is not None:
            done = {"done": self._fields["total"]} if self._sized else {}
            emit("stage", stage=self.current, state="done", **self._fields, **done)
        self.current, self._key, self._fields = None, None, {}
        self._sized = False
