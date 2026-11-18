"""Pakatun sovelluksen JIT-savutesti: ``autoraffkat --selftest-jit``.

Ääniketju kääntää silmukkansa numballa (llvmlite), ja llvmlite varaa
suoritettavaa muistia. Hardened runtime tappaa sen (CODESIGNING, Invalid
Page), ellei allekirjoituksessa ole JIT-oikeuksia. Savutesti ajaa saman
polun pienellä datalla, jotta CI huomaa kaatumisen eikä käyttäjä.
"""

from __future__ import annotations

import sys


def main() -> int:
    import numpy as np

    from speechmix import chain, meter

    chain._kernels()
    audio = np.sin(np.linspace(0, 200, 4800)).reshape(1, -1) * 0.5
    gain = chain._compress_block(audio, -20.0, 3.0, 12.0, 0.9, 0.99, np.zeros(3))
    if gain.shape[-1] != audio.shape[-1]:
        print("selftest-jit: wrong gain length", file=sys.stderr)
        return 1
    b = np.array([1.0, 0.0, 0.0])
    a = np.array([1.0, 0.0, 0.0])
    power = meter._weighted_power(audio, b, a, b, a, np.zeros((1, 4)))
    if power.shape[0] != audio.shape[1]:
        print("selftest-jit: wrong power length", file=sys.stderr)
        return 1
    print("selftest-jit: ok")
    return 0
