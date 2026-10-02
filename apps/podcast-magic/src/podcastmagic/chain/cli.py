"""Koko ketju komentoriviltä: ``podcast-magic jakso.nhsx --chain``.

Sama ajo kuin napilla, ilman ikkunaa. Vaiheiden asetukset tulevat samasta
paikasta kuin napilla, joten komento ja nappi eivät voi tehdä eri asioita.
"""

from __future__ import annotations

import sys

from ..jobs import Cancelled, Job, Progress
from . import run as runner


def parse_steps(text: str) -> runner.Steps:
    """``litterointi``-tyyppiset nimet eivät kelpaa: nimet ovat vaiheiden avaimet."""
    names = [part.strip() for part in text.split(",") if part.strip()]
    unknown = [name for name in names if name not in runner.LABELS]
    if unknown:
        raise ValueError(
            f"Tuntematon vaihe: {', '.join(unknown)}. Vaihtoehdot: {', '.join(runner.LABELS)}."
        )
    return runner.Steps(**{name: name in names for name in runner.LABELS})


def execute(
    session: str,
    steps: runner.Steps,
    target_lufs: float = runner.DEFAULT_TARGET_LUFS,
    audio_dir: str = "",
    force: bool = False,
) -> int:
    """Ajaa ketjun ja palauttaa poistumiskoodin. Lokirivit tulevat terminaaliin."""
    options, settings = runner.saved_settings()
    progress = Progress(Job(id=1, module="chain", label=session))
    try:
        result = runner.run(
            session, steps, options, settings, progress,
            audio_dir=audio_dir, force=force, target_lufs=target_lufs,
        )
    except Cancelled:
        print("Keskeytetty.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Epäonnistui: {exc}", file=sys.stderr)
        return 1
    if result.get("written"):
        print(f"Valmis: {result['written']}")
    return 0
