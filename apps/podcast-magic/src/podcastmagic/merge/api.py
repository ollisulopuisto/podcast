"""Litteroinnin siirron rajapinta selaimelle."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import settings as saved
from ..jobs import RUNNER
from ..nhsx.read import NhsxError
from . import core

router = APIRouter()
SECTION = "merge"


def _args(body: dict) -> tuple[str, str, bool]:
    """Kaksi istuntoa ja lupa korvata. Sekoitettuna sekin on kerrottava."""
    source = str(body.get("source") or "").strip()
    target = str(body.get("session") or "").strip()
    if not target:
        raise HTTPException(400, "Valitse istuntotiedosto, johon litterointi kopioidaan.")
    if not source:
        raise HTTPException(
            400, "Valitse lähdeistunto, josta litterointi kopioidaan."
        )
    return source, target, bool(body.get("overwrite", False))


@router.get("/info")
def info() -> dict:
    return {"overwrite": bool(saved.section(SECTION).get("overwrite", False))}


@router.post("/preview")
def preview(body: dict) -> dict:
    source, target, overwrite = _args(body)
    try:
        return core.merge(source, target, overwrite=overwrite, save=False)
    except NhsxError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/run")
def start(body: dict) -> dict:
    source, target, overwrite = _args(body)
    saved.save(SECTION, {"overwrite": overwrite})

    def work(_progress):
        return core.merge(source, target, overwrite=overwrite)

    try:
        job = RUNNER.start(SECTION, target, work)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return job.snapshot()
