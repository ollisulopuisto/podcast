"""Sanaleimojen mittari: kuinka kaukana Whisperin sanan alku on äänen nousevasta reunasta.

    uv run --package speechmix python scripts/ab/word_onsets.py jakso.json jakso.wav

``jakso.json`` on Whisperin tulos (``segments[].words[]``, jokaisella
``word``, ``start``, ``end``) tai ``{"words": [...]}``; äänen aikajana on sama
kuin transkriptin. Työkalu ei muuta leimoja. Se vain mittaa, ja mittaus
ratkaisee, kannattaako leimoja korjata ja miten:

* terävä huippu nollan vieressä: ei korjattavaa;
* terävä huippu jossain muualla: vakio-offset, joka voidaan vähentää pois;
* tauon jälkeiset sanat eroavat muista: tarvitaan napsautus ääneen;
* leveä hajonta kaikkialla: äänen reuna ei riitä, tarvitaan pakotettu kohdistus.

Reuna on äänen tason nousu, ei sanan alku. Hiljaa alkava konsonantti voi alkaa
ennen kuin energia nousee, joten reunan ja ihmisen kuulleen sanan alun ero on
tuntematon vakio tässä mittauksessa; se pitää tarkistaa pienellä käsin
merkityllä testijoukolla (20–30 sanaa), ei kalibroida sillä.

Reunan paikan tarkkuus on puoli lohkoa (``HOP_S`` / 2 = 1,25 ms).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np

#: Lohko, jonka energia mitataan. 2,5 ms: ohuempi kuin ääntöpulssi, joten reunan
#: paikka ei sumene.
HOP_S = 0.0025

#: Taso lasketaan neljän lohkon (10 ms) ikkunasta.
FRAME_BLOCKS = 4

#: Reunan sivu: nousu mitataan 40 ms:n keskiarvoista ennen ja jälkeen.
SPAN_S = 0.040

#: Kuinka monta dB:n nousu 40 ms:ssa on reuna. 15 dB: tavallinen puheen
#: sisäinen tavun vaihto on alle 10 dB, ja äänen alku kohinasta yli 25 dB.
#: Hidas desibeleinä lineaarinen sisäänajo (50 dB / 0,9 s = 2 dB / 40 ms)
#: jää reilusti alle.
MIN_RISE_DB = 15.0

#: Sanan alku ja reuna yhdistetään, jos ne ovat tämän lähempänä toisiaan.
#: 250 ms: Whisperin tauon jälkeiset virheet ovat sadan millisekunnin
#: luokkaa, eikä pidempi ikkuna löytäisi enää samaa sanaa.
WINDOW_S = 0.25

#: Edellisen sanan lopun ja tämän alun väli, josta alkaen sana on "tauon jälkeen".
PAUSE_S = 0.30

#: Alle tämän sanamäärän ei anneta tuomiota.
MIN_WORDS = 10

#: Alle tämän mediaani ei ole korjaamisen arvoinen: 20 ms on alle kehyksen
#: (40 ms) ja alle kuulokynnyksen sanan alulle.
WORTH_S = 0.020

#: Yli tämän kvartaaliväli on liian leveä vakiokorjaukseksi.
WIDE_IQR_S = 0.080

#: Reunan on noustava näin monta dB kohinalattian yläpuolelle (sama luku kuin
#: puheruudukossa, speechmix.grid.FLOOR_MARGIN_DB).
FLOOR_MARGIN_DB = 12.0

#: Reunat eivät saa olla lähempänä toisiaan kuin tämä: yksi tavun alku on yksi reuna.
MIN_GAP_S = 0.050


def load_words(path: Path) -> list[dict]:
    """Sanat transkriptista; sanat ilman aikaa jätetään pois."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    raw: list[dict] = []
    if isinstance(data, dict) and data.get("segments"):
        for seg in data["segments"]:
            raw.extend(seg.get("words") or [])
    elif isinstance(data, dict) and data.get("words"):
        raw = list(data["words"])
    elif isinstance(data, list):
        raw = list(data)
    words = [
        {
            "word": w.get("word", ""),
            "start": float(w["start"]),
            "end": float(w.get("end", w["start"])),
        }
        for w in raw
        if isinstance(w, dict) and w.get("start") is not None
    ]
    if not words:
        raise SystemExit(
            f"{path}: ei sanoja, joilla on alkuaika (segments[].words[].start)."
        )
    return words


def _level_db(x: np.ndarray, rate: int) -> tuple[np.ndarray, int]:
    """Taso dB:nä jokaiselle lohkolle; palauttaa myös lohkon koon näytteinä."""
    hop = max(1, int(round(HOP_S * rate)))
    n = x.size // hop
    if n < FRAME_BLOCKS + 1:
        return np.zeros(0, dtype=np.float32), hop
    blocks = np.square(x[: n * hop].astype(np.float64)).reshape(n, hop).sum(axis=1)
    frame = np.convolve(blocks, np.ones(FRAME_BLOCKS), mode="valid") / (
        FRAME_BLOCKS * hop
    )
    return (10 * np.log10(frame + 1e-12)).astype(np.float32), hop


def onset_times(x: np.ndarray, rate: int) -> list[float]:
    """Äänen nousevat reunat sekunteina.

    Reuna on kohta, jossa 40 ms:n keskitaso nousee vähintään ``MIN_RISE_DB``
    ja nousun jälkeinen taso on ``FLOOR_MARGIN_DB`` kohinalattian yläpuolella.
    Paikka on ensimmäinen lohko, jonka taso on neljänneksen nousun verran
    ylempänä kuin ennen: tarkka reunan alkuun, ei sen huippuun.
    """
    db, hop = _level_db(np.asarray(x, dtype=np.float32), rate)
    k = max(2, int(round(SPAN_S / HOP_S)))
    if db.size < 2 * k + 2:
        return []
    floor = float(np.percentile(db, 20.0))
    # Kumulatiiviset summat: keskiarvo ennen ja jälkeen ilman silmukkaa.
    c = np.concatenate([[0.0], np.cumsum(db, dtype=np.float64)])
    idx = np.arange(k, db.size - k)
    before = (c[idx] - c[idx - k]) / k
    after = (c[idx + k + 1] - c[idx + 1]) / k
    rise = after - before
    ok = (rise >= MIN_RISE_DB) & (after >= floor + FLOOR_MARGIN_DB)
    # Paikallinen maksimi +-k:n sisällä: yksi reuna yhtä nousua kohti.
    peaks = []
    for j in np.flatnonzero(ok):
        lo, hi = max(0, j - k), min(rise.size, j + k + 1)
        if rise[j] >= rise[lo:hi].max() and (not peaks or j - peaks[-1] > k):
            peaks.append(j)
    times: list[float] = []
    for j in peaks:
        i = idx[j]
        threshold = before[j] + 0.25 * rise[j]
        window = db[i - k : i + k + 1]
        first = int(np.argmax(window >= threshold))
        frame_index = i - k + first
        # Kehyksen loppu miinus puoli lohkoa: reuna on viimeisessä lohkossa.
        t = (frame_index + FRAME_BLOCKS - 0.5) * hop / rate
        if not times or t - times[-1] >= MIN_GAP_S:
            times.append(t)
    return times


def word_offsets(
    words: list[dict], onsets: list[float], window: float = WINDOW_S
) -> list:
    """Jokaiselle sanalle ``reuna - alku`` sekunteina tai ``None``.

    Lähin reuna kerrallaan: jokainen reuna kuuluu yhdelle sanalle, ja
    sellaiselle sanalle, jonka lähellä ei ole reunaa, ei keksitä reunaa.
    ``None`` ei ole nolla.
    """
    pairs = []
    for wi, w in enumerate(words):
        for oi, t in enumerate(onsets):
            d = abs(t - w["start"])
            if d <= window:
                pairs.append((d, wi, oi))
    pairs.sort()
    result: list = [None] * len(words)
    taken: set[int] = set()
    for _, wi, oi in pairs:
        if result[wi] is None and oi not in taken:
            result[wi] = onsets[oi] - words[wi]["start"]
            taken.add(oi)
    return result


def _stats(values: list[float]) -> dict:
    if not values:
        return {"n": 0, "median": None, "p25": None, "p75": None, "within20": None}
    a = np.asarray(values, dtype=np.float64)
    med = float(np.median(a))
    return {
        "n": int(a.size),
        "median": med,
        "p25": float(np.percentile(a, 25)),
        "p75": float(np.percentile(a, 75)),
        "within20": float(np.mean(np.abs(a - med) <= 0.020)),
    }


def summarize(words: list[dict], onsets: list[float]) -> dict:
    offsets = word_offsets(words, onsets)
    after, inside = [], []
    for i, (w, off) in enumerate(zip(words, offsets, strict=True)):
        if off is None:
            continue
        gap = w["start"] - words[i - 1]["end"] if i else float("inf")
        (after if gap >= PAUSE_S else inside).append(off)
    matched = [o for o in offsets if o is not None]
    return {
        "words": len(words),
        "matched": len(matched),
        "onsets": len(onsets),
        "all": _stats(matched),
        "after_pause": _stats(after),
        "inside": _stats(inside),
        "offsets": offsets,
    }


def verdict(offsets: list) -> str:
    values = [o for o in offsets if o is not None]
    if len(values) < MIN_WORDS:
        return f"liian vähän sanoja ({len(values)} < {MIN_WORDS}): ei tuomiota."
    s = _stats(values)
    iqr = s["p75"] - s["p25"]
    med_ms = s["median"] * 1000
    if iqr > WIDE_IQR_S:
        return (
            f"hajonta liian suuri vakiokorjaukseen (kvartaaliväli {iqr * 1000:.0f} ms): "
            "tauon jälkeiset sanat erikseen tai pakotettu kohdistus."
        )
    if abs(s["median"]) < WORTH_S:
        return f"ei korjattavaa: mediaani {med_ms:+.0f} ms, kvartaaliväli {iqr * 1000:.0f} ms."
    direction = "myöhemmäksi" if s["median"] > 0 else "aikaisemmaksi"
    return (
        f"vakio-offset {med_ms:+.0f} ms (kvartaaliväli {iqr * 1000:.0f} ms): "
        f"siirrä Whisperin leimoja {abs(med_ms):.0f} ms {direction}."
    )


def _line(name: str, s: dict) -> str:
    if not s["n"]:
        return f"{name:<14} {0:>5}  -"
    return (
        f"{name:<14} {s['n']:>5}  mediaani {s['median'] * 1000:+6.0f} ms  "
        f"p25..p75 {s['p25'] * 1000:+5.0f}..{s['p75'] * 1000:+5.0f}  "
        f"+-20 ms mediaanista {s['within20'] * 100:3.0f} %"
    )


def histogram(offsets: list, lo=-0.25, hi=0.25, bin_s=0.020) -> str:
    values = np.asarray([o for o in offsets if o is not None])
    edges = np.arange(lo, hi + bin_s / 2, bin_s)
    counts, _ = np.histogram(values, bins=edges)
    top = counts.max() if counts.size and counts.max() else 1
    rows = []
    for c, a in zip(counts, edges[:-1], strict=True):
        rows.append(f"{a * 1000:+5.0f} ms {'#' * int(round(40 * c / top))} {c}")
    return "\n".join(rows)


def format_report(summary: dict) -> str:
    lines = [
        f"Sanoja {summary['words']}, reunoja {summary['onsets']}, yhdistetty {summary['matched']} "
        f"({100 * summary['matched'] / max(1, summary['words']):.0f} %).",
        "Ero = reuna - Whisperin alku; plus tarkoittaa, että Whisper on liian aikaisin.",
        "",
        _line("kaikki", summary["all"]),
        _line("tauon jälkeen", summary["after_pause"]),
        _line("lauseen sisällä", summary["inside"]),
        "",
        histogram(summary["offsets"]),
        "",
        "Tuomio: " + verdict(summary["offsets"]),
    ]
    return "\n".join(lines)


def _read_audio(path: Path, start: float, seconds: float | None):
    import soundfile as sf

    with sf.SoundFile(str(path)) as f:
        rate = f.samplerate
        f.seek(int(start * rate))
        frames = -1 if seconds is None else int(seconds * rate)
        data = f.read(frames, dtype="float32", always_2d=True)
    return data.mean(axis=1), rate


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("transcript", type=Path)
    p.add_argument("audio", type=Path)
    p.add_argument("--start", type=float, default=0.0, help="äänen alku sekunteina")
    p.add_argument("--seconds", type=float, default=None, help="kuinka monta sekuntia")
    p.add_argument(
        "--csv", type=Path, default=None, help="kirjoita sanakohtaiset erot tänne"
    )
    args = p.parse_args(argv)

    words = load_words(args.transcript)
    x, rate = _read_audio(args.audio, args.start, args.seconds)
    end = args.start + x.size / rate
    words = [w for w in words if args.start <= w["start"] < end]
    # Sanojen ajat suhteutetaan ladatun ikkunan alkuun.
    shifted = [
        {**w, "start": w["start"] - args.start, "end": w["end"] - args.start}
        for w in words
    ]
    summary = summarize(shifted, onset_times(x, rate))
    print(format_report(summary))
    if args.csv:
        with args.csv.open("w", newline="", encoding="utf-8") as fh:
            out = csv.writer(fh)
            out.writerow(["start_s", "word", "offset_ms"])
            for w, off in zip(words, summary["offsets"], strict=True):
                out.writerow(
                    [
                        f"{w['start']:.3f}",
                        w["word"].strip(),
                        "" if off is None else f"{off * 1000:.0f}",
                    ]
                )
        print(f"Sanakohtaiset erot: {args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
