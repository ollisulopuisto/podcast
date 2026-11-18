"""Pakatun sovelluksen JIT-savutesti: ``autoraffkat --selftest-jit``.

Ääniketju kääntää silmukkansa numballa (llvmlite), ja llvmlite varaa
suoritettavaa muistia. Hardened runtime tappaa sen (CODESIGNING, Invalid
Page), ellei allekirjoituksessa ole JIT-oikeuksia. Savutesti ajaa saman
polun pienellä datalla speechmixin julkisen rajapinnan kautta, jotta CI
huomaa kaatumisen eikä käyttäjä.
"""

from __future__ import annotations

import sys


def main() -> int:
    import numpy as np

    from speechmix import chain, meter

    rate = 48000
    audio = (np.sin(np.linspace(0, 400, rate)) * 0.5).reshape(1, -1)
    # Kompressori ja de-esser ajavat chain-kernelit, mittari meter-kernelin.
    squeezed = chain.compress(audio, rate, -20.0, 3.0, 12.0, 5.0, 50.0)
    cleaned = chain.deess(audio, rate)
    gauge = meter.IntegratedMeter(rate)
    gauge.add(audio)
    gauge.value()
    if squeezed.shape != audio.shape or cleaned.shape != audio.shape:
        print("selftest-jit: unexpected output shape", file=sys.stderr)
        return 1
    print("selftest-jit: ok")
    return 0


def plugin_load(path: str) -> int:
    """``autoraffkat --selftest-plugin-load POLKU``: lataa kolmannen osapuolen
    kirjaston samalla tavalla kuin liitännäisen lataus (dlopen).

    Hardened runtimen kirjastovalidointi estää muun kuin saman tiimin tai
    Applen allekirjoittaman kirjaston latauksen. Pakattu sovellus lataa
    käyttäjän VST3/AU-liitännäiset (muiden tiimien allekirjoittamia), joten
    CI ajaa tämän allekirjoittamattomalla (ad hoc) testikirjastolla.
    """
    import ctypes

    try:
        ctypes.CDLL(path)
    except OSError as exc:
        print(f"selftest-plugin-load: failed: {exc}", file=sys.stderr)
        return 1
    print("selftest-plugin-load: ok")
    return 0
