"""Istunto miksauksena: mikä kuuluu, milloin, miten kovaa ja kummalta puolelta.

Tämä on ``pipeline.py``:n sisar. Siinä missä ``pipeline`` antaa istunnon
puheenkäsittelyketjun sanastolla — raita, puhuja, jaksot — tämä antaa sen
**toiston** sanastolla: lista leikkeitä ohjelma-aikajanalla, jokaisella
kerroin, häivytys ja paikka stereokuvassa. Kummallakin on sama lähde
(``read.py``) ja sama aikamuunnos; ne eroavat siinä mitä ne kysyvät.

Täällä ei ole yhtään tiedosto-operaatiota. Purku ja summaus ovat
``render.py``:ssä, ja syy erotteluun on että miksauksen viat ovat
laskennassa: väärä kohta aikajanalla, väärä kerroin, väärä puoli.

## Mikä on mitattu ja mikä ei

**Mitattua:** ``Start``, ``Length``, ``Offset`` ja ``Muted``. Ne ovat
istunnoissa joita tämä repositorio on lukenut ja kirjoittanut alusta asti —
``silence/apply.py`` kirjoittaa ``Muted="True"`` ja ``read.py`` on lukenut
geometrian koko ajan.

**Arvattua:** ``Gain``, ``Pan`` ja ``<Fade In= Out=>``. Kummassakaan
repositoriossa **ei ole yhtään istuntoa, jossa taso, panorointi tai
häivytys olisi asetettu**, eikä Hindenburgin formaattia ole dokumentoitu.
Nimet ovat siis uskottavia eivätkä todettuja: ``<Fade>`` on se nimi jolla
``tests/test_silence.py`` rakentaa alueen lapsielementin, ja ``apply.py``
sanoo lapsielementeistä «esimerkiksi häivytyksiä» — se on huomio, ei
mittaus.

Tämän luokan vika on hiljainen: tiedosto aukeaa, leikkeet ovat oikean
mittaisia, ääni tulee oikeasta kohtaa — ja taso on väärä. Siksi
**tuntematon attribuutti kerrotaan** (``Mix.unknown``) sen sijaan että se
ohitettaisiin, ja siksi ``prospect.py`` on olemassa: se lukee oikean
istunnon ja kertoo mitä siinä todella on. Yksi oikea tiedosto, jossa
faderia on liikutettu, vaihtaa yllä olevan arvauksen mittaukseksi — ja
``KNOWN_REGION_ATTRS`` on käsin kirjoitettu lista juuri siksi, ettei uusi
nimi livahda «tunnettujen» joukkoon ilman että kukaan päätti niin.

## Kaksi valintaa, jotka eivät ole makuasioita

**Panorointi on vakiotehoinen.** Lineaarisella lailla keskellä oleva raita
on summassa 3 dB kovempaa kuin laidoille ajettu, ja koko miksaus kallistuu
keskelle sitä mukaa kun raitoja on enemmän. ``pan_gains`` pitää
``vasen² + oikea² = 1`` laidasta laitaan, jolloin keskikohta on −3,01 dB
molemmilla puolilla.

**Häivytys on lineaarinen.** Hindenburgin käyrän muotoa ei tiedetä, ja
lineaarinen on niistä se joka ei väitä mitään. Kun muoto mitataan, se
vaihdetaan tässä yhdessä funktiossa.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .read import Session, children, localname, locate, time_to_seconds

# Alueen attribuutit jotka osataan lukea. Käsin kirjoitettu lista, ei
# johdettu koodista: johdettuna se seuraisi koodia eikä valvoisi sitä.
KNOWN_REGION_ATTRS = frozenset(
    {"Ref", "Start", "Length", "Offset", "Muted", "Name", "Gain", "Pan"}
)

# Sama raidalle. Raidan faderi ja leikkeen taso ovat eri säätimiä.
KNOWN_TRACK_ATTRS = frozenset({"Name", "Gain", "Pan", "Muted"})

# Alueen lapsielementti, joka on häivytys. Ks. moduulin alun varaus.
FADE_ELEMENT = "Fade"


def db_to_linear(db: float) -> float:
    """Desibelit kertoimeksi. ``-inf`` on hiljaisuus eikä virhe."""
    if db == float("-inf"):
        return 0.0
    return float(10.0 ** (db / 20.0))


def pan_gains(pan: float) -> tuple[float, float]:
    """Panoroinnin kertoimet vasemmalle ja oikealle, vakioteholla.

    ``pan`` on −1 (vasen) … +1 (oikea). Asteikon ulkopuolinen arvo
    **rajataan** eikä kierretä: arvo tulee attribuutista jota ei ole
    mitattu, ja kierrettynä se antaisi negatiivisen vahvistuksen eli
    vaihekäännöksen — kuultavana vikana aivan eri asia kuin liian kova.
    """
    pan = max(-1.0, min(1.0, pan))
    angle = (pan + 1.0) * math.pi / 4.0
    return (math.cos(angle), math.sin(angle))


def fit_fades(length: float, fade_in: float, fade_out: float) -> tuple[float, float]:
    """Häivytykset leikkeen sisään, suhteessa kutistaen.

    Leikettä pidemmät häivytykset syntyvät pilkkomisesta: ``apply.py``
    jättää lyhyitä paloja, ja alueen häivytys sellaisenaan perittynä on
    paloa pidempi. Ristiin menevien käyrien summa painuisi nollan ali, eli
    leike kääntyisi vaiheeltaan keskeltä.

    Tämä on **yksi funktio kahdelle kutsujalle** eikä sama sääntö kahdesti.
    ``plan`` soveltaa sen, jolloin jokainen ``Clip`` pitää lupauksen
    ``fade_in + fade_out <= length``; ``envelope`` soveltaa sen uudestaan,
    mikä on tyhjä operaatio jo mahtuville luvuille mutta pitää funktion
    turvallisena myös suoraan kutsuttuna. Kaksi kopiota säännöstä olisi
    täsmälleen se ajautuminen jota vastaan tämä repositorio on.
    """
    fade_in = max(0.0, fade_in)
    fade_out = max(0.0, fade_out)
    total = fade_in + fade_out
    if total > length and total > 0:
        scale = length / total
        return (fade_in * scale, fade_out * scale)
    return (fade_in, fade_out)


def envelope(length: float, sample_rate: int, fade_in: float, fade_out: float) -> np.ndarray:
    """Leikkeen häivytyskäyrä, ``length`` sekuntia ``sample_rate``:lla."""
    n = int(round(length * sample_rate))
    if n <= 0:
        return np.zeros(0, dtype=np.float32)

    fade_in, fade_out = fit_fades(length, fade_in, fade_out)

    env = np.ones(n, dtype=np.float32)
    n_in = min(n, int(round(fade_in * sample_rate)))
    n_out = min(n - n_in, int(round(fade_out * sample_rate)))
    if n_in > 1:
        env[:n_in] = np.linspace(0.0, 1.0, n_in, dtype=np.float32)
    elif n_in == 1:
        env[0] = 0.0
    if n_out > 1:
        env[n - n_out :] = np.linspace(1.0, 0.0, n_out, dtype=np.float32)
    elif n_out == 1:
        env[-1] = 0.0
    return env


@dataclass(frozen=True)
class Clip:
    """Yksi kuuluva leike ohjelma-aikajanalla.

    Vaimennettua leikettä ei ole: ``plan`` pudottaa ne ja laskee ne
    erikseen. Näin «miksauksessa oleva leike» tarkoittaa aina «tämä
    kuuluu», eikä jokaisen lukijan tarvitse muistaa tarkistaa lippua.

    Samasta syystä häivytykset **mahtuvat aina**:
    ``fade_in + fade_out <= length``. Lukijan ei tarvitse tietää
    kutistussääntöä — myöskään sen lukijan, joka on toista kieltä.
    """

    path: str
    speaker: str
    start: float
    length: float
    file_offset: float
    gain: float = 1.0
    pan: float = 0.0
    fade_in: float = 0.0
    fade_out: float = 0.0

    @property
    def end(self) -> float:
        return self.start + self.length

    def file_time(self, programme_time: float) -> float:
        """Sama muunnos kuin ``pipeline.Span.file_time`` ja ``silence/detect``."""
        return self.file_offset + (programme_time - self.start)


@dataclass
class Mix:
    """Istunto valmiina soitettavaksi tai renderöitäväksi."""

    clips: list[Clip] = field(default_factory=list)
    duration: float = 0.0
    muted: int = 0
    missing: list[str] = field(default_factory=list)
    unknown: dict[str, int] = field(default_factory=dict)

    @property
    def speakers(self) -> list[str]:
        out: list[str] = []
        for clip in self.clips:
            if clip.speaker not in out:
                out.append(clip.speaker)
        return out


def _truthy(value: str | None) -> bool:
    """``Muted`` on eri istunnoissa ``True``, ``true`` tai ``1``.

    Muistikirja kirjoitti ``'True'``, ``hindenburg-editor.py`` luki ``'1'``.
    Kumpikaan ei ollut väärässä siitä mitä *se* kirjoitti, ja siksi lukijan
    on kelpuutettava molemmat.
    """
    return (value or "").strip().lower() in {"true", "1", "yes"}


def _number(value: str | None, default: float) -> float:
    """Liukuluku attribuutista. Kelvoton arvo on oletus eikä poikkeus.

    Sama päätös kuin ``read.time_to_seconds``issa: yksi sekaisin mennyt
    attribuutti ei saa kaataa koko esikatselua.
    """
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _fades(region_elem, unknown: dict[str, int]) -> tuple[float, float]:
    """Alueen häivytykset lapsielementeistä."""
    fade_in = fade_out = 0.0
    for child in region_elem:
        name = localname(child)
        if not name:  # kommentit ja käsittelyohjeet
            continue
        if name == FADE_ELEMENT:
            fade_in = max(fade_in, time_to_seconds(child.get("In")))
            fade_out = max(fade_out, time_to_seconds(child.get("Out")))
        else:
            unknown[name] = unknown.get(name, 0) + 1
    return (fade_in, fade_out)


def _gain_and_pan(elem, known: frozenset[str], unknown: dict[str, int], prefix: str = ""):
    """Tason ja panoroinnin luku, ja kaiken muun kertominen."""
    for attr in elem.attrib:
        name = localname_attr(attr)
        if name not in known:
            key = f"{prefix}{name}"
            unknown[key] = unknown.get(key, 0) + 1
    return (
        db_to_linear(_number(elem.get("Gain"), 0.0)),
        max(-1.0, min(1.0, _number(elem.get("Pan"), 0.0))),
    )


def localname_attr(attr: str) -> str:
    """Attribuutin nimi ilman nimiavaruutta."""
    return attr.rsplit("}", 1)[-1]


def plan(session: Session, extra_dir: str = "") -> Mix:
    """Istunnon leikkeet ohjelma-aikajanalla, järjestyksessä.

    Ohjelman pituus lasketaan **kaikista** alueista, myös vaimennetuista ja
    niistä joiden tiedostoa ei löytynyt: aikajana on yhtä pitkä riippumatta
    siitä kuuluuko sen loppu. Muuten vaimennettuun loppuun päättyvä jakso
    lyhenisi joka renderöinnissä.
    """
    mixdown = Mix()
    seen_missing: set[str] = set()

    for track in session.tracks:
        track_elem = track.elem
        track_gain, track_pan = (1.0, 0.0)
        track_muted = False
        if track_elem is not None:
            track_gain, track_pan = _gain_and_pan(
                track_elem, KNOWN_TRACK_ATTRS, mixdown.unknown, prefix="Track/"
            )
            track_muted = _truthy(track_elem.get("Muted"))

        for region in track.regions:
            end = region.start + region.length
            mixdown.duration = max(mixdown.duration, end)

            if region.length <= 0:
                continue

            elem = region.elem
            gain, pan = (1.0, 0.0)
            fade_in = fade_out = 0.0
            if elem is not None:
                gain, pan = _gain_and_pan(elem, KNOWN_REGION_ATTRS, mixdown.unknown)
                fade_in, fade_out = _fades(elem, mixdown.unknown)

            # Kutistetaan tässä, jotta jokainen lukija — myös QuickLookin
            # Swift-puoli, joka ei jaa tämän kanssa riviäkään — saa
            # valmiiksi mahtuvat luvut eikä sääntöä opeteltavakseen.
            fits_in, fits_out = fit_fades(region.length, fade_in, fade_out)

            if track_muted or (elem is not None and _truthy(elem.get("Muted"))):
                mixdown.muted += 1
                continue

            info = session.file_by_id(region.ref)
            if info is None:
                continue
            path = locate(session, info, extra_dir)
            if not path:
                if info.name not in seen_missing:
                    seen_missing.add(info.name)
                    mixdown.missing.append(info.name)
                continue

            mixdown.clips.append(
                Clip(
                    path=path,
                    speaker=track.name,
                    start=region.start,
                    length=region.length,
                    file_offset=region.offset,
                    gain=gain * track_gain,
                    # Raidan panorointi siirtää leikkeen omaa, ei korvaa sitä.
                    pan=max(-1.0, min(1.0, pan + track_pan)),
                    fade_in=fits_in,
                    fade_out=fits_out,
                )
            )

    mixdown.clips.sort(key=lambda c: (c.start, c.speaker))
    return mixdown


def region_children(track_elem) -> list:
    """Raidan alueet elementteinä. ``prospect`` ja testit käyttävät tätä."""
    return children(track_elem, "Region")
