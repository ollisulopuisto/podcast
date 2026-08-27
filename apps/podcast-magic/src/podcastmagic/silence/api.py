"""Vaimennusmoduulin rajapinta selaimelle."""

from __future__ import annotations

from dataclasses import replace

from fastapi import APIRouter, HTTPException

from .. import settings as saved
from ..jobs import RUNNER
from ..nhsx import NhsxError
from . import run as runner
from .presets import DEFAULT_PRESET, PRESETS, Settings

router = APIRouter()
SECTION = "silence"


@router.get("/info")
def info() -> dict:
    return {
        "presets": {name: value.to_dict() for name, value in PRESETS.items()},
        "defaultPreset": DEFAULT_PRESET,
        "settings": {**PRESETS[DEFAULT_PRESET].to_dict(), **saved.section(SECTION)},
    }


@router.post("/preview")
def preview(body: dict) -> dict:
    session = str(body.get("session") or "").strip()
    if not session:
        raise HTTPException(400, "Valitse istuntotiedosto.")
    settings = Settings.from_dict(body.get("settings"))
    # Esikatselu ei mittaa tasoa. Mittaus purkaisi jokaisen raidan levyltä,
    # ja liukusäätimen vieressä oleva luku, joka ilmestyy minuutin päästä,
    # ei ole esikatselu. Ajossa taso mitataan; ero sanotaan käyttöliittymässä.
    quick = replace(settings, rms=False)
    try:
        result = runner.preview(session, quick, extra_dir=str(body.get("audioDir") or ""))
    except NhsxError as exc:
        raise HTTPException(400, str(exc)) from exc
    result["rmsSkipped"] = settings.rms
    return result


@router.post("/run")
def start(body: dict) -> dict:
    session = str(body.get("session") or "").strip()
    if not session:
        raise HTTPException(400, "Valitse istuntotiedosto.")
    settings = Settings.from_dict(body.get("settings"))
    audio_dir = str(body.get("audioDir") or "")
    saved.save(SECTION, settings.to_dict())

    def work(progress):
        return runner.run(session, settings, progress, extra_dir=audio_dir)

    try:
        job = RUNNER.start(SECTION, session, work)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return job.snapshot()
