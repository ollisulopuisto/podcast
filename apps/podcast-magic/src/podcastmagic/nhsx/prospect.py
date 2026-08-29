"""Mitä istunnossa todella on: elementit, attribuutit ja esimerkkiarvot.

``mix.py`` lukee tasoa, panorointia ja häivytyksiä nimillä, joita **ei ole
mitattu** — Hindenburgin formaattia ei ole dokumentoitu, eikä tässä
repositoriossa ole yhtään istuntoa, jossa faderia olisi liikutettu. Tämä
työkalu on se, joka vaihtaa arvauksen mittaukseksi: aja se oikeaan
istuntoon, jossa taso, panorointi ja häivytys on asetettu, ja se kertoo
millä nimillä ne siellä ovat.

Sama kuvio kuin ``verify.py``:llä litteroinnin puolella. Formaattia ei
arvata: siitä kysytään tiedostolta.

**Nimi on vasta puolet vastauksesta.** «Gain» ei kerro onko arvo desibeliä
vai kerrointa, eikä «Pan» kerro onko asteikko −1…1 vai −100…100. Siksi
raportissa on esimerkkiarvot: ``Gain="-3"`` on desibeliä ja ``Gain="0.5"``
on kerroin, ja sen erottaa vain katsomalla.

Litterointia ei kartoiteta sanoittain. Tunnin jaksossa on kymmeniätuhansia
``<w>``-elementtejä, ne ovat jo tunnettuja, ja mukana ne hukuttaisivat
raportin siihen mitä ollaan etsimässä.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from .mix import KNOWN_REGION_ATTRS, KNOWN_TRACK_ATTRS, localname_attr
from .read import NhsxError, localname

# Litteroinnin sisus: tunnettu, dokumentoitu ja liian iso raportoitavaksi.
SKIP_INSIDE = "Transcription"

# Mitä muualla osataan lukea. ``Region`` ja ``Track`` tulevat ``mix``ista,
# jotta lista on yhdessä paikassa eikä ajaudu erilleen siitä mitä koodi
# oikeasti lukee.
KNOWN: dict[str, frozenset[str]] = {
    "Region": KNOWN_REGION_ATTRS,
    "Track": KNOWN_TRACK_ATTRS,
    "File": frozenset({"Id", "Name", "Path"}),
    "AudioPool": frozenset({"Path"}),
    "Fade": frozenset({"In", "Out"}),
    # Istunnon ja säiliöiden omat attribuutit eivät ole miksausta. Ne ovat
    # tunnettuja tässä siksi, että `?` tarkoittaisi jotain: raportti jossa
    # joka rivillä on kysymysmerkki ei osoita mihinkään.
    "Session": frozenset({"Name"}),
    "Tracks": frozenset(),
}

# Montako eri arvoa attribuutista näytetään. Tarpeeksi että asteikon näkee,
# vähän tarpeeksi ettei raportti ole tiedosto uudestaan.
EXAMPLES = 5


@dataclass
class Survey:
    """Yhden istunnon kartoitus."""

    path: str = ""
    elements: Counter = field(default_factory=Counter)
    attributes: dict[str, Counter] = field(default_factory=dict)
    values: dict[str, dict[str, list[str]]] = field(default_factory=dict)
    unknown: dict[str, list[str]] = field(default_factory=dict)


def survey(path: str | Path) -> Survey:
    """Käy istunnon läpi ja kertoo mitä siinä on."""
    try:
        tree = etree.parse(str(path), etree.XMLParser(recover=False))
    except (OSError, etree.XMLSyntaxError) as exc:
        raise NhsxError(f"Istuntoa ei voi kartoittaa: {exc}") from exc

    out = Survey(path=str(path))
    _walk(tree.getroot(), out)
    for element, attrs in out.attributes.items():
        known = KNOWN.get(element, frozenset())
        missing = sorted(name for name in attrs if name not in known)
        if missing:
            out.unknown[element] = missing
    return out


def _walk(elem, out: Survey) -> None:
    name = localname(elem)
    if not name:  # kommentit ja käsittelyohjeet
        return

    out.elements[name] += 1
    attrs = out.attributes.setdefault(name, Counter())
    values = out.values.setdefault(name, {})
    for raw, value in elem.attrib.items():
        attr = localname_attr(raw)
        attrs[attr] += 1
        seen = values.setdefault(attr, [])
        if value not in seen and len(seen) < EXAMPLES:
            seen.append(value)

    if name == SKIP_INSIDE:
        return
    for child in elem:
        _walk(child, out)


def survey_is_fully_understood(found: Survey) -> bool:
    """Onko istunnossa yhtään attribuuttia, jota emme lue."""
    return not found.unknown


def text(found: Survey) -> str:
    """Kartoitus luettavana raporttina."""
    lines = [f"{Path(found.path).name}", ""]
    for element in sorted(found.elements, key=lambda e: (-found.elements[e], e)):
        lines.append(f"<{element}> × {found.elements[element]}")
        attrs = found.attributes.get(element, Counter())
        unknown = set(found.unknown.get(element, ()))
        for attr in sorted(attrs):
            mark = "  ?" if attr in unknown else "   "
            examples = ", ".join(found.values[element].get(attr, [])[:EXAMPLES])
            lines.append(f"{mark} {attr} × {attrs[attr]}   {examples}")
        lines.append("")

    if survey_is_fully_understood(found):
        lines.append("Jokainen attribuutti on tunnistettu.")
    else:
        lines.append(
            "?-merkityt ovat attribuutteja joita tämä ohjelma ei lue. Jos "
            "joukossa on taso, panorointi tai häivytys, se on se nimi jota "
            "`mix.py` arvaa — ja arvo kertoo asteikon."
        )
    return "\n".join(lines)
