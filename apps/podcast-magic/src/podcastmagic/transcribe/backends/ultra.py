"""Parakeet Ultra ajettuna Moondream Photonilla."""

from __future__ import annotations

import numpy as np

from ...jobs import Progress
from ..options import Options
from .audio import wav_file
from .base import Backend, BackendInfo, TranscriptResult, words_from_segments

MODEL = "moondream/parakeet-ultra"


class ParakeetUltra(Backend):
    key = "parakeet-ultra"
    label = "Parakeet Ultra (Photon)"

    def info(self) -> BackendInfo:
        try:
            import moondream  # noqa: F401
        except Exception as exc:
            return BackendInfo(
                self.key, self.label, False,
                reason=f"Moondream Photon ei ole asennettu ({type(exc).__name__}).",
                install="uv sync --all-packages --extra ultra",
            )
        return BackendInfo(
            self.key, self.label, True, device="Photon (automaattinen laitevalinta)",
            install="uv sync --all-packages --extra ultra",
        )

    def transcribe(
        self, samples: np.ndarray, options: Options, progress: Progress
    ) -> TranscriptResult:
        import moondream as md

        progress.log(f"Ladataan {MODEL} Photonilla…")
        progress.fraction(None)
        with wav_file(samples) as path, md.photon(MODEL) as speech:
            progress.check()
            raw = speech.transcribe(audio=path, timestamps="word")
        progress.check()
        segments = list(raw.get("segments") or ())
        progress.fraction(1.0)
        return TranscriptResult(
            words=words_from_segments(segments),
            text=str(raw.get("text", "")),
            language=str(raw.get("language", options.language)),
            raw={**raw, "segments": segments},
        )
