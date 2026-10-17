"""Tallennettujen tilojen vertailu: onko niiden malli sama.

    uv run --package speechmix python scripts/ab/state_compare.py JAKSO.wav \\
        --plugin /Library/Audio/Plug-Ins/VST3/Accentize-dxRevive.vst3 \\
        --state tila-a.b64 --state tila-b.b64 --start 600 --seconds 10

Mallin valinta on dxRevivessa liitännäisen tilassa eikä säädin (``speechmix.editor``),
ja ikkuna on joskus näyttänyt Studio 2:ta vaikka valittu oli Studio. Ikkunan näyttö ei
siis ratkaise, mikä malli tilaan tallentui. Tämä ratkaisee äänestä: sama ikkuna
renderöidään jokaisella tilalla (Mix 100 %, jotta tilaan tallennettu Mix ei sekoita) ja
erotusta verrataan liitännäisen omaan toistokohinaan (``audition_measure.repeat_residual_db``).

Tulostaa kolme asiaa: tilojen tavuerot, liitännäisen julkaisemat säätimet (onko mallille
oma säädin) ja äänen ero. Ero selvästi toistokohinan yläpuolella tarkoittaa, että tilat
eivät käyttäydy samoin: eri malli tai muu tilaan tallennettu ero.
"""

from __future__ import annotations

import argparse
import base64
import importlib.util
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location(
    "audition_measure", _HERE / "audition_measure.py"
)
am = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(am)


def byte_diff(a_b64: str, b_b64: str) -> tuple[int, int, int, list[int]]:
    """Kahden tilan pituudet, eroavien tavujen määrä ja ensimmäiset paikat.

    Eroavia tavuja lasketaan yhteisestä osasta, ja pituuseron tavut päälle:
    toinen tila voi olla pidempi, ja sekin on ero.
    """
    a, b = base64.b64decode(a_b64), base64.b64decode(b_b64)
    common = min(len(a), len(b))
    where = [i for i in range(common) if a[i] != b[i]]
    return len(a), len(b), len(where) + abs(len(a) - len(b)), where[:20]


def compare_states(plugin_a, plugin_b, audio, rate, start, end, preroll):
    """``(toisto, ero)`` dB: A kahdesti, ja A vastaan B.

    Jokainen ajo mitataan omalla viiveellään: malli voi viivästää eri verran.
    """
    repeat = am.repeat_residual_db(plugin_a, audio, rate, start, end, preroll)
    a, _ = am.render_window(plugin_a, audio, rate, start, end, preroll)
    b, _ = am.render_window(plugin_b, audio, rate, start, end, preroll)
    return repeat, am.residual_db(a, b)


def verdict(repeat: float, between: float) -> str:
    margin = between - repeat
    if margin >= am.BEYOND_NOISE_DB:
        return (
            f"different: the renders differ by {between:.1f} dB, {margin:.1f} dB above "
            f"the repeat noise ({repeat:.1f} dB). The two states do not behave alike: "
            "a different model, or another setting stored in the state."
        )
    return (
        f"same within the repeat noise: the renders differ by {between:.1f} dB and the "
        f"plug-in's own repeat noise is {repeat:.1f} dB. These states behave alike."
    )


def _load(path: str, state: str, param: str, mix: float):
    from speechmix import chain

    return chain.load_plugin(path, {param: mix}, state)


def _mix_param_default(path: str):
    return am._mix_param_default(path)


def _published_parameters(path: str) -> list[str] | None:
    from speechmix import chain

    try:
        specs, _ = chain.parameter_specs(path)
    except Exception:
        return None
    return [str(spec.get("name")) for spec in specs]


def main(argv: list[str] | None = None) -> int:
    import soundfile as sf

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("audio")
    parser.add_argument("--plugin", required=True)
    parser.add_argument(
        "--state", action="append", required=True, help="tilatiedosto, vähintään kaksi"
    )
    parser.add_argument("--start", type=float, required=True, help="sekuntia")
    parser.add_argument("--seconds", type=float, default=10.0)
    parser.add_argument("--preroll", type=float, default=8.0)
    parser.add_argument("--mix-param", help="Mix-säätimen nimi")
    parser.add_argument(
        "--mix", type=float, default=100.0, help="Mix kaikille, yksiköissä"
    )
    args = parser.parse_args(argv)
    if len(args.state) < 2:
        print("Give at least two --state files.", file=sys.stderr)
        return 2

    param = args.mix_param or _mix_param_default(args.plugin)
    if not param:
        print("No Mix parameter found; pass --mix-param.", file=sys.stderr)
        return 2
    states = [Path(p).read_text(encoding="ascii").strip() for p in args.state]

    print("## Saved states, byte by byte\n")
    for index, path in enumerate(args.state):
        print(
            f"- state {chr(65 + index)} ({path}): {len(base64.b64decode(states[index]))} bytes"
        )
    for index in range(1, len(states)):
        la, lb, count, where = byte_diff(states[0], states[index])
        print(
            f"- A vs {chr(65 + index)}: {count} differing bytes of {la}/{lb}, "
            f"first at {where}"
        )
    names = _published_parameters(args.plugin)
    if names is not None:
        print("\n## Parameters the plug-in publishes\n")
        print(", ".join(names) or "(none)")

    end = args.start + args.seconds
    info = sf.info(args.audio)
    rate = info.samplerate
    first = int(max(0.0, args.start - args.preroll) * rate)
    last = int((end + am.DEFAULT_TAIL) * rate)
    data, _ = sf.read(args.audio, start=first, stop=last, dtype="float32", always_2d=True)
    audio = data.T
    offset = first / rate

    plugins = [_load(args.plugin, state, param, args.mix) for state in states]
    print("\n## Audio: same window through each state (Mix fixed)\n")
    print("| compared | repeat noise | difference |\n|---|---|---|")
    texts = []
    for index in range(1, len(plugins)):
        repeat, between = compare_states(
            plugins[0], plugins[index], audio, rate,
            args.start - offset, end - offset, args.preroll,
        )  # fmt: skip
        label = f"A vs {chr(65 + index)}"
        print(f"| {label} | {repeat:.1f} dB | {between:.1f} dB |")
        texts.append(f"{label}: {verdict(repeat, between)}")
    print()
    for text in texts:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
