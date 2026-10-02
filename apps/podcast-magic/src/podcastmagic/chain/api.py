"""Ketjumoduulin rajapinta selaimelle."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import settings as saved
from ..jobs import RUNNER
from . import mixer
from . import run as runner

router = APIRouter()
SECTION = "chain"

#: Voimakkuuden kelvolliset rajat. Ei mittaus vaan järkevyystarkistus:
#: kirjoitusvirhe («-61» «-16»:n sijaan) ei saa tuottaa tuntia työtä ja
#: hiljaista tiedostoa. Podcastien tavoitteet ovat −14…−19 LUFS.
LUFS_RANGE = (-40.0, -5.0)


def _target(raw) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return runner.DEFAULT_TARGET_LUFS
    return value


@router.get("/info")
def info() -> dict:
    stored = saved.section(SECTION)
    available = mixer.command() is not None
    return {
        "steps": runner.Steps.from_dict(stored.get("steps")).to_dict(),
        "targetLufs": _target(stored.get("targetLufs", runner.DEFAULT_TARGET_LUFS)),
        "mixer": {
            "available": available,
            "reason": "" if available else mixer.MISSING,
            "install": mixer.INSTALL,
        },
    }


@router.post("/run")
def start(body: dict) -> dict:
    session = str(body.get("session") or "").strip()
    if not session:
        raise HTTPException(400, "Valitse istuntotiedosto.")
    steps = runner.Steps.from_dict(body.get("steps"))
    if not steps.chosen:
        raise HTTPException(400, "Valitse ainakin yksi vaihe.")
    if steps.mix and mixer.command() is None:
        raise HTTPException(400, mixer.MISSING)
    target = _target(body.get("targetLufs"))
    if not LUFS_RANGE[0] <= target <= LUFS_RANGE[1]:
        raise HTTPException(400, f"Voimakkuuden pitää olla {LUFS_RANGE[0]:.0f}…{LUFS_RANGE[1]:.0f} LUFS.")
    audio_dir = str(body.get("audioDir") or "")
    force = bool(body.get("force"))
    saved.save(SECTION, {"steps": steps.to_dict(), "targetLufs": target})

    options, settings = runner.saved_settings()

    def work(progress):
        return runner.run(
            session, steps, options, settings, progress,
            audio_dir=audio_dir, force=force, target_lufs=target,
        )

    try:
        job = RUNNER.start(SECTION, session, work)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return job.snapshot()
