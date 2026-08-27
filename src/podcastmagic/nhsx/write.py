"""``.nhsx``-tiedoston kirjoitus."""

from __future__ import annotations

from pathlib import Path

from lxml import etree

from .read import Word, localname, seconds_to_time

# Puhujatunnus sanaelementissä. Hindenburg odottaa kentän olevan olemassa;
# «UU» on sen oma merkintä tuntemattomalle puhujalle. Diarisaatiota ei tehdä,
# koska Hindenburgissa jokainen puhuja on jo omalla raidallaan.
UNKNOWN_SPEAKER = "UU"


def set_transcription(file_elem, words: list[Word], speaker: str = UNKNOWN_SPEAKER) -> int:
    """Kirjoittaa sanat ``<File>``-elementin alle ja palauttaa sanamäärän.

    Vanha litterointi korvataan. Uudelleenlitterointi eri mallilla on
    tavallisin syy ajaa tämä toiseen kertaan, ja kaksi ``<Transcription>``ia
    samassa tiedostossa on Hindenburgille rikkinäinen istunto.
    """
    for old in [c for c in file_elem if localname(c) == "Transcription"]:
        file_elem.remove(old)

    transcription = etree.SubElement(file_elem, "Transcription")
    paragraph = etree.SubElement(transcription, "p")
    count = 0
    for word in words:
        text = word.text.strip()
        if not text:
            continue
        elem = etree.SubElement(paragraph, "w")
        elem.set("s", seconds_to_time(word.start))
        elem.set("l", seconds_to_time(max(0.0, word.length)))
        elem.set("sp", speaker)
        elem.text = text
        count += 1
    return count


def write(tree, path: str | Path) -> None:
    """Kirjoittaa puun levylle XML-esittelyn kera."""
    tree.write(str(path), encoding="UTF-8", xml_declaration=True)


def next_free_path(path: str | Path) -> Path:
    """Vapaa nimi: ``nimi.nhsx``, ``nimi v2.nhsx``, ``nimi v3.nhsx``…

    Vanhaa vientiä ei ylikirjoiteta. Hindenburgin selaimessa nimi on ainoa
    ero kahden version välillä, ja edellinen ajo on usein se joka kelpasi.
    """
    path = Path(path)
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    n = 2
    while True:
        candidate = path.with_name(f"{stem} v{n}{suffix}")
        if not candidate.exists():
            return candidate
        n += 1
