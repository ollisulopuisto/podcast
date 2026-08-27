"""Litteroinnin asetukset yhtenä oliona."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .models import DEFAULT_MODEL


@dataclass
class Options:
    """Mitä käyttöliittymästä tulee moottorille.

    ``fillers``: Colab-muistikirjan ``--suppress_tokens "" --suppress_blank
    False``. Whisper on koulutettu siistimään puheen, ja litteroinnin ainoa
    käyttötarkoitus tässä on löytää missä kohtaa ääntä puhutaan — «tota noin»
    on puhetta siinä missä muukin, ja ilman sitä leikkuri vaientaa sen.

    ``vad``: hiljaisuuden poisto ennen tunnistusta. Estää mallia keksimästä
    sanoja tauolle. faster-whisperissä oma suodin, mlx-whisperissä
    ``hallucination_silence_threshold``.
    """

    backend: str = "auto"
    model: str = DEFAULT_MODEL
    language: str = "fi"
    fillers: bool = True
    vad: bool = True
    initial_prompt: str = ""

    @classmethod
    def from_dict(cls, raw: dict | None) -> "Options":
        raw = raw or {}
        known = {f: getattr(cls(), f) for f in cls.__dataclass_fields__}
        out = {}
        for name, default in known.items():
            value = raw.get(name, default)
            if isinstance(default, bool):
                out[name] = bool(value)
            else:
                out[name] = str(value or "").strip() or default
        # Tyhjä kieli tarkoittaa automaattista tunnistusta, ja se on eri asia
        # kuin oletus «fi» — siksi se ei saa pudota oletukselle yllä.
        if "language" in raw:
            out["language"] = str(raw.get("language") or "").strip()
        if "initial_prompt" in raw:
            out["initial_prompt"] = str(raw.get("initial_prompt") or "")
        return cls(**out)

    def to_dict(self) -> dict:
        return asdict(self)

    def fingerprint(self) -> str:
        """Tunniste, joka erottaa eri asetuksilla tehdyt litteroinnit.

        Välimuisti ohittaa jo litteroidun tiedoston. Ilman tunnistetta mallin
        vaihtaminen ei tekisi mitään, koska vanha JSON löytyisi levyltä.
        """
        return "-".join(
            [
                self.model,
                self.language or "auto",
                "fill" if self.fillers else "clean",
                "vad" if self.vad else "raw",
            ]
        )
