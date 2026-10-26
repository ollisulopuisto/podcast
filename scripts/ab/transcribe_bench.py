"""Litteroinnin mittari: kellotettu ajo ja sanojen alkujen vertailu käsin merkittyihin.

Kaksi komentoa, ja ne vastaavat kahteen kysymykseen, joihin changelog ei vielä
vastaa (``colab-transcribe/CHANGELOG.md``: «65x–85x», «~43x» ilman
mittauspöytäkirjaa):

    # Kuinka nopea? Ajaa colab-transcriben ja kellottaa sen, kirjoittaa
    # <nimi>.bench.json:n sanatiedoston viereen.
    uv run --package colab-transcribe python scripts/ab/transcribe_bench.py \\
        run jakso.wav --out ulos --backend parakeet

    # Kuinka tarkka? Sanojen alut käsin merkittyjä vasten; useampi litterointi
    # rinnakkain samoilla merkinnöillä (uusi ja vanha).
    uv run --package podcast-magic python scripts/ab/transcribe_bench.py \\
        compare ulos/jakso.words.json --marks merkinnat.txt \\
        --baseline vanha/jakso.words.json

Vertailu ei yhdistä merkintää sanaan Whisperin alkuajalla kuten ``ctc_align.py``:
toisen mallin alku ei ole sama luku. Sana yhdistetään **tekstillä** (kirjainkoko
ja välimerkit eivät ratkaise) ja lähimmällä omalla ajalla ``WINDOW_S`` sisällä;
mikä ei löydy, jää yhdistämättä eikä sille arvata. Merkintätiedosto on sama
kuin ``ctc_align.py``:llä: ``whisper_aika sana oma_aika``, otsikot ``TAUON
JÄLKEEN`` ja ``SISÄLLÄ`` (Whisper-aika luetaan mutta ei käytetä).

Ero on ``oma - arvio``: plus tarkoittaa, että mallin alku on liian aikaisin
(Whisperilla mitattu mediaani oli +87 ms, ks. ``docs/KUULAS-TIMECODES.md``).
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ctc_align import HIT_S, parse_marks

BACKENDS = ("colab", "parakeet", "orukeet")

#: Merkintä yhdistetään samanasuiseen sanaan, jonka alku on tämän sisällä
#: merkinnän omasta ajasta. Ikkuna on arvio, ei mittaus: sen tarkoitus on
#: erottaa kaksoiskappaleet (sama sana monessa kohtaa), ei sallia suuria
#: virheitä. Whisperin pahin mitattu virhe oli 2,5 s, joten 3 s kattaa senkin.
WINDOW_S = 3.0

_PUNCT = re.compile(r"[^\w]+", re.UNICODE)


def command(audio: Path | str, out: Path | str, backend: str) -> list[str]:
    """colab-transcriben komento pelkän äänen tilassa; ``backend`` tarkistetaan."""
    if backend not in BACKENDS:
        raise ValueError(f"backend: {backend!r}, sallitut {', '.join(BACKENDS)}")
    return [
        "uv", "run", "--package", "colab-transcribe", "colab-transcribe",
        "--audio", str(audio), "--json", str(out), "--backend", backend,
    ]


def realtime_factor(audio_seconds: float, wall_seconds: float) -> float | None:
    """Kuinka monta kertaa nopeammin kuin äänen kesto; ``None`` jos luku ei ole mielekäs."""
    if audio_seconds <= 0 or wall_seconds <= 0:
        return None
    return audio_seconds / wall_seconds


def audio_seconds(path: Path) -> float:
    """Äänen kesto: soundfile, sitten ffprobe; muuten pyydetään ``--seconds``."""
    try:
        import soundfile as sf

        return float(sf.info(str(path)).duration)
    except Exception:
        pass
    try:
        done = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True, check=True,
        )
        return float(done.stdout.strip())
    except Exception:
        raise SystemExit(
            f"Kestoa ei saatu luettua: {path}. Anna se itse: --seconds <sekuntia>."
        ) from None


def load_words(path: Path) -> dict:
    """Sanatiedosto; kieltäytyy jos siinä ei ole ``words``-listaa."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data.get("words"), list):
        raise SystemExit(f"{path}: ei 'words'-listaa, tämä ei ole *.words.json.")
    return data


def _norm(text: str) -> str:
    return _PUNCT.sub("", text).casefold()


def compare(marks: list[dict], doc: dict) -> list[dict]:
    """Jokainen merkintä samanasuiseen sanaan, jonka alku on lähimpänä merkinnän omaa aikaa."""
    candidates = [(_norm(w["w"]), float(w["s"])) for w in doc["words"]]
    table = []
    for mark in marks:
        want = _norm(mark["word"])
        near = [s for text, s in candidates if text == want and abs(s - mark["mine"]) <= WINDOW_S]
        estimate = min(near, key=lambda s: abs(s - mark["mine"])) if near else None
        table.append(
            {
                "group": mark["group"],
                "word": mark["word"],
                "mine": mark["mine"],
                "estimate": estimate,
                "error": None if estimate is None else mark["mine"] - estimate,
            }
        )
    return table


def summarize(table: list[dict]) -> dict:
    out = {}
    for name in [*sorted({t["group"] for t in table}), "kaikki"]:
        sel = [t for t in table if name == "kaikki" or t["group"] == name]
        errors = [t["error"] for t in sel if t["error"] is not None]
        out[name] = {
            "n": len(sel),
            "matched": len(errors),
            "median": statistics.median(errors) if errors else None,
            "hits": sum(abs(e) <= HIT_S for e in errors),
        }
    return out


def _ms(value) -> str:
    return "     -" if value is None else f"{value * 1000:+6.0f}"


def report(marks: list[dict], docs: dict[str, dict]) -> str:
    """Rinnakkaisraportti: yksi sarake per litterointi, samat merkinnät."""
    tables = {name: compare(marks, doc) for name, doc in docs.items()}
    names = list(tables)
    head = f"{'ryhmä':<14}{'sana':<14}{'oma':>9}" + "".join(f"{n[:9]:>10}" for n in names)
    lines = [head]
    for i, mark in enumerate(marks):
        cells = "".join(f"{_ms(tables[n][i]['error']):>10}" for n in names)
        lines.append(f"{mark['group']:<14}{mark['word'][:13]:<14}{mark['mine']:9.3f}{cells}")
    lines += [
        "",
        "ero = oma - arvio (ms); plus tarkoittaa, että mallin alku on liian aikaisin. "
        "'-' = ei yhdistetty (ei samaa sanaa ikkunassa).",
    ]
    for name in names:
        for group, s in summarize(tables[name]).items():
            lines.append(
                f"{name[:9]:<10}{group:<14} n={s['n']:2d} yhdistetty={s['matched']:2d}  "
                f"mediaani {_ms(s['median'])} ms  |ero|<={HIT_S * 1000:.0f} ms: {s['hits']}/{s['matched']}"
            )
    lines += [
        "",
        "Rajaus: tämä on yksi puhuja ja merkintöjä on vähän, jos ne ovat samat 15. "
        "Tulos ei yleisty toiseen puhujaan, pitkään jaksoon (ajautuminen) tai sanojen "
        "loppuihin; ne vaativat omat merkintänsä.",
    ]
    return "\n".join(lines)


def run(args, clock=time.monotonic) -> int:
    audio = Path(args.audio)
    out = Path(args.out)
    seconds = args.seconds if args.seconds else audio_seconds(audio)
    expected = out / f"{audio.stem}.words.json"
    expected.unlink(missing_ok=True)  # vanha tiedosto ei saa kelvata uuden tilalle

    started = clock()
    done = subprocess.run(command(audio, out, args.backend), check=False)
    wall = clock() - started

    if done.returncode != 0:
        print(f"Ajo epäonnistui (poistumiskoodi {done.returncode}); ei mittaustulosta.")
        return 1
    if not expected.is_file():
        print(f"Ajo päättyi ilman tulostiedostoa {expected}; ei mittaustulosta.")
        return 1

    doc = load_words(expected)
    factor = realtime_factor(seconds, wall)
    bench = {
        "backend": args.backend,
        "audio": str(audio),
        "audio_s": seconds,
        "wall_s": round(wall, 3),
        "realtime_factor": None if factor is None else round(factor, 2),
        "words": len(doc["words"]),
        "timing": doc.get("timing"),
    }
    (out / f"{audio.stem}.bench.json").write_text(
        json.dumps(bench, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"{args.backend}: {seconds:.0f} s ääntä {wall:.1f} s:ssa"
        + (f" = {factor:.1f}x reaaliaikaa" if factor else "")
        + f", {bench['words']} sanaa. Mittaus on koko ajon seinäkello: malli ladataan ja "
        "lämmitetään ajon sisällä, joten ensimmäinen ajo on hitaampi kuin toinen."
    )
    return 0


def compare_command(args) -> int:
    marks = parse_marks(Path(args.marks).read_text(encoding="utf-8"))
    if not marks:
        raise SystemExit(f"{args.marks}: ei yhtään merkintää.")
    docs = {Path(args.transcript).stem.split(".")[0]: load_words(args.transcript)}
    for extra in args.baseline or []:
        docs[Path(extra).parent.name or Path(extra).stem] = load_words(extra)
    print(report(marks, docs))
    return 0


def main(argv=None, clock=time.monotonic) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    run_p = sub.add_parser("run", help="aja colab-transcribe ja kellota")
    run_p.add_argument("audio", type=Path)
    run_p.add_argument("--out", type=Path, required=True)
    run_p.add_argument("--backend", choices=BACKENDS, required=True)
    run_p.add_argument("--seconds", type=float, help="äänen kesto, jos sitä ei saa luettua")

    cmp_p = sub.add_parser("compare", help="sanojen alut käsin merkittyjä vasten")
    cmp_p.add_argument("transcript", type=Path, help="*.words.json")
    cmp_p.add_argument("--marks", type=Path, required=True)
    cmp_p.add_argument("--baseline", type=Path, action="append", help="toinen *.words.json")

    args = parser.parse_args(argv)
    if args.cmd == "run":
        return run(args, clock)
    return compare_command(args)


if __name__ == "__main__":
    sys.exit(main())
