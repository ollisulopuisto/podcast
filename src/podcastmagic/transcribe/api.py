"""Litterointimoduulin rajapinta selaimelle."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import settings as saved
from ..jobs import RUNNER
from ..nhsx import NhsxError
from . import run as runner
from .backends import infos
from .models import DEFAULT_MODEL, MODELS
from .options import Options

router = APIRouter()
SECTION = "transcribe"


@router.get("/info")
def info() -> dict:
    return {
        "backends": [
            {
                "key": b.key,
                "label": b.label,
                "available": b.available,
                "reason": b.reason,
                "device": b.device,
                "install": b.install,
            }
            for b in infos()
        ],
        "models": [
            {
                "key": m.key,
                "label": m.label,
                "hint": {"fi": m.hint_fi, "en": m.hint_en},
            }
            for m in MODELS
        ],
        "defaultModel": DEFAULT_MODEL,
        "options": {**Options().to_dict(), **saved.section(SECTION)},
    }


@router.post("/plan")
def plan(body: dict) -> dict:
    session = str(body.get("session") or "").strip()
    if not session:
        raise HTTPException(400, "Valitse istuntotiedosto.")
    options = Options.from_dict(body.get("options"))
    try:
        result = runner.plan(
            session,
            options,
            audio_dir=str(body.get("audioDir") or ""),
            force=bool(body.get("force")),
        )
    except NhsxError as exc:
        raise HTTPException(400, str(exc)) from exc
    return result.to_dict()


@router.post("/run")
def start(body: dict) -> dict:
    session = str(body.get("session") or "").strip()
    if not session:
        raise HTTPException(400, "Valitse istuntotiedosto.")
    options = Options.from_dict(body.get("options"))
    audio_dir = str(body.get("audioDir") or "")
    force = bool(body.get("force"))
    saved.save(SECTION, options.to_dict())

    def work(progress):
        return runner.run(session, options, progress, audio_dir=audio_dir, force=force)

    try:
        job = RUNNER.start(SECTION, session, work)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return job.snapshot()
