"""Paikallinen Orukeet-runtime ja sanakohtainen CTC-kohdistus."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path

from . import events
from .colab import pipeline

RECEIPT = Path.home() / ".cache" / "orukeet" / "installation.json"
WHEEL = (
    "https://github.com/Oruk-AI/orukeet/releases/download/v0.1.1/"
    "orukeet-0.1.1-py3-none-any.whl"
)
INSTALL = (
    f"uv pip install '{WHEEL}' torch==2.8.0 torchaudio==2.8.0 && "
    f"orukeet install --device auto --cache {RECEIPT.parent} --output {RECEIPT}"
)


def _receipt_path() -> Path:
    return Path(os.environ.get("ORUKEET_INSTALLATION", RECEIPT)).expanduser()


def _decode(path):
    from wordalign import decode

    return decode(str(path))


@contextmanager
def _wav_file(path):
    """Muuntaa myös MP3/M4A-lähteet natiiviruntimen 16 kHz mono-WAViksi."""
    with tempfile.TemporaryDirectory(prefix="orukeet-") as directory:
        wav_path = Path(directory) / "input.wav"
        subprocess.run(
            [
                "ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(path),
                "-f", "wav", "-ac", "1", "-ar", "16000", str(wav_path),
            ],
            check=True,
            timeout=3600,
        )
        yield wav_path


def _aligner():
    from wordalign import make_aligner

    return make_aligner()


def _align_segments(segments, audio, aligner, errors):
    from wordalign import align_segments, refined

    rows = align_segments(segments, audio, aligner, errors=errors)
    if any(row["ctc_start"] is None or row["ctc_end"] is None for row in rows):
        raise RuntimeError(
            "Orukeet-litteroinnin kaikkia sanoja ei saatu kohdistettua: "
            + "; ".join(errors)
        )
    return refined(rows)


def is_available() -> tuple[bool, str]:
    """Tarkistaa SDK:n, asennetun mallin ja CTC-kohdistimen saatavuuden."""
    if shutil.which("ffmpeg") is None:
        return False, "Orukeetin paikallinen äänimuunnos vaatii ffmpeg-komennon."
    try:
        import orukeet  # noqa: F401
    except ImportError:
        return False, f"Orukeet SDK ei ole asennettu. Asenna: {INSTALL}"

    receipt = _receipt_path()
    if not receipt.is_file():
        return False, f"Orukeetin asennuskuitti puuttuu: {receipt}. Asenna: {INSTALL}"

    try:
        import torch  # noqa: F401
        import torchaudio  # noqa: F401
    except ImportError as exc:
        return (
            False,
            "Orukeet vaatii sanakohdistukseen torchin ja torchaudion. "
            f"Asenna ne tähän ympäristöön; syy: {exc}",
        )
    return True, ""


def transcribe_file(audio_path: Path | str) -> dict:
    """Litteroi Orukeetilla ja kohdistaa lauseiden sanat ääneen CTC:llä."""
    from orukeet import Orukeet as Engine

    config = json.loads(_receipt_path().read_text(encoding="utf-8-sig"))
    with (
        _wav_file(audio_path) as wav_path,
        Engine(config["model"], config["runtime"], device=config["device"]) as model,
    ):
        response = model.transcribe(str(wav_path))

    segments = list(response.get("segments") or ())
    errors: list[str] = []
    if segments:
        words = _align_segments(segments, _decode(audio_path), _aligner(), errors)
    else:
        words = []

    return {
        "text": str(response.get("text", "")),
        "language": response.get("language"),
        "segments": [{"words": words}] if words else [],
        "alignment_errors": errors,
    }


def run_audio_mode_orukeet(
    options,
    audio,
    dry_run,
    log,
    on_progress=None,
    events_enabled=False,
) -> int:
    """Käyttää paikallista Orukeet-runtimea samalla Kuulas-tiedostosopimuksella."""
    if dry_run:
        for path in audio:
            target = options.resolved_output_dir() / f"{Path(path).stem}.words.json"
            log(f"orukeet transcribe {path} --output {target} (CTC word alignment)")
        return 0

    available, reason = is_available()
    if not available:
        log(f"Virhe: {reason}")
        if events_enabled:
            events.emit("error", reason="environment", message=reason)
        return 1

    out_dir = options.resolved_output_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    expected = [out_dir / f"{Path(path).stem}.words.json" for path in audio]
    for path in expected:
        path.unlink(missing_ok=True)

    if events_enabled:
        events.emit("session", state="local", backend="orukeet")

    total = len(audio)
    trail = events.StageTrail()
    for index, audio_path in enumerate(audio):
        source = Path(audio_path)
        if not source.is_file():
            log(f"Äänitiedostoa ei löydy: {audio_path}")
            return 1
        message = f"[{index + 1}/{total}] Litteroidaan paikallisesti (Orukeet): {source.name}"
        log(message)
        if events_enabled:
            trail.enter("transcribe", index=index + 1, total=total, name=source.name)
        if on_progress:
            on_progress(int(10 + index / max(total, 1) * 80), message)
        try:
            raw = transcribe_file(source)
        except Exception as exc:
            log(f"Litterointi epäonnistui tiedostolle {source.name}: {exc}")
            if events_enabled:
                events.emit(
                    "error", reason="failed", code=1, stage=trail.current,
                    message=str(exc), file=source.name,
                )
            return 1

        doc = pipeline.words_document(raw, options.language, timing="orukeet-ctc")
        expected[index].write_text(
            json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        if events_enabled:
            trail.finish()

    if on_progress:
        on_progress(100, "Valmis.")
    if events_enabled:
        events.emit("done", files=[str(path) for path in expected])
    log(f"\nValmiit sanatiedostot ({len(expected)}):")
    for path in expected:
        log(f"  {path}")
    return 0
