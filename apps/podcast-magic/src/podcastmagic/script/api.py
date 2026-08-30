"""Käsikirjoitusmoduulin rajapinta selaimelle."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

from ..jobs import RUNNER
from ..nhsx.read import NhsxError
from ..nhsx.write import next_free_path
from . import core

router = APIRouter()
SECTION = "script"


def _session(body: dict) -> str:
    session = str(body.get("session") or "").strip()
    if not session:
        raise HTTPException(400, "Valitse istuntotiedosto.")
    return session


@router.get("/info")
def info() -> dict:
    return {}


@router.post("/preview")
def preview(body: dict) -> dict:
    session = _session(body)
    try:
        return {"markdown": core.script(core.read(session))}
    except NhsxError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/run")
def start(body: dict) -> dict:
    session = _session(body)
    # Istunto luetaan jo tässä: rikkonainen tiedosto on virhe nyt, ei
    # työn tuloksena jonka käyttöliittämä lupasi onnistuneen.
    try:
        parsed = core.read(session)
    except NhsxError as exc:
        raise HTTPException(400, str(exc)) from exc

    def work(_progress):
        text = core.script(parsed)
        target = next_free_path(Path(session).with_suffix(".md"))
        target.write_text(text, encoding="utf-8")
        return {"written": str(target), "lines": len(text.splitlines())}

    try:
        job = RUNNER.start(SECTION, session, work)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return job.snapshot()
