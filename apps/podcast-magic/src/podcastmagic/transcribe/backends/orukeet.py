"""Paikallinen Orukeet. Sanat kohdistetaan CTC:llä, sillä moottori palauttaa lauseajat."""

from __future__ import annotations

import importlib.util
import json
import os
import re
from pathlib import Path

import numpy as np

from ...jobs import Progress
from ..options import Options
from .audio import wav_file
from .base import Backend, BackendInfo, TranscriptResult, words_from_segments

RECEIPT = Path.home() / ".cache" / "orukeet" / "installation.json"
INSTALL = (
    "uv sync --all-packages --extra orukeet && "
    f"orukeet install --device auto --cache {RECEIPT.parent} --output {RECEIPT}"
)


def _receipt_path() -> Path:
    return Path(os.environ.get("ORUKEET_INSTALLATION", RECEIPT))


def _with_word_seeds(segments: list[dict]) -> list[dict]:
    """Lisää CTC:lle sanat ja lauseen rajat ilman keksittyjä sanakohtaisia aikoja."""
    seeded = []
    for segment in segments:
        start = float(segment["start"])
        end = float(segment["end"])
        words = [
            {"word": word, "start": start, "end": end}
            for word in re.findall(r"\S+", str(segment.get("text", "")))
        ]
        if words:
            seeded.append({**segment, "words": words})
    return seeded


class Orukeet(Backend):
    key = "orukeet"
    label = "Orukeet (paikallinen)"

    def info(self) -> BackendInfo:
        receipt = _receipt_path()
        try:
            import orukeet  # noqa: F401
        except Exception as exc:
            return BackendInfo(
                self.key, self.label, False,
                reason=f"Orukeet SDK ei ole asennettu ({type(exc).__name__}).",
                install=INSTALL,
            )
        if not receipt.is_file():
            return BackendInfo(
                self.key, self.label, False,
                reason=f"Orukeetin asennuskuitti puuttuu: {receipt}", install=INSTALL,
            )
        missing_aligner = [
            name for name in ("torch", "torchaudio")
            if importlib.util.find_spec(name) is None
        ]
        if missing_aligner:
            return BackendInfo(
                self.key, self.label, False,
                reason=(
                    "Orukeet vaatii CTC-sanakohdistuksen, mutta puuttuu: "
                    + ", ".join(missing_aligner)
                ),
                install=(
                    "uv run --package podcast-magic --with torch==2.8.0 "
                    "--with torchaudio==2.8.0 podcast-magic"
                ),
            )
        return BackendInfo(
            self.key, self.label, True, device="Metal / CUDA / CPU (asennuskuitti)",
            install=INSTALL,
        )

    def transcribe(
        self, samples: np.ndarray, options: Options, progress: Progress
    ) -> TranscriptResult:
        from orukeet import Orukeet as Engine

        config = json.loads(_receipt_path().read_text(encoding="utf-8-sig"))
        progress.log("Ladataan Orukeet…")
        progress.fraction(None)
        with wav_file(samples) as path, Engine(
            config["model"], config["runtime"], device=config["device"]
        ) as engine:
            progress.check()
            response = engine.transcribe(path)
        segments = _with_word_seeds(list(response.get("segments") or ()))
        progress.check()
        progress.fraction(1.0)
        raw = {**response, "segments": segments}
        return TranscriptResult(
            words=words_from_segments(segments),
            text=str(response.get("text", "")),
            language=str(response.get("language", options.language)),
            raw=raw,
        )
