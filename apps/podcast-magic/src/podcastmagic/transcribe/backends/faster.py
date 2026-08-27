"""faster-whisper: CTranslate2. Sama moottori kuin Colab-muistikirjassa.

Macilla tämä ajaa suorittimella. CTranslate2:ssa ei ole Metal-taustaa, joten
Applen näytönohjain jää käyttämättä — muistikirjan ``--compute_type auto`` ei
tuo Macilla mitään esiin. Siksi tämä ei ole oletus vaan varakone:

* Intel-Macilla, jossa MLX ei toimi lainkaan
* saman tiedoston ajamiseen toisella moottorilla, kun tulos näyttää oudolta
* CI-ajurilla, jolla ei ole Applen näytönohjainta

Malli ladataan kerran ja jää muistiin. Painojen luku on kymmeniä sekunteja ja
saman mallin lataaminen jokaiselle tiedostolle olisi useimmissa ajoissa
enemmän aikaa kuin itse litterointi.
"""

from __future__ import annotations

import threading

import numpy as np

from ...audio import SAMPLE_RATE
from ...jobs import Progress
from ..models import model_choice
from ..options import Options
from .base import Backend, BackendInfo, TranscriptResult, words_from_segments

_MODELS: dict[tuple, object] = {}
_MODELS_LOCK = threading.Lock()


class FasterWhisper(Backend):
    key = "faster-whisper"
    label = "faster-whisper (CPU)"

    def info(self) -> BackendInfo:
        try:
            import faster_whisper  # noqa: F401
        # Asentamaton paketti on tavallisin, mutta mikä tahansa tuontivirhe
        # tarkoittaa samaa: tätä moottoria ei voi tarjota.
        except Exception as exc:
            return BackendInfo(
                key=self.key,
                label=self.label,
                available=False,
                reason=f"Ei asennettu ({type(exc).__name__}).",
                install="uv sync --all-packages --extra faster",
            )
        return BackendInfo(
            key=self.key, label=self.label, available=True, device="CPU (int8)",
            install="uv sync --all-packages --extra faster",
        )

    def _model(self, name: str, progress: Progress):
        from faster_whisper import WhisperModel

        key = (name, "cpu", "int8")
        with _MODELS_LOCK:
            model = _MODELS.get(key)
            if model is None:
                progress.log(f"Ladataan malli {name}…")
                model = WhisperModel(name, device="cpu", compute_type="int8")
                _MODELS[key] = model
        return model

    def transcribe(
        self, samples: np.ndarray, options: Options, progress: Progress
    ) -> TranscriptResult:
        model = self._model(model_choice(options.model).faster, progress)
        total = max(1e-6, len(samples) / SAMPLE_RATE)

        segments_iter, info = model.transcribe(
            samples,
            language=options.language or None,
            word_timestamps=True,
            vad_filter=options.vad,
            initial_prompt=options.initial_prompt or None,
            # Sama kuin muistikirjan --suppress_tokens "" --suppress_blank False.
            suppress_tokens=[] if options.fillers else [-1],
            suppress_blank=not options.fillers,
        )

        # Segmentit tulevat generaattorista sitä mukaa kun ne valmistuvat.
        # Siinä on tämän moottorin ainoa etu edistymisen kannalta: osuus on
        # mitattu eikä arvattu.
        segments: list[dict] = []
        for segment in segments_iter:
            progress.check()
            segments.append(
                {
                    "id": segment.id,
                    "start": segment.start,
                    "end": segment.end,
                    "text": segment.text,
                    "words": [
                        {"word": w.word, "start": w.start, "end": w.end, "probability": w.probability}
                        for w in (segment.words or ())
                    ],
                }
            )
            progress.fraction(segment.end / total)

        raw = {
            "text": "".join(s["text"] for s in segments),
            "segments": segments,
            "language": info.language,
        }
        return TranscriptResult(
            words=words_from_segments(segments),
            text=raw["text"],
            language=info.language,
            raw=raw,
        )
