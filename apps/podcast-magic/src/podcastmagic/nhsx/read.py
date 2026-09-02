"""``.nhsx``-tiedoston luku.

Rakenne, siltä osin kuin tämä työkalu siitä välittää::

    <Session>
      <AudioPool Path="…">
        <File Id="1" Name="olli.wav" Path="olli.wav">
          <Transcription><p><w s="1.20" l="0.31" sp="UU">sana</w>…</p></Transcription>
        </File>
      </AudioPool>
      <Tracks>
        <Track Name="Olli">
          <Region Ref="1" Start="0.000" Length="12.500" Offset="0.000"/>
        </Track>
      </Tracks>
    </Session>

Sanan ``s`` on aika **tiedoston** alusta, ei aikajanan. Regionin ``Offset``
kertoo mistä kohtaa tiedostoa alue alkaa ja ``Start`` mihin kohtaan aikajanaa
se on sijoitettu; sanan paikka aikajanalla on siis
``Start + (s - Offset)``. Tämä on koko vaimennusmoduulin ydin, ja siksi
tiedostoaika ja aikajana-aika pidetään koodissa erillään nimissä asti.

Elementit haetaan paikallisnimellä (``Localname``) eikä suoralla tagilla,
koska Hindenburgin viemät tiedostot ovat joskus nimiavaruudessa ja joskus
eivät. Colab-muistikirja kiersi saman asian tarkistamalla ``'AudioPool' in
tag`` — sama idea, mutta ilman osumaa nimeen ``MyAudioPoolBackup``.
"""

from __future__ import annotations

import glob
import os
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree


class NhsxError(RuntimeError):
    """Tiedosto ei jäsenny tai siitä puuttuu istunnon rakenne."""


def localname(elem) -> str:
    """Elementin nimi ilman nimiavaruutta."""
    tag = elem.tag
    if not isinstance(tag, str):  # kommentit ja käsittelyohjeet
        return ""
    return tag.rsplit("}", 1)[-1]


def children(elem, name: str) -> list:
    """Suorat lapset paikallisnimellä."""
    return [c for c in elem if localname(c) == name]


def descendants(root, name: str) -> list:
    """Kaikki jälkeläiset paikallisnimellä."""
    return [e for e in root.iter() if localname(e) == name]


def first(elem, name: str):
    for c in elem:
        if localname(c) == name:
            return c
    return None


def time_to_seconds(value: str | None) -> float:
    """Lukee ajan sekunteina tai muodossa ``[HH:]MM:SS[.mmm]``.

    Hindenburg kirjoittaa yleensä sekunteja, mutta kaksoispistemuoto esiintyy
    vanhemmissa istunnoissa. Puuttuva arvo (None) on nolla; rikkinäinen arvo
    nostaa ``ValueError``in, jonka luku muuntaa ``NhsxError``iksi. Sama
    sovitu kuin jaetussa ``nhsx``-paketissa ja Colabin snapshotissa: hiljainen
    nolla sijoittaisi alueen väärään kohtaan eikä kukaan huomaisi.
    """
    if value is None:
        return 0.0
    if not value:
        raise ValueError("tyhjä aikaleima")
    try:
        if ":" in value:
            parts = value.split(":")
            # [HH:]MM:SS on enimmäkseen: neljästä osasta koostuva arvo on
            # rikkinäinen, ei päivää. Ilman vartijaa 1:2:3:4 laskettaisiin
            # 223 384 s:ksi ja alue sijoittuisi kymmenen päivän päähän.
            if len(parts) > 3:
                raise ValueError(f"virheellinen aikaleima: {value}")
            return sum(float(part) * 60**i for i, part in enumerate(reversed(parts)))
        return float(value)
    except ValueError as exc:
        raise ValueError(f"virheellinen aikaleima: {value}") from exc


def seconds_to_time(seconds: float) -> str:
    """Aika takaisin attribuutiksi: sekunteja, kolme desimaalia."""
    return f"{seconds:.3f}"


@dataclass(frozen=True)
class Word:
    """Yksi sana litteroinnissa. ``start`` on aikaa tiedoston alusta."""

    text: str
    start: float
    length: float

    @property
    def end(self) -> float:
        return self.start + self.length


@dataclass
class FileInfo:
    """Yksi äänipoolin tiedosto."""

    id: str
    name: str
    path: str
    elem: object = field(repr=False, default=None)

    @property
    def transcription(self):
        return first(self.elem, "Transcription") if self.elem is not None else None

    @property
    def transcribed(self) -> bool:
        """Onko tiedostolla litterointi, jossa on edes yksi sana."""
        node = self.transcription
        return node is not None and bool(descendants(node, "w"))

    def words(self) -> list[Word]:
        node = self.transcription
        if node is None:
            return []
        out = []
        for w in descendants(node, "w"):
            text = (w.text or "").strip()
            if not text:
                continue
            out.append(
                Word(
                    text=text,
                    start=time_to_seconds(w.get("s")),
                    length=time_to_seconds(w.get("l")),
                )
            )
        return out


@dataclass
class RegionInfo:
    """Yksi alue raidalla. Ajat ovat aikajanaa paitsi ``offset``."""

    ref: str
    start: float
    length: float
    offset: float
    elem: object = field(repr=False, default=None)

    @property
    def end(self) -> float:
        return self.start + self.length


@dataclass
class TrackInfo:
    name: str
    elem: object = field(repr=False, default=None)
    regions: list[RegionInfo] = field(default_factory=list)


@dataclass
class Session:
    """Luettu istunto. ``tree`` on lxml-puu, jota moduulit muokkaavat."""

    path: str
    tree: object = field(repr=False, default=None)
    files: list[FileInfo] = field(default_factory=list)
    tracks: list[TrackInfo] = field(default_factory=list)
    audio_dir: str = ""

    def file_by_id(self, ref: str) -> FileInfo | None:
        for f in self.files:
            if f.id == ref:
                return f
        return None

    def file_by_name(self, name: str) -> FileInfo | None:
        """Nimihaku. Ensin täsmälleen, sitten kirjainkoko sivuuttaen.

        Kirjainkoko on Macilla merkityksetön tiedostojärjestelmässä mutta ei
        XML:ssä, ja Hindenburgin poolissa nimi tulee levyltä. Tarkka osuma
        ensin, jotta ``Puhe.wav`` ja ``puhe.wav`` samassa poolissa eivät mene
        ristiin.
        """
        for f in self.files:
            if f.name == name:
                return f
        low = name.lower()
        for f in self.files:
            if f.name.lower() == low:
                return f
        return None

    @property
    def word_count(self) -> int:
        return sum(len(f.words()) for f in self.files)


def read(path: str | Path) -> Session:
    """Lukee istunnon. Nostaa ``NhsxError``in jos tiedosto ei kelpaa."""
    path = str(path)
    parser = etree.XMLParser(
        remove_blank_text=False,
        recover=False,
        resolve_entities=False,
        no_network=True,
        dtd_validation=False,
        load_dtd=False,
    )
    try:
        tree = etree.parse(path, parser)
    except OSError as exc:
        raise NhsxError(f"Tiedostoa ei voi lukea: {exc}") from exc
    except etree.XMLSyntaxError as exc:
        raise NhsxError(f"XML ei jäsenny: {exc}") from exc

    root = tree.getroot()
    pool = None
    for elem in root.iter():
        if localname(elem) == "AudioPool":
            pool = elem
            break

    files: list[FileInfo] = []
    if pool is not None:
        for elem in children(pool, "File"):
            files.append(
                FileInfo(
                    id=elem.get("Id", ""),
                    name=elem.get("Name", ""),
                    path=elem.get("Path", elem.get("Name", "")),
                    elem=elem,
                )
            )

    tracks: list[TrackInfo] = []
    try:
        for elem in descendants(root, "Track"):
            track = TrackInfo(name=elem.get("Name", ""), elem=elem)
            for region in children(elem, "Region"):
                track.regions.append(
                    RegionInfo(
                        ref=region.get("Ref", ""),
                        start=time_to_seconds(region.get("Start", "0")),
                        length=time_to_seconds(region.get("Length")),
                        offset=time_to_seconds(region.get("Offset", "0")),
                        elem=region,
                    )
                )
            tracks.append(track)
    except ValueError as exc:
        raise NhsxError(f"Virheellinen aikaleima: {exc}") from exc

    if pool is None and not tracks:
        raise NhsxError(
            "Tiedostosta ei löytynyt äänipoolia eikä raitoja. "
            "Onko tämä Hindenburgin istuntotiedosto?"
        )

    # Äänipoolin oma Path on suhteellinen istuntotiedostoon nähden, ja
    # Hindenburg jättää sen usein tyhjäksi. Tiedoston oma hakemisto on siis
    # oikea oletus eikä varasija.
    pool_path = (pool.get("Path") or "").strip() if pool is not None else ""
    base = Path(path).resolve().parent
    audio_dir = str((base / pool_path).resolve()) if pool_path else str(base)

    return Session(path=path, tree=tree, files=files, tracks=tracks, audio_dir=audio_dir)


def locate(session: Session, file_info, extra_dir: str = "") -> str:
    """Etsii äänipoolin tiedoston levyltä.

    ``Path`` on istunnoissa milloin absoluuttinen, milloin istuntoon nähden
    suhteellinen, milloin pelkkä nimi. Kaikki kolme kokeillaan, ja vasta
    sitten haetaan nimellä syvemmältä: rekursio on hidas verkkolevyllä eikä
    sitä tehdä ennen kuin halvat vaihtoehdot on käyty läpi.
    """
    raw = file_info.path or file_info.name
    name = os.path.basename(raw) or file_info.name
    roots = [d for d in (extra_dir, session.audio_dir, str(Path(session.path).parent)) if d]

    if os.path.isabs(raw) and os.path.isfile(raw):
        return raw
    for root in roots:
        for candidate in (os.path.join(root, raw), os.path.join(root, name)):
            if os.path.isfile(candidate):
                return candidate
    for root in roots:
        try:
            for found in Path(root).rglob(glob.escape(name)):
                if found.is_file() and found.name == name:
                    return str(found)
        except OSError:
            continue
    return ""
