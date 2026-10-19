"""Pakotettu kohdistus: Whisperin sanat ääneen, ja vertailu käsin merkittyihin alkuihin.

    uv run --package speechmix --with torch==2.8.0 --with torchaudio==2.8.0 \\
        python scripts/ab/ctc_align.py olli.json olli.wav \\
        --marks merkinnat.txt --csv ctc.csv

Whisperin sanaleimat ovat huomiomatriisin arvio, ja mitattuna (10 sanaa, käsin
merkittyä alkua) ne ovat enimmäkseen liian aikaisin, 20–550 ms. Äänen
energiasta alkua ei löydä luotettavasti: tavun alku ja sanan alku eivät ole
sama asia. Tämä kohdistaa **tekstin** ääneen foneettisesti (CTC, torchaudion
``MMS_FA``, joka tukee suomea) 20 ms:n kehyksillä, eikä luota Whisperin
omaan aika-arvioon. Mitä se antaa, ratkaisee vertailu sinun merkintöihisi:
``ctc_error`` (oma - kohdistin) ``whisper_error``in (oma - Whisper) rinnalla.

Kohdistin ajetaan **segmentti kerrallaan** (``PAD_S`` täytettä molemmin puolin),
ei koko äänelle: CTC:n ristikko kasvaa ajan ja tekstin pituuden tulona, eikä
kymmenen minuutin pätkä mahdu siihen kohtuullisella muistilla.

Merkintätiedosto: rivit ``whisper_aika sana oma_aika``, otsikot ``TAUON
JÄLKEEN`` ja ``SISÄLLÄ``; ajat sekunteina tai muodossa ``m:ss,mmm``;
rivit joilla on ``XX`` ohitetaan.

Neuroverkko annetaan ``main``ille parametrina (``aligner``), jotta kaikki sen
ympärillä on testattavissa ilman torchia (``tests/test_ctc_align.py``).
Itse malli ladataan vasta ajossa (``make_torchaudio_aligner``).
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
import unicodedata
from pathlib import Path

import numpy as np

#: Kohdistimen näytetaajuus (``torchaudio.pipelines.MMS_FA.sample_rate``).
RATE = 16000

#: Täyte segmentin molemmin puolin sekunteina. Whisperin segmentin raja voi olla
#: sadan millisekunnin verran pielessä (mitattu), joten ikkunan pitää ulottua
#: sanan oikean alun taakse. Liian suuri täyte vetää viereisen sanan äänen
#: mukaan pakotettuun kohdistukseen.
PAD_S = 0.5

#: Litteroinnin, jossa on vain tasainen sanalista, ryhmittely: tätä pidempi tauko
#: aloittaa uuden ryhmän, ja ryhmä on enintään näin pitkä.
GROUP_GAP_S = 1.0
GROUP_MAX_S = 25.0

#: Tätä pidempi tauko Whisperin sanojen välillä aloittaa uuden kohdistusryhmän.
#: Mitattu: segmentissä oli 2,9 s tauko, jossa kuului toisen mikin ääntä, ja
#: pakotettu kohdistus ahtaa sanat peräkkäin ja sijoitti tauon jälkeisen sanan
#: sinne, 2,7 s liian aikaisin. Ihmisen puheen sisäiset tauot ovat harvoin yli
#: puolen sekunnin, joten ryhmä ei menetä kontekstia, jota kohdistin tarvitsee.
SPLIT_GAP_S = 0.5

#: Kohdistin, joka siirtää sanan alun yli näin kauas Whisperin leimasta, on
#: erehtynyt: mitatut oikeat virheet Whisperissä olivat enintään 0,56 s. Sana
#: jää ilman aikaa ja syy kirjataan, ei arvata.
MAX_SHIFT_S = 1.0

#: Merkinnän ja arvion ero, jota pidetään osumana (sama kuin muissa mittareissa).
HIT_S = 0.030

#: Merkintä yhdistetään sanaan, jonka Whisper-alku on näin lähellä merkinnän
#: Whisper-aikaa (aika on kopioitu samasta litteroinnista).
MATCH_S = 0.005


def normalise_word(text: str) -> str:
    """Sana sellaiseksi kuin malli tuntee: pienet kirjaimet a-z ja heittomerkki.

    ä, ö ja å romanisoidaan ``a``, ``o`` ja ``a``; numerot ja välimerkit
    pudotetaan. Tyhjä tulos tarkoittaa sanaa, jota ei voi kohdistaa.
    """
    text = unicodedata.normalize("NFKD", text.replace("’", "'").lower())
    return "".join(c for c in text if ("a" <= c <= "z") or c == "'")


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


def _clean_words(raw) -> list[dict]:
    return [
        {
            "word": w.get("word", ""),
            "start": float(w["start"]),
            "end": float(w.get("end", w["start"])),
        }
        for w in raw
        if isinstance(w, dict) and w.get("start") is not None
    ]


def segments_of(data: dict) -> list[list[dict]]:
    """Whisperin JSON ryhmiksi, joista jokainen kohdistetaan erikseen."""
    groups: list[list[dict]] = []
    if isinstance(data, dict) and data.get("segments"):
        for segment in data["segments"]:
            words = _clean_words(segment.get("words") or [])
            if words:
                groups.append(words)
    elif isinstance(data, dict) and data.get("words"):
        current: list[dict] = []
        for word in _clean_words(data["words"]):
            if current and (
                word["start"] - current[-1]["end"] > GROUP_GAP_S
                or word["end"] - current[0]["start"] > GROUP_MAX_S
            ):
                groups.append(current)
                current = []
            current.append(word)
        if current:
            groups.append(current)
    if not groups:
        raise SystemExit("ei sanoja, joilla on alkuaika (segments[].words[].start).")
    return groups


def resample(x: np.ndarray, rate: int) -> np.ndarray:
    """Ääni kohdistimen taajuudelle (16 kHz); sama taulukko jos jo oikea."""
    if rate == RATE:
        return x
    from scipy.signal import resample_poly

    g = math.gcd(RATE, rate)
    return resample_poly(x, RATE // g, rate // g).astype(np.float32)


def split_at_pauses(
    groups: list[list[dict]], gap: float = SPLIT_GAP_S
) -> list[list[dict]]:
    """Ryhmät katkaistuna kohdista, joissa sanojen välissä on yli ``gap`` sekuntia."""
    out: list[list[dict]] = []
    for words in groups:
        current: list[dict] = []
        for word in words:
            if current and word["start"] - current[-1]["end"] > gap:
                out.append(current)
                current = []
            current.append(word)
        if current:
            out.append(current)
    return out


def window(words: list[dict], audio_s: float, pad: float = PAD_S) -> tuple[float, float]:
    """Segmentin ikkuna täytteineen, rajattuna äänen sisään."""
    return max(0.0, words[0]["start"] - pad), min(audio_s, words[-1]["end"] + pad)


def align_words(
    words, audio, align, pad: float = PAD_S, errors: list | None = None
) -> list[dict]:
    """Yhden segmentin sanat kohdistettuna; ajat koko äänen aika-akselilla.

    ``align(chunk, words) -> [(alku, loppu), ...]`` sekunteina palan alusta.
    Epäonnistuminen ei kaada ajoa: segmentin sanat jäävät ilman aikaa ja syy
    kirjataan ``errors``iin. ``None`` ei ole nolla.
    """
    out = [{**w, "ctc_start": None, "ctc_end": None} for w in words]
    texts = [normalise_word(w["word"]) for w in words]
    keep = [i for i, t in enumerate(texts) if t]
    if not keep:
        return out
    start, end = window(words, len(audio) / RATE, pad)
    chunk = audio[int(round(start * RATE)) : int(round(end * RATE))]
    try:
        spans = align(chunk, [texts[i] for i in keep])
        if len(spans) != len(keep):
            raise RuntimeError(
                f"aligner returned {len(spans)} spans for {len(keep)} words"
            )
    except Exception as exc:  # mallin virhe ei saa kaataa muita segmenttejä
        if errors is not None:
            errors.append(f"{start:.1f}-{end:.1f} s: {exc}")
        return out
    for i, (a, b) in zip(keep, spans, strict=True):
        shift = abs(start + a - words[i]["start"])
        if shift > MAX_SHIFT_S:
            if errors is not None:
                errors.append(
                    f"{words[i]['word'].strip()} at {words[i]['start']:.2f} s: aligner said "
                    f"{start + a:.2f} s ({shift:.1f} s away), rejected"
                )
            continue
        out[i]["ctc_start"] = start + a
        out[i]["ctc_end"] = start + b
    return out


def align_transcript(data, audio, align, pad: float = PAD_S, errors: list | None = None):
    rows: list[dict] = []
    for words in split_at_pauses(segments_of(data)):
        rows.extend(align_words(words, audio, align, pad, errors))
    return rows


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


def make_torchaudio_aligner():
    """Torchaudion ``MMS_FA``: monikielinen CTC-kohdistin (tukee suomea).

    Painot (noin 1,2 Gt) ladataan ensimmäisellä ajolla ja jäävät välimuistiin.
    """
    import torch
    import torchaudio

    bundle = torchaudio.pipelines.MMS_FA
    model = bundle.get_model(with_star=False).eval()
    tokenizer = bundle.get_tokenizer()
    aligner = bundle.get_aligner()

    def align(chunk, words):
        waveform = torch.from_numpy(np.asarray(chunk, dtype=np.float32))[None, :]
        with torch.inference_mode():
            emission, _ = model(waveform)
        spans = aligner(emission[0], tokenizer(words))
        ratio = waveform.size(1) / emission.size(1) / bundle.sample_rate
        return [(s[0].start * ratio, s[-1].end * ratio) for s in spans]

    return align


def main(argv=None, aligner=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("transcript", type=Path, help="Whisperin JSON")
    parser.add_argument(
        "audio", type=Path, help="sama ääni, jonka aika-akseli on litteroinnin"
    )
    parser.add_argument("--marks", type=Path, help="käsin merkityt alut")
    parser.add_argument("--csv", type=Path, help="kirjoita sanakohtaiset ajat tänne")
    parser.add_argument(
        "--pad", type=float, default=PAD_S, help="täyte segmentin ympärillä (s)"
    )
    args = parser.parse_args(argv)

    import soundfile as sf

    data = json.loads(args.transcript.read_text(encoding="utf-8"))
    segments_of(data)  # kieltäytyy ennen kuin mallia ladataan, jos sanoja ei ole
    samples, rate = sf.read(str(args.audio), dtype="float32", always_2d=True)
    audio = resample(samples.mean(axis=1), rate)

    if aligner is None:
        try:
            aligner = make_torchaudio_aligner()
        except ImportError as exc:
            print(
                f"Kohdistin tarvitsee torchin ja torchaudion ({exc}). Aja näin:\n"
                "  uv run --package speechmix --with torch==2.8.0 --with torchaudio==2.8.0 "
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
