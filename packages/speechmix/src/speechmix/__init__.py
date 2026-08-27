"""Puheen miksausketju: näytteitä sisään, näytteitä ulos.

Ei tunne yhtäkään istuntoformaattia. Isäntä antaa **raitoja joilla on
paikka ohjelman aikajanalla**, ei FCPXML-assetteja eikä nhsx-rivejä; ks.
paketin README.
"""

from . import chain, debleed, messages
from .messages import set_translator

__all__ = ["chain", "debleed", "messages", "set_translator"]
