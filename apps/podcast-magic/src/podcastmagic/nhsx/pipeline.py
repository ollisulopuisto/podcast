"""Istunto siinä muodossa, jota puheenkäsittelyketju odottaa.

Tässä ei ole vielä yhtään käsittelyä. Tämä on **sauma**: se kääntää
Hindenburgin istunnon sanastolle, jolla autoraffkatin mitattu ääniketju
puhuu, jotta ketjun tuominen tänne omaksi moduulikseen on ketjun tuomista
eikä lukijan uudelleenkirjoittamista.

Sanasto on «raita, jolla on paikka ohjelma-aikajanalla»:

    Track:
        path        äänitiedosto levyllä
        speaker      kenen mikki tämä on
        mono         aina tosi mikille, ks. alla
        bit_depth    lähteen bittisyvyys, 0 jos ei tiedetä
        spans        [(ohjelma-alku, ohjelma-loppu, tiedosto-offset)]

Muunnos ohjelma-ajan ja tiedostoajan välillä on lineaarinen jokaisen jakson
sisällä, ja se yksi kaava on kaikki mitä ketju tarvitsee aikajanasta
tietää — sama kaava jolla ``silence/detect.py`` sijoittaa sanat::

    tiedostoaika = span.file_offset + (ohjelma-aika - span.programme_start)

Mikki on aina mono ulos, myös stereolähteestä. Kaksi kanavaa rikkoo
laskennan kolmessa paikassa hiljaa: vuodon vähennys lukee vain ensimmäisen
kanavan, ohjelman kattoon summautuvat eri kanavamääräiset raidat
levittämällä, ja panorointi on monolähteen käsite. Siksi ``mono`` on
lipuke jonka lukija asettaa, ei toive.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field

from ..binaries import MissingBinary, get_binary_path
from .read import Session, locate


@dataclass(frozen=True)
class Span:
    """Yhden alueen paikka ohjelma-aikajanalla."""

    programme_start: float
    programme_end: float
    file_offset: float

    def file_time(self, programme_time: float) -> float:
        return self.file_offset + (programme_time - self.programme_start)


@dataclass
class Track:
    path: str
    speaker: str
    mono: bool = True
    bit_depth: int = 0
    channels: int = 0
    spans: list[Span] = field(default_factory=list)


def probe(path: str) -> tuple[int, int]:
    """Bittisyvyys ja kanavamäärä, tai (0, 0) jos ei selviä.

    ffprobe eikä arvaus tiedostopäätteestä: WAV voi olla 16-, 24- tai
    32-bittinen, ja käsittelyn lähtökohta on väärä jos se arvataan.
    Puuttuva ffprobe ei ole virhe täällä — tieto on ketjun tarve, ei lukijan.
    """
    try:
        tool = get_binary_path("ffprobe")
    except MissingBinary:
        return (0, 0)
    cmd = [tool, "-v", "quiet", "-print_format", "json", "-show_streams",
           "-select_streams", "a:0", path]
    try:
        out = subprocess.run(cmd, capture_output=True, check=True).stdout
        streams = json.loads(out).get("streams") or []
    except (subprocess.CalledProcessError, ValueError, OSError):
        return (0, 0)
    if not streams:
        return (0, 0)
    stream = streams[0]
    depth = stream.get("bits_per_raw_sample") or stream.get("bits_per_sample") or 0
    try:
        depth = int(depth)
    except (TypeError, ValueError):
        depth = 0
    try:
        channels = int(stream.get("channels") or 0)
    except (TypeError, ValueError):
        channels = 0
    return (depth, channels)


def tracks(session: Session, extra_dir: str = "", with_probe: bool = True) -> list[Track]:
    """Istunnon raidat ketjun sanastolla.

    Yksi raita voi viitata useaan tiedostoon (leikattu istunto), ja ketju
    käsittelee yhden tiedoston kerrallaan. Siksi jako tehdään tiedostoittain
    raidan sisällä: raidan nimi on puhuja, tiedosto on käsittelyn kohde.
    """
    out: list[Track] = []
    for track in session.tracks:
        by_file: dict[str, list[Span]] = {}
        for region in track.regions:
            info = session.file_by_id(region.ref)
            if info is None:
                continue
            path = locate(session, info, extra_dir)
            if not path:
                continue
            by_file.setdefault(path, []).append(
                Span(
                    programme_start=region.start,
                    programme_end=region.end,
                    file_offset=region.offset,
                )
            )
        for path, spans in by_file.items():
            depth, channels = probe(path) if with_probe else (0, 0)
            out.append(
                Track(
                    path=path,
                    speaker=track.name,
                    mono=True,
                    bit_depth=depth,
                    channels=channels,
                    spans=sorted(spans, key=lambda s: s.programme_start),
                )
            )
    return out
