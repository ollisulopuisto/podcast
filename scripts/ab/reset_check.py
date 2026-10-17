"""Reset-koe: onko liitännäisen tulos satunnainen, tilallinen vai toistettava.

    uv run --package speechmix python scripts/ab/reset_check.py JAKSO.wav \\
        --plugin /Library/Audio/Plug-Ins/VST3/Accentize-dxRevive.vst3 \\
        --state tila-studio2.b64 --start 600 --seconds 10

``audition_measure`` löysi, että kaksi samanlaista ajoa eroavat toisistaan −38 dB
(Studio 2) tai −25 dB (toinen tila). Kaksi selitystä antaa saman luvun, ja ne vaativat
eri toimet:

* **Satunnainen:** jokaisessa ajossa on oma kohinansa (generatiivinen malli). Mikään ei
  korjaa sitä, ja kaikki vertailut ovat sen alapuolella sokeita.
* **Tilallinen:** ``reset=True`` ei tyhjennä kaikkea, ja kutsu alkaa edellisen kutsun
  jäljiltä. Se olisi **hiljainen vika tuotannossa**: sama raita kuulostaa erilaiselta
  sen mukaan, mitä instanssi käsitteli ennen sitä (automixerilla tämä oli yksi
  löydetyistä virheistä, ks. ``HANDOFF.md``).

**Esiaika on tässä kokeessa 0.** Edellisen kutsun jäänne näkyy kutsun alussa, ja pitkä
esiaika leikkaisi sen pois ikkunan ulkopuolelle (``test_a_long_preroll_hides_a_short_carry_over``).
Siksi myös ``audition_measure``n 8 sekunnin esiajalla ajetut mittaukset eivät olisi nähneet
lyhyttä vuotoa.

Koe erottaa ne kolmella vertailulla, yhteensä kolme instanssia:

1. **Tuoreet instanssit:** sama ikkuna kolmella uudella instanssilla, kukin kerran.
2. **Sama instanssi toistuvasti:** ensimmäisen instanssin kolme uutta ajoa.
3. **Muun äänen jälkeen:** toinen instanssi käsittelee ensin toisen ikkunan, ja sitten
   alkuperäisen; lopuksi ``reset()`` ja uudestaan.

Päätössääntö (kirjoitettu ennen lukuja, ``diagnose``):

* kaikki alle −55 dB: **toistettava**;
* tuoreet instanssit sopivat toisiinsa vähintään 10 dB paremmin kuin uudelleenkäytetty
  tai muun äänen jälkeinen: **tilallinen** (``reset=True`` ei riitä);
* kaikki samalla tasolla, yli −55 dB: **satunnainen**.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

import numpy as np

_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location(
    "audition_measure", _HERE / "audition_measure.py"
)
am = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(am)

#: Tämän alla kaksi ajoa on «sama» kokeessa. −55 dB: selvästi float32:n ja kaiken
#: kuultavan alapuolella, ja yli sen toistokohinaa jo mitataan.
DETERMINISTIC_DB = -55.0

#: Kuinka paljon paremmin tuoreiden instanssien pitää sopia toisiinsa kuin
#: uudelleenkäytettyjen, jotta ero luetaan tilaksi eikä satunnaisuudeksi.
CARRY_OVER_DB = 10.0

#: Alle tämän eroavat tasot luetaan samaksi.
SAME_LEVEL_DB = 6.0


def reset_experiment(
    plugins: list,
    audio: np.ndarray,
    rate: int,
    start: float,
    end: float,
    preroll: float,
    other_start: float,
    other_end: float,
    tail: float = am.DEFAULT_TAIL,
) -> dict:
    """Kolme vertailua kolmella instanssilla. Palauttaa ``dB``-arvot sanakirjassa."""
    if len(plugins) != 3:
        raise ValueError("the experiment needs exactly three plug-in instances")

    def render(plugin, a, b):
        return am.render_window(plugin, audio, rate, a, b, preroll, tail=tail)[0]

    p1, p2, p3 = plugins
    fresh = [render(p, start, end) for p in plugins]
    fresh_pairs = [
        am.residual_db(fresh[0], fresh[1]),
        am.residual_db(fresh[0], fresh[2]),
        am.residual_db(fresh[1], fresh[2]),
    ]

    again = [render(p1, start, end) for _ in range(3)]
    repeated = [
        am.residual_db(fresh[0], again[0]),
        am.residual_db(again[0], again[1]),
        am.residual_db(again[1], again[2]),
    ]

    render(p2, other_start, other_end)
    after_other = am.residual_db(fresh[1], render(p2, start, end))
    after_reset = None
    if hasattr(p2, "reset"):
        p2.reset()
        after_reset = am.residual_db(fresh[1], render(p2, start, end))
    _ = p3
    return {
        "fresh": fresh_pairs,
        "repeated": repeated,
        "after_other": after_other,
        "after_reset": after_reset,
    }


def diagnose(result: dict) -> str:
    """Päätössääntö kirjoitettu ennen lukuja, ks. moduulin docstring."""
    fresh = float(np.mean(result["fresh"]))
    repeated = float(np.max(result["repeated"]))
    after = float(result["after_other"])
    worst = max(fresh, repeated, after)
    if worst < DETERMINISTIC_DB:
        return (
            f"deterministic: every comparison is below {DETERMINISTIC_DB:.0f} dB "
            f"(worst {worst:.1f} dB). The plug-in repeats itself and reset=True works."
        )
    if repeated - fresh >= CARRY_OVER_DB or after - fresh >= CARRY_OVER_DB:
        return (
            f"carry-over: fresh instances agree to {fresh:.1f} dB, but a reused instance "
            f"differs by {repeated:.1f} dB and one that processed other audio first by "
            f"{after:.1f} dB. reset=True does not clear the plug-in's state: the output "
            "depends on what the instance did before."
        )
    spread = worst - min(fresh, repeated, after)
    if spread < SAME_LEVEL_DB:
        return (
            f"stochastic: fresh instances, a reused instance and one that processed "
            f"other audio first all differ by about {fresh:.1f} dB ({repeated:.1f} and "
            f"{after:.1f} dB). The output varies from run to run whatever the history; "
            "reset=True is not the cause."
        )
    return (
        f"mixed: fresh {fresh:.1f} dB, reused {repeated:.1f} dB, after other audio "
        f"{after:.1f} dB. The levels differ by {spread:.1f} dB but not by the "
        f"{CARRY_OVER_DB:.0f} dB that would call it carry-over; repeat with another window."
    )


def format_report(result: dict) -> str:
    fresh, repeated = result["fresh"], result["repeated"]
    lines = [
        "## Fresh instances (each renders the window once)",
        "",
        "| pair | difference |",
        "|---|---|",
        f"| 1 vs 2 | {fresh[0]:.1f} dB |",
        f"| 1 vs 3 | {fresh[1]:.1f} dB |",
        f"| 2 vs 3 | {fresh[2]:.1f} dB |",
        "",
        "## Same instance, repeated",
        "",
        "| pair | difference |",
        "|---|---|",
        f"| first vs second use | {repeated[0]:.1f} dB |",
        f"| second vs third | {repeated[1]:.1f} dB |",
        f"| third vs fourth | {repeated[2]:.1f} dB |",
        "",
        "## After other audio",
        "",
        "| step | difference from the instance's own first render |",
        "|---|---|",
        f"| after processing other audio | {result['after_other']:.1f} dB |",
    ]
    if result["after_reset"] is not None:
        lines.append(f"| after an explicit reset() | {result['after_reset']:.1f} dB |")
    else:
        lines.append("| after an explicit reset() | (plug-in has no reset()) |")
    return "\n".join([*lines, "", diagnose(result)])


def _load(path: str, state: str | None, count: int, param: str, mix: float) -> list:
    from speechmix import chain

    return [chain.load_plugin(path, {param: mix}, state) for _ in range(count)]


def _mix_param_default(path: str):
    return am._mix_param_default(path)


def main(argv: list[str] | None = None) -> int:
    import soundfile as sf

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("audio")
    parser.add_argument("--plugin", required=True)
    parser.add_argument("--state", help="tiedosto, jossa liitännäisen tila base64:nä")
    parser.add_argument("--start", type=float, required=True, help="sekuntia")
    parser.add_argument("--seconds", type=float, default=10.0)
    parser.add_argument(
        "--preroll",
        type=float,
        default=0.0,
        help="esiaika, sekuntia. Oletus 0: pidempi esiaika leikkaisi pois kutsun alun, "
        "jossa edellisen kutsun jäänne näkyy",
    )
    parser.add_argument(
        "--other-start",
        type=float,
        help="toisen ikkunan alku, sekuntia (oletus: --start + 60)",
    )
    parser.add_argument("--mix-param", help="Mix-säätimen nimi")
    parser.add_argument("--mix", type=float, default=100.0, help="Mix, yksiköissä")
    args = parser.parse_args(argv)

    param = args.mix_param or _mix_param_default(args.plugin)
    if not param:
        print("No Mix parameter found; pass --mix-param.", file=sys.stderr)
        return 2
    state = None
    if args.state:
        state = Path(args.state).read_text(encoding="ascii").strip()

    other_start = args.other_start if args.other_start is not None else args.start + 60.0
    end = args.start + args.seconds
    other_end = other_start + args.seconds
    info = sf.info(args.audio)
    rate = info.samplerate
    first = int(max(0.0, min(args.start, other_start) - args.preroll) * rate)
    last = int((max(end, other_end) + am.DEFAULT_TAIL) * rate)
    data, _ = sf.read(args.audio, start=first, stop=last, dtype="float32", always_2d=True)
    audio = data.T
    offset = first / rate

    plugins = _load(args.plugin, state, 3, param, args.mix)
    result = reset_experiment(
        plugins,
        audio,
        rate,
        args.start - offset,
        end - offset,
        args.preroll,
        other_start - offset,
        other_end - offset,
    )
    print(format_report(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
