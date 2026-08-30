"""Moduulirekisteri.

Sateenvarjo: yksi ikkuna, monta työkalua. Moduuli on tässä neljä asiaa —
avain, nimi, oma reititin ja oma selainskripti. Uusi moduuli (esimerkiksi
automixerin ääniketju) on yksi merkintä tässä listassa, yksi
``APIRouter`` ja yksi ``mod_*.js``; palvelin ja kuori eivät muutu.

Moduulit eivät tunne toisiaan. Yhteistä on vain ``.nhsx``-tiedosto ja
työjono, ja kumpikin on rekisterin ulkopuolella.
"""

from __future__ import annotations

from dataclasses import dataclass

from .merge import api as merge_api
from .script import api as script_api
from .silence import api as silence_api
from .transcribe import api as transcribe_api


@dataclass(frozen=True)
class ModuleSpec:
    key: str
    title_fi: str
    title_en: str
    blurb_fi: str
    blurb_en: str
    script: str
    router: object

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "title": {"fi": self.title_fi, "en": self.title_en},
            "blurb": {"fi": self.blurb_fi, "en": self.blurb_en},
            "script": self.script,
        }


MODULES: tuple[ModuleSpec, ...] = (
    ModuleSpec(
        key="transcribe",
        title_fi="Litterointi",
        title_en="Transcribe",
        blurb_fi="Whisper kirjoittaa äänipoolin sanat aikoineen istuntoon.",
        blurb_en="Whisper writes the pool's words, with timings, into the session.",
        script="mod_transcribe.js",
        router=transcribe_api.router,
    ),
    ModuleSpec(
        key="silence",
        title_fi="Vaimennus",
        title_en="Silence",
        blurb_fi="Litteroinnin perusteella hiljaiset kohdat vaiti raidoilta.",
        blurb_en="Mutes what nobody says, track by track, from the transcription.",
        script="mod_silence.js",
        router=silence_api.router,
    ),
    ModuleSpec(
        key="script",
        title_fi="Käsikirjoitus",
        title_en="Script",
        blurb_fi="Litteroinnista luettava markdown puhujineen ja aikaleimoineen.",
        blurb_en="A readable markdown transcript, with speakers and time codes.",
        script="mod_script.js",
        router=script_api.router,
    ),
    ModuleSpec(
        key="merge",
        title_fi="Litteroinnin siirto",
        title_en="Merge transcription",
        blurb_fi="Kopioi litteroinnin leikkaamattomasta istunnosta leikattuun.",
        blurb_en="Carries the transcription from the uncut session into the edited one.",
        script="mod_merge.js",
        router=merge_api.router,
    ),
)


def to_list() -> list[dict]:
    return [m.to_dict() for m in MODULES]
