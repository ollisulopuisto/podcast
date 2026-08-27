"""Puheen miksausketju: näytteitä sisään, näytteitä ulos.

Ei tunne yhtäkään istuntoformaattia. Isäntä antaa **raitoja joilla on
paikka ohjelman aikajanalla**, ei FCPXML-assetteja eikä nhsx-rivejä; ks.
paketin README.
"""

from . import debleed

__all__ = ["debleed"]
