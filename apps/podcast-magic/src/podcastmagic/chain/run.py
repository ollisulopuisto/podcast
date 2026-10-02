"""Ketjun ajo: kukin vaihe lukee edellisen kirjoittaman istunnon.

Ketju ei tee mitään itse. Se kutsuu samoja ``run``-funktioita kuin
välilehdet, samoilla asetuksilla jotka välilehdillä on viimeksi tallennettu,
ja antaa jokaiselle sen, minkä edellinen kirjoitti. Siksi ketjun tulos on
sama kuin vaiheiden ajo käsin peräkkäin — eikä ketjulla ole omia säätimiä
jotka voisivat ajautua erilleen välilehtien omista.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..jobs import Progress
from ..silence import run as silence_run
from ..silence.presets import Settings
from ..transcribe import run as transcribe_run
from ..transcribe.options import Options
from . import mixer

DEFAULT_TARGET_LUFS = -16.0

LABELS = {"transcribe": "Litterointi", "silence": "Vaimennus", "mix": "Miksaus"}


@dataclass(frozen=True)
class Steps:
    transcribe: bool = True
    silence: bool = True
    mix: bool = True

    @classmethod
    def from_dict(cls, raw: dict | None) -> "Steps":
        raw = raw or {}
        base = cls()
        return cls(**{name: bool(raw.get(name, getattr(base, name))) for name in LABELS})

    def to_dict(self) -> dict:
        return {name: getattr(self, name) for name in LABELS}

    @property
    def chosen(self) -> list[str]:
        return [name for name in LABELS if getattr(self, name)]


class StageProgress:
    """Vaiheen edistyminen ketjun mittakaavassa.

    Vaihe kertoo oman «2/5»:nsä ja oman osuutensa. Ne eivät saa kirjoittaa
    ketjun «1/3»:n päälle: palkki hyppäisi taaksepäin jokaisen vaiheen
    alussa. Siksi vaiheen luvut jäävät tähän ja työlle annetaan ketjun
    vaihe ja vaiheen sisäinen osuus.
    """

    def __init__(self, progress: Progress, label: str, index: int, total: int) -> None:
        self._progress = progress
        self._label = label
        self._index = index
        self._total = total
        self._done = 0
        self._of = 0

    def log(self, message: str) -> None:
        self._progress.log(message)

    def check(self) -> None:
        self._progress.check()

    @property
    def cancelled(self) -> bool:
        return self._progress.cancelled

    def begin(self) -> None:
        self._progress.step(self._label, done=self._index, total=self._total)
        self._progress.fraction(0.0)

    def step(self, label: str, done: int | None = None, total: int | None = None) -> None:
        if done is not None:
            self._done = done
        if total is not None:
            self._of = total
        self._progress.step(f"{self._label}: {label}", done=self._index, total=self._total)
        self._progress.fraction(self._done / self._of if self._of else None)

    def fraction(self, value: float | None) -> None:
        if value is None:
            self._progress.fraction(None)
        elif self._of:
            self._progress.fraction((self._done + value) / self._of)
        else:
            self._progress.fraction(value)


def run(
    session_path: str,
    steps: Steps,
    options: Options,
    settings: Settings,
    progress: Progress,
    audio_dir: str = "",
    force: bool = False,
    target_lufs: float = DEFAULT_TARGET_LUFS,
) -> dict:
    """Ajaa valitut vaiheet järjestyksessä ja palauttaa viimeisen tuloksen."""
    chosen = steps.chosen
    if not chosen:
        raise RuntimeError("Valitse ainakin yksi vaihe.")
    # Miksain tarkistetaan ennen kuin mitään ajetaan. Litterointi kestää
    # tunnin, eikä puuttuvaa miksainta saa huomata vasta sen jälkeen.
    if steps.mix and mixer.command() is None:
        raise RuntimeError(mixer.MISSING)

    current = session_path
    written = ""
    records: list[dict] = []
    total = len(chosen)

    for index, name in enumerate(chosen):
        progress.check()
        stage = StageProgress(progress, LABELS[name], index, total)
        stage.begin()
        progress.log(f"— {LABELS[name]} ({index + 1}/{total}) —")

        if name == "transcribe":
            result = transcribe_run.run(
                current, options, stage, audio_dir=audio_dir, force=force
            )
            produced = result.get("written") or ""
            if not produced:
                # Poolin kaikki tiedostot oli jo litteroitu. Se ei pysäytä
                # ketjua: jäljellä olevat vaiheet ovat täysin tehtävissä.
                progress.log("Litteroitavaa ei ollut — jatketaan istunnolla sellaisenaan.")
        elif name == "silence":
            result = silence_run.run(current, settings, stage, extra_dir=audio_dir)
            produced = result.get("written") or ""
        else:
            produced = mixer.run(current, target_lufs, stage)
            result = {"written": produced}

        records.append({"stage": name, "written": produced})
        if produced:
            written = produced
            if name != "mix":
                current = produced

    return {"written": written, "stages": records}
