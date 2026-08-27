"""mlx-whisper: Whisper Applen MLX:llä, eli Metalilla näytönohjaimella.

Tämä on Macin nopein tapa ajaa Whisperiä sanatarkoilla aikaleimoilla.
CTranslate2:ssa (faster-whisper) ei ole Metal-taustaa lainkaan, joten se jää
Macilla suorittimelle; MLX ajaa saman mallin GPU:lla ilman erillistä
kääntämistä tai muunnosta.

Ääni annetaan valmiiksi puretuna taulukkona eikä polkuna. mlx-whisperin oma
``load_audio`` kutsuu ffmpegiä **PATHista**, ja pakatussa sovelluksessa
PATHissa ei ole mitään — binääri on paketin sisällä. Polkua antamalla
litterointi toimisi kehityskoneella ja kaatuisi valmiissa .app-paketissa.
"""

from __future__ import annotations

import numpy as np

from ...jobs import Cancelled, Progress
from ..models import model_choice
from ..options import Options
from .base import Backend, BackendInfo, TranscriptResult, words_from_segments

# Kuinka pitkä hiljaisuus saa olla ennen kuin sitä epäillään keksityksi
# puheeksi. mlx-whisperissä ei ole VAD-suodinta; tämä on sen tilalla ja
# vaikuttaa samaan ongelmaan: taukoon ilmestyvään «Tekstitys: YLE».
HALLUCINATION_SILENCE_S = 2.0


class _Bar:
    """tqdm:n paikalle pujahtava palkki, joka kertoo osuuden eteenpäin.

    mlx-whisperin ``transcribe`` ei tarjoa takaisinkutsua edistymiselle. Se
    kuitenkin päivittää tqdm-palkkia kehysten tahdissa, ja tuntimittainen
    jakso ilman mitään merkkiä etenemisestä on käyttöliittymä joka näyttää
    jumiutuneelta. Vaihdamme moduulin ``tqdm``-attribuutin — ei globaalia
    tqdm-pakettia — ja luemme saman luvun.

    Peruutus nostetaan täältä: se on ainoa kohta jossa oma koodi ajaa kesken
    yhden tiedoston litteroinnin.
    """

    def __init__(self, *_args, total=None, on=None, check=None, **_kwargs):
        self.total = total or 0
        self.n = 0
        self._on = on
        self._check = check

    def update(self, n=1):
        self.n += n or 0
        if self._check is not None:
            self._check()
        if self._on is not None and self.total:
            self._on(min(1.0, self.n / self.total))

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _TqdmShim:
    """Näyttää moduulin silmissä tqdm-paketilta: ``tqdm.tqdm(...)``."""

    def __init__(self, factory):
        self.tqdm = factory


class MlxWhisper(Backend):
    key = "mlx"
    label = "mlx-whisper (Metal)"

    def info(self) -> BackendInfo:
        try:
            import mlx_whisper  # noqa: F401
        # Puuttuva paketti on tavallisin, mutta mikä tahansa tuontivirhe
        # tarkoittaa samaa: tätä moottoria ei voi tarjota.
        except Exception as exc:
            return BackendInfo(
                key=self.key,
                label=self.label,
                available=False,
                reason=f"Ei asennettu ({type(exc).__name__}). Vaatii Apple Siliconin.",
                install="uv sync --all-packages --extra mlx",
            )
        return BackendInfo(
            key=self.key,
            label=self.label,
            available=True,
            device="Apple GPU (Metal)",
            install="uv sync --all-packages --extra mlx",
        )

    def transcribe(
        self, samples: np.ndarray, options: Options, progress: Progress
    ) -> TranscriptResult:
        import sys

        import mlx_whisper

        # Moduuli haetaan ``sys.modules``ista eikä attribuuttina. Paketin
        # ``__init__`` tekee ``from .transcribe import transcribe``, joten
        # ``mlx_whisper.transcribe`` on **funktio** ja varjostaa
        # samannimisen alimoduulin — myös ``import mlx_whisper.transcribe
        # as x`` päätyy funktioon. Attribuutilta ei löydy ``tqdm``ia, joten
        # paikkaus ei kiinnity, edistyminen ei näy eikä mikään kerro siitä.
        transcribe_module = sys.modules.get("mlx_whisper.transcribe")

        repo = model_choice(options.model).mlx

        decode: dict = {}
        if options.fillers:
            # Tyhjä lista = älä vaimenna mitään. Näin täytesanat ja
            # äänteet jäävät mukaan; ne ovat puhetta ja leikkuri tarvitsee ne.
            decode["suppress_tokens"] = []
            decode["suppress_blank"] = False

        original = getattr(transcribe_module, "tqdm", None)
        patched = original is not None and hasattr(original, "tqdm")
        if patched:
            def factory(*args, **kwargs):
                return _Bar(
                    *args,
                    total=kwargs.get("total"),
                    on=progress.fraction,
                    check=progress.check,
                    **{k: v for k, v in kwargs.items() if k != "total"},
                )

            transcribe_module.tqdm = _TqdmShim(factory)
        else:
            # Ylävirta muuttui. Litterointi toimii yhä, edistyminen ei näy
            # tiedoston sisällä — se on haitta, ei virhe.
            progress.log("mlx-whisperin edistymispalkkia ei tunnistettu.")
            progress.fraction(None)

        try:
            result = mlx_whisper.transcribe(
                samples,
                path_or_hf_repo=repo,
                language=options.language or None,
                word_timestamps=True,
                verbose=False,
                initial_prompt=options.initial_prompt or None,
                hallucination_silence_threshold=(
                    HALLUCINATION_SILENCE_S if options.vad else None
                ),
                **decode,
            )
        except Cancelled:
            raise
        finally:
            if patched:
                transcribe_module.tqdm = original

        segments = list(result.get("segments") or ())
        return TranscriptResult(
            words=words_from_segments(segments),
            text=str(result.get("text", "")),
            language=str(result.get("language", options.language or "")),
            raw=result,
        )
