"""Kohdistus: Whisperin sanat pakotetaan ääneen, ja sanojen alut korjataan.

Laskenta on ``packages/wordalign``issa (yksi tiedosto): mittaukset, säännöt ja
niiden perustelut ovat sen ohjeessa. Colab-skripti lataa saman tiedoston, joten
kopiota ei ole. Tämä moduuli on sovelluksen puoli: ``Word``-muoto, oma
välimuisti ja asennusohje.

Kohdistus ajetaan **jälkivaiheena**: se lukee Whisperin raakatuloksen
(``segments[].words[]``), joten sama JSON kelpaa kaikille moottoreille eikä
litterointia tarvitse ajaa uudestaan. Tulos on oma välimuistinsa
(``cache_path``), koska kohdistus vaihtuu Whisperistä riippumatta.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np

from wordalign import (
    GROUP_GAP_S,
    GROUP_MAX_S,
    MAX_EARLY_S,
    MAX_LATE_S,
    PAD_S,
    RATE,
    SPLIT_GAP_S,
    VERSION,
    AlignerUnavailable,
    align_raw,
    align_words,
    groups_of,
    normalise_word,
    refined,
    split_at_pauses,
    window,
)
from wordalign import make_aligner as _make_aligner
from wordalign import summarize as _summarize

from ..nhsx import Word
from .options import Options

__all__ = [
    "GROUP_GAP_S",
    "GROUP_MAX_S",
    "INSTALL",
    "MAX_EARLY_S",
    "MAX_LATE_S",
    "PAD_S",
    "RATE",
    "SPLIT_GAP_S",
    "VERSION",
    "AlignerUnavailable",
    "align_raw",
    "align_words",
    "availability",
    "cache_path",
    "groups_of",
    "make_aligner",
    "normalise_word",
    "refine",
    "refined_words",
    "split_at_pauses",
    "summarize",
    "window",
]

#: Asennus. Ei ole ``--extra``: torch on jo ``fcp-subs-whisper``in riippuvuus eri
#: versiolla (>=2.5.1, lukossa 2.13), ja kohdistin tarvitsee torchaudion 2.8:n,
#: koska ``forced_align`` poistuu 2.9:stä. Lisäriippuvuus pakottaisi toisen
#: sovelluksen torchin toiseen versioon hiljaa. ``--with`` ei kosketa lukkoa.
INSTALL = "uv run --package podcast-magic --with torch==2.8.0 --with torchaudio==2.8.0 podcast-magic"


def _installed(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def availability() -> dict:
    """Onko kohdistin asennettu. Näytetään käyttöliittymässä ennen ajoa."""
    missing = [name for name in ("torch", "torchaudio") if not _installed(name)]
    if missing:
        return {
            "available": False,
            "reason": f"puuttuu: {', '.join(missing)}",
            "install": INSTALL,
        }
    return {"available": True, "reason": "", "install": INSTALL}


def make_aligner():
    """Kirjaston kohdistin sovelluksen asennusohjeella virheviestissä."""
    return _make_aligner(INSTALL)


def refined_words(rows: list[dict]) -> list[Word]:
    """Kohdistetut sanat istuntoon (``wordalign.refined``); nollapituinen sana saa lattian."""
    return [
        Word(text=r["word"], start=r["start"], length=max(0.02, r["end"] - r["start"]))
        for r in refined(rows)
    ]


def summarize(rows: list[dict], rejected: list[str]) -> dict:
    """Mitä kohdistus teki; ``cache_error`` täyttyy vasta välimuistia kirjoitettaessa."""
    return {**_summarize(rows, rejected), "cache_error": None}


def cache_path(directory: Path, audio_path: str, options: Options) -> Path:
    """Kohdistuksen välimuisti: äänen nimi, Whisperin tunniste ja kohdistuksen versio.

    Whisperin tunniste on nimessä, koska kohdistus on tehty sen sanoista; toisella
    mallilla tehdyistä sanoista tämä olisi väärä tulos.
    """
    stem = Path(audio_path).stem
    return Path(directory) / f"{stem}.{options.fingerprint()}.align-{VERSION}.json"


def _load(path: Path, source: list) -> tuple[list[dict], list[str]] | None:
    """Välimuisti, jos se on samasta versiosta ja samoista sanoista; muuten ``None``."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("version") != VERSION:
        return None
    if data.get("source") != source:
        return None
    rows, rejected = data.get("rows"), data.get("rejected")
    if not isinstance(rows, list) or not isinstance(rejected, list):
        return None
    return rows, rejected


def refine(raw: dict, samples: np.ndarray, get_aligner, cache: Path | None = None):
    """Whisperin raakatuloksesta korjatut sanat ja yhteenveto.

    ``get_aligner()`` palauttaa kohdistimen ja ``samples`` äänen (16 kHz float32
    -taulukko tai sen palauttava funktio) vasta kun niitä tarvitaan, joten
    välimuistista luettaessa mallia ei ladata eikä ääntä pureta. Välimuisti
    kelpaa vain jos se on tehty samoista sanoista samalla versiolla.
    """
    flat = [w for group in groups_of(raw) for w in group]
    if not flat:
        return [], summarize([], [])
    source = [[w["word"], w["start"]] for w in flat]
    cached = _load(cache, source) if cache else None
    if cached is not None:
        rows, rejected = cached
        return refined_words(rows), summarize(rows, rejected)
    rejected: list[str] = []
    audio = samples() if callable(samples) else samples
    rows = align_raw(raw, audio, get_aligner(), errors=rejected)
    summary = summarize(rows, rejected)
    if cache:
        try:
            Path(cache).write_text(
                json.dumps(
                    {
                        "version": VERSION,
                        "source": source,
                        "rows": rows,
                        "rejected": rejected,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except OSError as exc:
            summary["cache_error"] = str(exc)
    return refined_words(rows), summary
