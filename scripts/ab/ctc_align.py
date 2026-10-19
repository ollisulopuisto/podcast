"""Pakotettu kohdistus: Whisperin sanat ääneen, ja vertailu käsin merkittyihin alkuihin.

    uv run --package podcast-magic --with torch==2.8.0 --with torchaudio==2.8.0 \\
        python scripts/ab/ctc_align.py olli.json olli.wav \\
        --marks merkinnat.txt --csv ctc.csv

Whisperin sanaleimat ovat huomiomatriisin arvio, ja mitattuna (10 sanaa, käsin
merkittyä alkua) ne ovat enimmäkseen liian aikaisin, 20–550 ms. Äänen
energiasta alkua ei löydä luotettavasti: tavun alku ja sanan alku eivät ole
sama asia. Tämä kohdistaa **tekstin** ääneen foneettisesti (CTC, torchaudion
``MMS_FA``, joka tukee suomea) 20 ms:n kehyksillä, eikä luota Whisperin
omaan aika-arvioon. Mitä se antaa, ratkaisee vertailu sinun merkintöihisi:
``ctc_error`` (oma - kohdistin) ``whisper_error``in (oma - Whisper) rinnalla.

Kohdistus itse on sovelluksessa (``podcastmagic.transcribe.align``), ja tämä on
sen mittari: sama koodi, jota litterointi käyttää, ajettuna käsin merkittyjä
alkuja vasten. Kohdistin ajetaan ryhmä kerrallaan eikä koko äänelle: CTC:n
ristikko kasvaa ajan ja tekstin pituuden tulona.

Merkintätiedosto: rivit ``whisper_aika sana oma_aika``, otsikot ``TAUON
JÄLKEEN`` ja ``SISÄLLÄ``; ajat sekunteina tai muodossa ``m:ss,mmm``;
rivit joilla on ``XX`` ohitetaan.

Neuroverkko annetaan ``main``ille parametrina (``aligner``), jotta kaikki sen
ympärillä on testattavissa ilman torchia (``tests/test_ctc_align.py``).
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from pathlib import Path

import numpy as np

from podcastmagic.transcribe import align as core

#: Merkinnän ja arvion ero, jota pidetään osumana (sama kuin muissa mittareissa).
HIT_S = 0.030

#: Merkintä yhdistetään sanaan, jonka Whisper-alku on näin lähellä merkinnän
#: Whisper-aikaa (aika on kopioitu samasta litteroinnista).
MATCH_S = 0.005


def seconds(token: str) -> float:
    """``12.5``, ``12,5``, ``m:ss,mmm`` tai ``h:mm:ss`` sekunteina."""
    parts = token.strip().replace(",", ".").split(":")
    if len(parts) > 3 or not parts[0]:
        raise ValueError(token)
    total = 0.0
    for part in parts:
        total = total * 60 + float(part)
    return total


def parse_marks(text: str) -> list[dict]:
    """Käsin merkityt alut. Ryhmä tulee otsikkorivistä; ``XX``-rivit ohitetaan."""
    group, marks = "?", []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        upper = stripped.upper()
        if upper.startswith("TAUON"):
            group = "tauon jälkeen"
            continue
        if upper.startswith(("SISÄLLÄ", "SISALLA")):
            group = "sisällä"
            continue
        parts = stripped.split()
        try:
            whisper, mine = seconds(parts[0]), seconds(parts[-1])
        except (ValueError, IndexError):
            continue
        marks.append(
            {
                "group": group,
                "word": " ".join(parts[1:-1]),
                "whisper": whisper,
                "mine": mine,
            }
        )
    return marks


def segments_of(data: dict) -> list[list[dict]]:
    """Whisperin JSON ryhmiksi; kieltäytyy, jos sanoja ei ole."""
    groups = core.groups_of(data)
    if not groups:
        raise SystemExit("ei sanoja, joilla on alkuaika (segments[].words[].start).")
    return groups


def resample(x: np.ndarray, rate: int) -> np.ndarray:
    """Ääni kohdistimen taajuudelle (16 kHz); sama taulukko jos jo oikea."""
    if rate == core.RATE:
        return x
    from scipy.signal import resample_poly

    g = math.gcd(core.RATE, rate)
    return resample_poly(x, core.RATE // g, rate // g).astype(np.float32)


def align_transcript(
    data, audio, aligner, pad: float = core.PAD_S, errors: list | None = None
):
    """Kaikki sanat kohdistettuna sovelluksen ytimellä; kieltäytyy, jos sanoja ei ole."""
    segments_of(data)
    return core.align_raw(data, audio, aligner, pad, errors)


def compare(marks: list[dict], rows: list[dict]) -> list[dict]:
    """Jokainen merkintä sanaan, jolla on sama Whisper-alku. Ero = oma - arvio."""
    table = []
    for mark in marks:
        near = [r for r in rows if abs(r["start"] - mark["whisper"]) <= MATCH_S]
        row = min(near, key=lambda r: abs(r["start"] - mark["whisper"])) if near else None
        entry = {
            "group": mark["group"],
            "word": mark["word"],
            "whisper": mark["whisper"],
            "mine": mark["mine"],
            "matched": row is not None,
            "ctc_start": None if row is None else row["ctc_start"],
            "whisper_error": None,
            "ctc_error": None,
        }
        if row is not None:
            entry["whisper_error"] = mark["mine"] - row["start"]
            if row["ctc_start"] is not None:
                entry["ctc_error"] = mark["mine"] - row["ctc_start"]
        table.append(entry)
    return table


def _stats(errors: list[float]) -> tuple[float | None, int]:
    if not errors:
        return None, 0
    return statistics.median(errors), sum(abs(e) <= HIT_S for e in errors)


def summarize(table: list[dict]) -> dict:
    groups = {}
    for name in [*sorted({t["group"] for t in table}), "kaikki"]:
        sel = [t for t in table if name == "kaikki" or t["group"] == name]
        w = [t["whisper_error"] for t in sel if t["whisper_error"] is not None]
        c = [t["ctc_error"] for t in sel if t["ctc_error"] is not None]
        w_med, w_hits = _stats(w)
        c_med, c_hits = _stats(c)
        groups[name] = {
            "n": len(sel),
            "whisper_n": len(w),
            "ctc_n": len(c),
            "whisper_median": w_med,
            "ctc_median": c_med,
            "whisper_hits": w_hits,
            "ctc_hits": c_hits,
        }
    return groups


def _ms(value) -> str:
    return "     -" if value is None else f"{value * 1000:+6.0f}"


def format_report(table: list[dict]) -> str:
    lines = [
        f"{'ryhmä':<14}{'sana':<14}{'whisper':>9}{'kohdistin':>10}{'oma':>9}{'W-ero':>8}{'C-ero':>8}"
    ]
    for t in table:
        ctc = "-" if t["ctc_start"] is None else f"{t['ctc_start']:.3f}"
        lines.append(
            f"{t['group']:<14}{t['word'][:13]:<14}{t['whisper']:9.3f}{ctc:>10}{t['mine']:9.3f}"
            f"{_ms(t['whisper_error']):>8}{_ms(t['ctc_error']):>8}"
        )
    lines += [
        "",
        "ero = oma - arvio (ms); plus tarkoittaa, että arvio on liian aikaisin. "
        "W = Whisper, C = kohdistin.",
    ]
    for name, s in summarize(table).items():
        lines.append(
            f"{name:<14} n={s['n']:2d}  Whisper: mediaani {_ms(s['whisper_median'])} ms, "
            f"|ero|<=30: {s['whisper_hits']}/{s['whisper_n']}    "
            f"kohdistin: mediaani {_ms(s['ctc_median'])} ms, |ero|<=30: {s['ctc_hits']}/{s['ctc_n']}"
        )
    return "\n".join(lines)


def write_csv(rows: list[dict], path: Path) -> None:
    def fmt(v):
        return "" if v is None else f"{v:.3f}"

    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        out = csv.writer(handle)
        out.writerow(["word", "whisper_start", "whisper_end", "ctc_start", "ctc_end"])
        for r in rows:
            out.writerow(
                [
                    r["word"].strip(),
                    fmt(r["start"]),
                    fmt(r["end"]),
                    fmt(r["ctc_start"]),
                    fmt(r["ctc_end"]),
                ]
            )


def main(argv=None, aligner=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("transcript", type=Path, help="Whisperin JSON")
    parser.add_argument(
        "audio", type=Path, help="sama ääni, jonka aika-akseli on litteroinnin"
    )
    parser.add_argument("--marks", type=Path, help="käsin merkityt alut")
    parser.add_argument("--csv", type=Path, help="kirjoita sanakohtaiset ajat tänne")
    parser.add_argument(
        "--pad", type=float, default=core.PAD_S, help="täyte segmentin ympärillä (s)"
    )
    args = parser.parse_args(argv)

    import soundfile as sf

    data = json.loads(args.transcript.read_text(encoding="utf-8"))
    segments_of(data)  # kieltäytyy ennen kuin mallia ladataan, jos sanoja ei ole
    samples, rate = sf.read(str(args.audio), dtype="float32", always_2d=True)
    audio = resample(samples.mean(axis=1), rate)

    if aligner is None:
        try:
            aligner = core.make_aligner()
        except core.AlignerUnavailable as exc:
            print(
                f"{exc}\nAja näin:\n"
                "  uv run --package podcast-magic --with torch==2.8.0 --with torchaudio==2.8.0 "
                "python scripts/ab/ctc_align.py ..."
            )
            sys.exit(1)

    errors: list[str] = []
    rows = align_transcript(data, audio, aligner, args.pad, errors)
    aligned = sum(r["ctc_start"] is not None for r in rows)
    print(
        f"Sanoja {len(rows)}, kohdistettu {aligned}, epäonnistuneita segmenttejä {len(errors)}."
    )
    for message in errors:
        print("  !", message)
    if args.csv:
        write_csv(rows, args.csv)
        print(f"Sanakohtaiset ajat: {args.csv}")
    if args.marks:
        table = compare(parse_marks(args.marks.read_text(encoding="utf-8")), rows)
        print()
        print(format_report(table))
    return 0


if __name__ == "__main__":
    sys.exit(main())
