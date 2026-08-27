"""``.nhsx``-tiedoston kirjoitus."""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path

from lxml import etree

from .read import Word, localname, seconds_to_time

# Puhujatunnus sanaelementissä. Hindenburg odottaa kentän olevan olemassa;
# «UU» on sen oma merkintä tuntemattomalle puhujalle. Diarisaatiota ei tehdä,
# koska Hindenburgissa jokainen puhuja on jo omalla raidallaan.
UNKNOWN_SPEAKER = "UU"

# Lyhin pituus jonka sana saa. Nollapituinen sana katoaa vaimennuksessa
# kokonaan, vaikka se on puhuttu.
MIN_WORD_LENGTH = 0.02


# Kuinka pitkä tauko aloittaa uuden kappaleen. Puheenvuoron vaihto ja
# virkkeen loppu ovat molemmat yli sekunnin taukoja; sanaväli on
# kymmenesosia. Arvo on väljä tarkoituksella: liian tiheä jako tekee
# kappaleista rivejä, mikä ei ole sen luettavampi kuin yksi muuri.
PARAGRAPH_GAP = 1.2

# Kappaleen katto, jotta tauoton monologi ei jää yhdeksi kappaleeksi.
PARAGRAPH_MAX_WORDS = 80


def tidy(words: list[Word]) -> tuple[list[Word], int, int]:
    """Sanat aikajärjestykseen ilman päällekkäisyyksiä.

    Palauttaa (sanat, siirretyt, lyhennetyt).

    Whisper tuottaa toisinaan sanan joka alkaa ennen edellistä: lämpötilan
    pudotus segmentin rajalla siirtää aikaleimoja, ja pituus voi olla nolla
    tai negatiivinen. Aikajananäkymässä se ei näy — sana piirtyy hieman
    väärään kohtaan eikä sitä huomaa. Aikaindeksi sen sijaan olettaa
    kasvavan järjestyksen, ja puolitushaku järjestämättömän listan yli ei
    palauta virhettä vaan väärän kohdan.

    Järjestys korjataan lajittelemalla (vakaa, joten samaan hetkeen osuvat
    sanat säilyttävät keskinäisen järjestyksensä) ja päällekkäisyys
    lyhentämällä edellistä sanaa — ei siirtämällä seuraavaa. Alkuajat ovat
    se mihin toistokohdistin osuu, joten niitä ei muuteta.
    """
    ordered = sorted(words, key=lambda w: w.start)
    moved = sum(1 for a, b in zip(words, ordered, strict=True) if a is not b)

    out: list[Word] = []
    shortened = 0
    for word in ordered:
        length = word.length
        if length <= 0:
            length = MIN_WORD_LENGTH
            shortened += 1
        if out:
            previous = out[-1]
            if word.start < previous.end - 1e-9:
                clipped = max(MIN_WORD_LENGTH, word.start - previous.start)
                if clipped < previous.length:
                    out[-1] = Word(previous.text, previous.start, clipped)
                    shortened += 1
        out.append(Word(word.text, word.start, length))
    return out, moved, shortened


def paragraphs(words: list[Word], gap: float = PARAGRAPH_GAP,
               max_words: int = PARAGRAPH_MAX_WORDS) -> list[list[Word]]:
    """Jakaa sanat kappaleiksi tauoista.

    Yksi kappale, jossa on tuhansia sanoja, ei ole käsikirjoitus vaan
    tekstimuuri, eikä siinä ole mihin vierittää. Hindenburgin oma litterointi
    jakaa puheenvuoroihin, ja käsikirjoitusnäkymä on rakennettu sen ympärille.
    """
    if not words:
        return []
    groups: list[list[Word]] = [[words[0]]]
    for previous, word in pairwise(words):
        if word.start - previous.end >= gap or len(groups[-1]) >= max_words:
            groups.append([word])
        else:
            groups[-1].append(word)
    return groups


def set_transcription(
    file_elem,
    words: list[Word],
    speaker: str = UNKNOWN_SPEAKER,
    split: bool = True,
) -> dict:
    """Kirjoittaa sanat ``<File>``-elementin alle ja kertoo mitä se teki.

    Vanha litterointi korvataan. Uudelleenlitterointi eri mallilla on
    tavallisin syy ajaa tämä toiseen kertaan, ja kaksi ``<Transcription>``ia
    samassa tiedostossa on Hindenburgille rikkinäinen istunto.

    ``split=False`` kirjoittaa kaiken yhteen kappaleeseen, kuten
    Colab-muistikirja teki. Se on olemassa vertailua varten: kun
    käsikirjoitusnäkymä oireilee, sama istunto kahdella asetuksella kertoo
    onko kappalejako syy vai ei.
    """
    for old in [c for c in file_elem if localname(c) == "Transcription"]:
        file_elem.remove(old)

    clean = [w for w in words if w.text.strip()]
    clean, moved, shortened = tidy(clean)

    transcription = etree.SubElement(file_elem, "Transcription")
    groups = paragraphs(clean) if split else ([clean] if clean else [])
    count = 0
    for group in groups:
        paragraph = etree.SubElement(transcription, "p")
        for word in group:
            elem = etree.SubElement(paragraph, "w")
            elem.set("s", seconds_to_time(word.start))
            elem.set("l", seconds_to_time(max(MIN_WORD_LENGTH, word.length)))
            elem.set("sp", speaker)
            elem.text = word.text.strip()
            count += 1
    if not groups:
        etree.SubElement(transcription, "p")

    return {
        "words": count,
        "paragraphs": len(groups),
        "reordered": moved,
        "shortened": shortened,
    }


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
