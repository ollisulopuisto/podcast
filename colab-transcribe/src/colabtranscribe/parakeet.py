"""Parakeet MLX -litterointitausta paikalliseen ajoon Apple Siliconilla.

Tämä moduuli toteuttaa vaihtoehtoisen, paikallisen litterointitaustan
``colab-transcribelle``. Se käyttää Applen Metal-kiihdytettyä ``parakeet-mlx``-
kirjastoa ja tuottaa täsmälleen saman ``<nimi>.words.json``-sopimuksen
(``docs/KUULAS-COLAB.md``) kuin Colab-ajo ilman pilvipalvelun käynnistysviivettä
tai tiedonsiirtoa.
"""

from __future__ import annotations

import json
import platform
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from . import events
from .colab import pipeline

# Match parakeet-mlx CLI defaults. Its Python API defaults to unchunked
# whole-file attention, which can request tens of GB for long recordings.
CHUNK_SECONDS = 120.0
OVERLAP_SECONDS = 15.0

if TYPE_CHECKING:
    from .options import RunOptions


def is_available() -> tuple[bool, str]:
    """Tarkistaa onko Parakeet MLX käytettävissä tällä laitteistolla.

    Vaatii macOS:n, Apple Silicon -suorittimen (arm64) sekä asennetun
    ``parakeet-mlx``-kirjaston.
    """
    if platform.system() != "Darwin":
        return (
            False,
            f"Parakeet MLX vaatii macOS-käyttöjärjestelmän (nykyinen: {platform.system()}).",
        )
    if platform.machine() != "arm64":
        return (
            False,
            f"Parakeet MLX vaatii Apple Silicon (arm64) -suorittimen (nykyinen: {platform.machine()}).",
        )
    try:
        import parakeet_mlx  # noqa: F401

        return True, ""
    except ImportError:
        return (
            False,
            "parakeet-mlx ei ole asennettu. Asenna se: uv pip install parakeet-mlx "
            "(tai uv sync --extra parakeet).",
        )


def transcribe_file(
    audio_path: Path | str,
    model_name: str = "mlx-community/parakeet-tdt-0.6b-v3",
) -> dict:
    """Litteroi yhden äänitiedoston Parakeet MLX:llä ja palauttaa raw-rakenteen.

    Yhdistää SentencePiece-alisanat ja välimerkit kokonaisiksi sanoiksi aikoineen.
    Palautettu rakenne noudattaa Whisper-yhteensopivaa muotoa
    ``{"segments": [{"words": [{"word": str, "start": float, "end": float}]}]}``,
    jotta se voidaan suoraan viedä ``pipeline.words_document``-funktiolle.
    """
    from parakeet_mlx import from_pretrained

    model = from_pretrained(model_name)
    result = model.transcribe(
        str(audio_path), chunk_duration=CHUNK_SECONDS,
        overlap_duration=OVERLAP_SECONDS,
    )

    segments = []
    for sentence in getattr(result, "sentences", []):
        words = []
        curr_word: dict | None = None
        for tok in getattr(sentence, "tokens", []):
            tok_text = str(getattr(tok, "text", ""))
            if not tok_text:
                continue
            start = float(getattr(tok, "start", 0.0))
            end = float(getattr(tok, "end", start))

            if tok_text.startswith(" "):
                # Uusi sana alkaa välilyönnistä
                if curr_word:
                    words.append(curr_word)
                cleaned = tok_text.lstrip()
                if cleaned:
                    curr_word = {"word": cleaned, "start": start, "end": end}
                else:
                    curr_word = None
            elif curr_word is not None:
                # Alisana tai välimerkki liittyy edelliseen sanaan
                curr_word["word"] += tok_text
                curr_word["end"] = max(curr_word["end"], end)
            else:
                # Aloitetaan ensimmäinen sana jos ei edeltävää välilyöntiä
                curr_word = {"word": tok_text, "start": start, "end": end}

        if curr_word:
            words.append(curr_word)
        if words:
            segments.append({"words": words})

    return {"segments": segments, "text": getattr(result, "text", "").strip()}


def plan_parakeet_commands(
    options: RunOptions, audio_files: list[str]
) -> list[list[str]]:
    """Muodostaa suunnitellut paikalliset komennot (esim. --dry-run-tulostetta varten)."""
    out_dir = options.resolved_output_dir()
    return [
        [
            "parakeet-mlx",
            a,
            "--model",
            options.parakeet_model,
            "--output",
            str(out_dir / f"{Path(a).stem}.words.json"),
        ]
        for a in audio_files
    ]


def run_audio_mode_parakeet(
    options: RunOptions,
    audio: list[str],
    dry_run: bool,
    log: Callable[[str], None],
    on_progress: Callable[[int, str], None] | None = None,
    events_enabled: bool = False,
) -> int:
    """Suorittaa pelkän äänen litteroinnin paikallisesti Parakeet MLX:llä."""
    if dry_run:
        commands = plan_parakeet_commands(options, audio)
        for cmd in commands:
            log(" ".join(cmd))
        return 0

    available, reason = is_available()
    if not available:
        log(f"Virhe: {reason}")
        if events_enabled:
            events.emit("error", reason="environment", message=reason)
        return 1

    out_dir = options.resolved_output_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    expected = [out_dir / f"{Path(a).stem}.words.json" for a in audio]

    # Poistetaan vanhat tulostiedostot ennen ajoa
    for p in expected:
        p.unlink(missing_ok=True)

    if events_enabled:
        events.emit("session", state="local", backend=options.backend)

    total = len(audio)
    trail = events.StageTrail()

    def report_progress(percent: int, message: str) -> None:
        if on_progress:
            on_progress(percent, message)
        if events_enabled:
            events.emit("progress", percent=percent, message=message)

    backend_title = (
        "Orukeet"
        if "oruk" in options.parakeet_model.lower() or options.backend == "orukeet"
        else "Parakeet"
    )
    for idx, audio_file in enumerate(audio):
        audio_path = Path(audio_file)
        if not audio_path.is_file():
            msg = f"Äänitiedostoa ei löydy: {audio_file}"
            log(msg)
            if events_enabled:
                events.emit(
                    "error", reason="failed", code=1, stage=trail.current,
                    message=msg, file=audio_file
                )
            return 1

        step_pct = int(10 + (idx / total) * 80)
        msg = f"[{idx + 1}/{total}] Litteroidaan paikallisesti ({backend_title}): {audio_path.name}"
        log(msg)
        if events_enabled:
            trail.enter(
                "transcribe", index=idx + 1, total=total, name=audio_path.name
            )
        report_progress(step_pct, msg)

        try:
            raw = transcribe_file(audio_path, model_name=options.parakeet_model)
        except Exception as e:
            err_msg = f"Litterointi epäonnistui tiedostolle {audio_path.name}: {e}"
            log(err_msg)
            if events_enabled:
                events.emit(
                    "error", reason="failed", code=1, stage=trail.current,
                    message=err_msg, file=audio_path.name
                )
            return 1

        doc = pipeline.words_document(raw, options.language, timing=options.backend)
        dest = out_dir / f"{audio_path.stem}.words.json"
        dest.write_text(
            json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

        if not doc.get("words"):
            warn_msg = f"Varoitus: Tiedostosta '{audio_path.name}' ei löytynyt puhetta."
            log(warn_msg)
            if events_enabled:
                events.emit(
                    "warning", code="no_words", file=audio_path.name, message=warn_msg
                )

        end_pct = int(10 + ((idx + 1) / total) * 80)
        trail.finish()
        report_progress(end_pct, f"[{idx + 1}/{total}] Valmis: {audio_path.name}")

    report_progress(100, "Valmis.")
    if events_enabled:
        events.emit("done", files=[str(p) for p in expected])

    log(f"\nValmiit sanatiedostot ({len(expected)}):")
    for p in expected:
        log(f"  {p}")

    return 0
