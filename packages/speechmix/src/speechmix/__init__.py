"""Puheen miksausketju: näytteitä sisään, näytteitä ulos.

Ei tunne yhtäkään istuntoformaattia. Isäntä antaa **raitoja joilla on
paikka ohjelman aikajanalla**, ei FCPXML-assetteja eikä nhsx-rivejä; ks.
paketin README.

Jokaisella alla olevalla moduulilla on kuluttaja. Se on tämän paketin
ainoa olemassaolon syy: kirjasto johon kirjoitetaan koodia jota mikään ei
kutsu on sama kolme kopiota ketjusta, vain yhden hakemiston sisällä.
"""

from . import (
    binaries,
    chain,
    debleed,
    dsp,
    editor,
    envelopes,
    errors,
    freshness,
    grid,
    masks,
    messages,
    meter,
    programme,
    rms,
    timeline,
)
from .messages import set_translator

__all__ = [
    "binaries",
    "chain",
    "debleed",
    "dsp",
    "editor",
    "envelopes",
    "errors",
    "freshness",
    "grid",
    "masks",
    "messages",
    "meter",
    "programme",
    "rms",
    "set_translator",
    "timeline",
]
