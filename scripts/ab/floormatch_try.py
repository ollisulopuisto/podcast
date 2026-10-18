"""floormatch oikealla jaksolla: mittaa huoneäänen ylimäärä ja kirjoita ennen/jälkeen.

    uv run --package speechmix python scripts/ab/floormatch_try.py \\
        --track Olli="polku/olli.wav" --track Aamen="polku/aamen.wav" \\
        --track X="polku/x.wav" --track Y="polku/y.wav" \\
        --start 0 --seconds 300

``speechmix.floormatch`` (huoneäänen sävyn tasaus mikkien kesken) tarvitsee kolme
asiaa, jotka tämä ajuri laskee: **jaksot, joissa kukaan ei puhu** (``room_tone``:n
``spans``), **kunkin mikin oman puheen tason** (``excess_curves``:n ``speech_db``) ja
sen jälkeen ``apply``. Ajuri ei muuta ``floormatch.py``:tä: moduuli tuodaan vasta
``main``issa, ja ``run`` saa sen parametrina, jotta testit voivat käyttää valemoduulia.

Jaksot: puhemaski on sama kuin ``tone_measure``ssa (gridin kynnys), ja jakso on
kohta, jossa **jokainen** mikki on hiljaa yhtä aikaa, vähintään ``MIN_PAUSE_S`` pitkä
kummastakin päästä ``GUARD_S`` sisään vedettynä (lauseen häntä ja hengitys eivät ole
huoneääntä). Oma puhetaso: mikin oman puheen kehysten teho, mieluiten kehyksissä, joissa
mikään muu mikki ei puhu (vuoto ei sekoita), ja kaikissa omissa kehyksissä jos niitä on
liian vähän. Vain mikkien väliset erot ovat tärkeitä, joten yksikkö ei ratkaise.

Tulostaa taulukon (puhetaso, huoneääni, suurin ylimäärä, ylimäärä kolmella kaistalla)
ja kirjoittaa jokaiselle mikille ``NIMI.original.wav`` ja ``NIMI.matched.wav``, jotka
voi kuunnella ``scripts/ab/compare.py``:llä samalla äänekkyydellä.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

import numpy as np

_HERE = Path(__file__).resolve().parent


def _load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, _HERE / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tm = _load("tone_measure", "tone_measure.py")

#: Yhteisen tauon vähimmäispituus vartiovälien jälkeen, sekunteina. ``room_tone``
#: karsii jakson reunat 0,2 s, joten alle sekunnin jakso ei jätä juuri mitään.
MIN_PAUSE_S = 1.0

#: Kuinka paljon yhteistä taukoa vedetään sisään puheesta kummastakin päästä.
GUARD_S = 0.3

#: Alle tämän yksin puhuvien kehysten määrän oma taso lasketaan kaikista omista.
MIN_SOLO_FRAMES = 50

#: Kaistat, joilla ylimäärä raportoidaan: kokeen alussa kuultu sihinä oli 3-8 kHz.
BANDS = {
    "200-2000 Hz": (200.0, 2000.0),
    "3-8 kHz": (3000.0, 8000.0),
    "8-15 kHz": (8000.0, 15000.0),
}


def _grid():
    from speechmix import grid

    return grid


def frame_masks(tracks: dict[str, np.ndarray], rate: int) -> dict[str, np.ndarray]:
    """Puhekehykset mikeittäin, yhteiseen pituuteen leikattuna."""
    masks = {name: tm.speech_mask(x, rate) for name, x in tracks.items()}
    n = min(len(m) for m in masks.values())
    return {name: m[:n] for name, m in masks.items()}


def common_pauses(
    masks: dict[str, np.ndarray], guard_s: float = GUARD_S, min_s: float = MIN_PAUSE_S
) -> list[tuple[float, float]]:
    """Jaksot (sekunteja), joissa yksikään mikki ei puhu, vartiovälit sisään vedettynä."""
    grid = _grid()
    silent = ~np.any(np.stack(list(masks.values())), axis=0)
    padded = np.concatenate([[False], silent, [False]])
    edges = np.flatnonzero(np.diff(padded.astype(np.int8)))
    spans = []
    for first, last in zip(edges[0::2], edges[1::2], strict=True):
        start = first * grid.HOP_SEC + guard_s
        end = (last - 1) * grid.HOP_SEC + grid.FRAME_SEC - guard_s
        if end - start >= min_s:
            spans.append((float(start), float(end)))
    return spans


def _frame_power(x: np.ndarray, rate: int) -> np.ndarray:
    """Kehyskohtainen teho samoilla kehyksillä kuin puhemaski."""
    grid = _grid()
    size, hop = int(grid.FRAME_SEC * rate), int(grid.HOP_SEC * rate)
    count = 1 + (len(x) - size) // hop
    index = np.arange(size)[None, :] + hop * np.arange(count)[:, None]
    return np.mean(x[index].astype(np.float64) ** 2, axis=1)


def _db(power: float) -> float:
    return float(10.0 * np.log10(max(power, 1e-20)))


def own_speech_level_db(
    x: np.ndarray, masks: dict[str, np.ndarray], name: str, rate: int
) -> float | None:
    """Mikin oman puheen taso dB:nä, tai ``None`` jos sillä ei ole puhekehyksiä."""
    power = _frame_power(x, rate)
    n = min(len(power), len(masks[name]))
    own = masks[name][:n]
    others = [m[:n] for key, m in masks.items() if key != name]
    solo = own & ~np.any(np.stack(others), axis=0) if others else own
    chosen = solo if int(solo.sum()) >= MIN_SOLO_FRAMES else own
    if not chosen.any():
        return None
    return _db(float(np.mean(power[:n][chosen])))


def _room_db(x: np.ndarray, rate: int, spans: list[tuple[float, float]]) -> float | None:
    pieces = [x[int(a * rate) : int(b * rate)] for a, b in spans]
    pieces = [p for p in pieces if len(p)]
    if not pieces:
        return None
    return _db(float(np.mean(np.concatenate(pieces).astype(np.float64) ** 2)))


def run(floor, tracks: dict[str, np.ndarray], rate: int, out_dir: Path) -> dict:
    """Mittaa ja kirjoittaa ``floor``:n (``speechmix.floormatch``) avulla."""
    import soundfile as sf

    if len(tracks) < 2:
        raise ValueError("floormatch compares microphones: give at least two tracks")
    masks = frame_masks(tracks, rate)
    spans = common_pauses(masks)
    speech_db: dict[str, float] = {}
    skipped: list[str] = []
    for name, x in tracks.items():
        level = own_speech_level_db(x, masks, name, rate)
        if level is None:
            skipped.append(name)
        else:
            speech_db[name] = float(level)
    tones = {}
    for name, x in tracks.items():
        if name in skipped:
            continue
        tone = floor.room_tone(x, rate, spans)
        if tone is None:
            skipped.append(name)
        else:
            tones[name] = tone
    curves = floor.excess_curves(tones, {n: speech_db[n] for n in tones}, rate)

    out_dir.mkdir(parents=True, exist_ok=True)
    freqs = np.fft.rfftfreq(floor.N_FFT, 1.0 / rate)
    rows = []
    for name, tone in tones.items():
        excess = np.asarray(
            curves.get(name, np.zeros(floor.N_FFT // 2 + 1)), dtype=np.float64
        )
        x = tracks[name]
        matched = floor.apply(x[None, :], rate, tone, excess)[0]
        sf.write(out_dir / f"{name}.original.wav", x, rate)
        sf.write(out_dir / f"{name}.matched.wav", matched, rate)
        bands = {
            label: float(excess[(freqs >= lo) & (freqs < hi)].mean())
            for label, (lo, hi) in BANDS.items()
        }
        rows.append(
            {
                "name": name,
                "speech_db": speech_db[name],
                "room_db": _room_db(x, rate, spans),
                "excess_max": float(excess.max()),
                "bands": bands,
            }
        )
    return {"spans": spans, "rows": rows, "skipped": skipped, "out_dir": Path(out_dir)}


def format_report(result: dict) -> str:
    spans = result["spans"]
    total = sum(b - a for a, b in spans)
    lines = [
        f"Common pauses: {len(spans)} spans, {total:.0f} s in total.",
        "",
        "| mic | speech | room tone | max excess | " + " | ".join(BANDS) + " |",
        "|---|---|---|---|" + "---|" * len(BANDS),
    ]
    for row in result["rows"]:
        room = "n/a" if row["room_db"] is None else f"{row['room_db']:.1f} dB"
        bands = " | ".join(f"{row['bands'][label]:.1f} dB" for label in BANDS)
        lines.append(
            f"| {row['name']} | {row['speech_db']:.1f} dB | {room} | "
            f"{row['excess_max']:.1f} dB | {bands} |"
        )
    for name in result["skipped"]:
        lines.append(
            f"\n{name}: no room tone profile (too little pause or speech), left out."
        )
    out = result["out_dir"]
    listen = [r["name"] for r in result["rows"] if r["excess_max"] >= 1.0]
    if listen:
        files = " ".join(f"{out}/{n}.original.wav {out}/{n}.matched.wav" for n in listen)
        lines += [
            "",
            "Listen (loudness-matched, in this order: original, matched):",
            f"uv run --package speechmix python scripts/ab/compare.py {files}",
        ]
    return "\n".join(lines)


def _import_floormatch():
    from speechmix import floormatch

    return floormatch


def main(argv: list[str] | None = None) -> int:
    import soundfile as sf

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--track",
        action="append",
        required=True,
        metavar="NIMI=POLKU",
        help="vähintään kaksi",
    )
    parser.add_argument("--start", type=float, default=0.0, help="sekuntia")
    parser.add_argument("--seconds", type=float, default=120.0)
    parser.add_argument(
        "--out", default="temp/floormatch", help="kansio tulostiedostoille"
    )
    args = parser.parse_args(argv)

    tracks: dict[str, np.ndarray] = {}
    rates = set()
    for spec in args.track:
        if "=" not in spec:
            print(f"--track wants NAME=PATH, got {spec!r}", file=sys.stderr)
            return 2
        name, path = spec.split("=", 1)
        rate = sf.info(path).samplerate
        rates.add(rate)
        data, _ = sf.read(
            path,
            start=int(args.start * rate),
            stop=int((args.start + args.seconds) * rate),
            dtype="float32",
            always_2d=True,
        )
        tracks[name] = np.ascontiguousarray(data[:, 0])
    if len(rates) != 1:
        print(f"The tracks have different sample rates: {sorted(rates)}", file=sys.stderr)
        return 2
    result = run(_import_floormatch(), tracks, rates.pop(), Path(args.out))
    print(format_report(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
