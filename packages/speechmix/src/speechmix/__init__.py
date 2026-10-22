"""Puheen miksausketju: näytteitä sisään, näytteitä ulos.

Ei tunne yhtäkään istuntoformaattia. Isäntä antaa **raitoja joilla on
paikka ohjelman aikajanalla**, ei FCPXML-assetteja eikä nhsx-rivejä; ks.
paketin README.

Jokaisella alla olevalla moduulilla on kuluttaja. Se on tämän paketin
ainoa olemassaolon syy: kirjasto johon kirjoitetaan koodia jota mikään ei
kutsu on sama kolme kopiota ketjusta, vain yhden hakemiston sisällä.

Alimoduulit tuodaan vasta kun niitä pyydetään (PEP 562): ``speechmix.chain``
ja ``from speechmix import chain`` toimivat kuten ennenkin. Kaikkien tuonti
heti vei 0,74 s jokaiselta ``speechmix``in käyttäjältä, myös
``automixer --help``iltä, josta ``scipy.signal`` (``dsp``) 0,55 s (Linux,
lämmin välimuisti, ``-X importtime``).
"""

import importlib as _importlib

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
    "mixlaw",
    "programme",
    "rms",
    "set_translator",
    "timeline",
]

#: Myös ne joita ``__all__`` ei luettele (``blocks``, ``log``, ``panning``,
#: ``stems``): ``speechmix.stems`` toimii ilman omaa tuontia.
_SUBMODULES = (frozenset(__all__) - {"set_translator"}) | {
    "blocks", "log", "panning", "stems",
}


def __getattr__(name: str):
    if name in _SUBMODULES:
        # import_module asettaa alimoduulin paketin attribuutiksi, joten
        # tämä ajetaan kerran nimeä kohti.
        return _importlib.import_module(f".{name}", __name__)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | _SUBMODULES)
