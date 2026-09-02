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

**Mitattua:** ``Start``, ``Length``, ``Offset``, ``Muted``, ``Gain``,
``ClipGain``, ``Pan``, ``Volume`` ja ``<Fade Start Length Gain>``.
``h-test A`` mittasi ne. ``In``/``Out`` häivytyksessä olivat keksittyjä.

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

**Häivytys on raised-cosine.** Mitattu `h-test A` -istunnon A7-alueesta:
kosinille 0,29 dB RMS-virhe, janalle 1,04 dB. Muoto on `_share`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .read import Session, children, localname, locate, time_to_seconds

# Alueen attribuutit jotka osataan lukea. Käsin kirjoitettu lista, ei
# johdettu koodista: johdettuna se seuraisi koodia eikä valvoisi sitä.
KNOWN_REGION_ATTRS = frozenset(
    {
        "Ref", "Start", "Length", "Offset", "Muted", "Name", "Gain", "Pan",
        # Leikkeen oma taso, ja se joka **voittaa**: mitattu istunnosta
        # jossa alueella on `Gain="-11.2"` ja `ClipGain="-22.2"`. Renderissä
        # se alue on 22,50 dB vaimeampi kuin vaimentamaton — eli `ClipGain`
        # eikä niiden summa (-33,4 dB). Ne eivät siis laske yhteen.
        "ClipGain",
        # Eivät vaikuta tasoon: lippuja litterointia ja musiikkitunnistusta
        # varten. Tunnettuja, jotta varoitus säilyy merkitsevänä.
        "IsMusic", "UseTranscription",
    }
)

# Häivytyselementin attribuutit. `Start` ja `Length`, **ei** `In` ja `Out`:
# ne kaksi olivat keksittyjä, eikä yksikään istunto ollut kiistänyt niitä.
KNOWN_FADE_ATTRS = frozenset({"Start", "Length", "Gain"})

# Sama raidalle. Raidan vaimennin ja leikkeen taso ovat eri säätimiä.
# `Volume` on raidan vaimennin desibeleinä, mitattu `h-test A` -istunnosta
# ja sen renderöinnistä: `Volume="6"` → alueen rms −13,98 dBFS (lähde
# −20), `Volume="-6"` → −26,03. `Gain` on säilytetty, koska lukija tuki
# sen ennen mittoja; jos molemmat joskus esiintyvät, ne lasketaan yhteen
# kuten alueen `Gain` ja raidan `Volume` (mitattu: −8,06, ennuste −8,00).
KNOWN_TRACK_ATTRS = frozenset({"Name", "Gain", "Pan", "Muted", "Volume"})

# Alueen lapsielementti, joka on häivytys. Ks. moduulin alun varaus.
FADE_ELEMENT = "Fade"


def db_to_linear(db: float) -> float:
    """Desibelit kertoimeksi. ``-inf`` on hiljaisuus eikä virhe."""
    if db == float("-inf"):
        return 0.0
    return float(10.0 ** (db / 20.0))


def pan_gains(pan: float) -> tuple[float, float]:
    """Panorointi kanavakertoimiksi. **Lineaarinen ja vakiosummainen.**

    Mitattu, ei valittu. `pans and stuff` -istunto renderöitiin
    Hindenburgilla, ja renderöidystä raidasta sovitettiin pienimmän
    neliösumman suhde ``R = k·L``:

        Pan="0.625"   ennuste 0,23077   mitattu 0,23027
        Pan="-0.55"   ennuste 3,44444   mitattu 3,44347

    eli ``R/L = (1-p)/(1+p)`` 0,2 %:n ja 0,03 %:n tarkkuudella. Kaksi
    riippumatonta arvoa samalla lailla ei ole sattuma.

    **Positiivinen on vasen.** Tämä oli väärin päin, ja väärin päin oleva
    panorointi on kelvollinen tiedosto jossa puhujat ovat vaihtaneet
    puolta — ei mikään kaadu, eikä sitä huomaa muuten kuin kuuntelemalla.

    Normalisointi on vakiosumma (``L + R == 1``) eikä vakioteho. Sekin on
    mitattu: raidat ``Pan="0.625"`` ja ``Pan="-0.55"`` ovat summattuna
    0,24 dB:n päässä toisistaan. Vakiotehoisella lailla ero olisi 1,5 dB.

    Aiempi valinta oli vakiotehoinen laki. Perustelu — ettei keskellä oleva
    raita nouse laidoille ajetun yli — on hyvä perustelu, mutta se on
    perustelu sille miten *asian pitäisi* olla. Hindenburg tekee toisin, ja
    tämä lukee Hindenburgin istuntoja.

    Se mitä tämä **ei** kerro: absoluuttista skaalaa. Suhde ja summan
    vakioisuus mitattiin, mutta lähdetiedostoa ei ollut, joten ``(1±p)/2``
    ja ``(1±p)`` erottuisivat vain kokonaistasossa. Vakiosumma on niistä se,
    joka pitää keskelle panoroidun monolähteen summan ykkösenä.
    """
    pan = max(-1.0, min(1.0, pan))
    return ((1.0 + pan) / 2.0, (1.0 - pan) / 2.0)


@dataclass(frozen=True)
class Ramp:
    """Yksi äänenvoimakkuuskäyrän luiska leikkeen sisällä.

    Hindenburgin `<Fade>` ei ole häivytys hiljaisuuteen vaan **luiska
    tasolle**: se kulkee edellisestä tasosta arvoon ``gain`` ajassa
    ``length`` ja jää sinne. Mitattu istunnosta, jonka alue on

        <Fade Length="02.500" Gain="-11.2"/>
        <Fade Start="25.900" Length="02.500"/>

    ja jonka runko on renderissä 12,02 dB vaimeampi kuin vaimentamaton
    alue — eli luiska päätyi arvoon -11,2 dB eikä nollaan, ja jäi sinne.
    Toisella luiskalla ei ole ``Gain``ia, ja se palaa ykköseen: kuvaruudulla
    se on juuri se käyrä joka laskee, kulkee tasaisena ja nousee takaisin.

    Vanha malli oli `fade_in`/`fade_out` sekunteina hiljaisuudesta ja
    hiljaisuuteen. Se ei osaa esittää tasannetta lainkaan, joten kyse ei
    ollut väärästä luvusta vaan väärästä muodosta.
    """

    start: float
    length: float
    gain: float = 1.0

    @property
    def end(self) -> float:
        return self.start + self.length


def _share(share: float) -> float:
    """Luiskan kulkema osuus pisteessä ``share`` ∈ [0, 1]: raised-cosine.

    Mitattu, ei valittu. `h-test A` -testi-istunnon A7-alue (tasainen
    −20 dBFS kohina, luiska −10 dB:iin ja takaisin) sovitettiin 20 ms
    ikkunoiden RMS:llä: kosinille 0,29 dB RMS-virhe — mittauskohinan
    tuntumassa — janalle 1,04 dB, pahimmillaan 2,06 dB pielessä. Sekä
    ylös- että alaskäyrä istuvat samaan muotoon.

    Aiempi valinta oli jana, perusteena «se joka ei väitä mitään». Se
    peruste kuoli mittaan: jana väittää nyt mitattavasti väärin.
    """
    return (1.0 - np.cos(np.pi * share)) / 2.0


def level_at(ramps: "tuple[Ramp, ...]", when: float) -> float:
    """Käyrän arvo hetkellä ``when`` sekuntia leikkeen alusta.

    Taso on ykkönen ensimmäiseen luiskaan asti, kääntyy raised-cosine
    -muodossa (ks. ``_share``) luiskan yli ja pysyy sen päätearvossa
    seuraavaan luiskaan asti.
    """
    level = 1.0
    for ramp in ramps:
        if when <= ramp.start:
            return level
        if when >= ramp.end:
            level = ramp.gain
            continue
        if ramp.length <= 0:
            return ramp.gain
        share = (when - ramp.start) / ramp.length
        return level + (ramp.gain - level) * _share(share)
    return level


def envelope(length: float, sample_rate: int, ramps: "tuple[Ramp, ...]" = ()) -> np.ndarray:
    """Leikkeen äänenvoimakkuuskäyrä, ``length`` sekuntia ``sample_rate``:lla."""
    n = int(round(length * sample_rate))
    if n <= 0:
        return np.zeros(0, dtype=np.float32)
    if not ramps:
        return np.ones(n, dtype=np.float32)

    env = np.ones(n, dtype=np.float32)
    level = 1.0
    filled = 0
    for ramp in ramps:
        a = max(filled, min(n, int(round(ramp.start * sample_rate))))
        b = max(a, min(n, int(round(ramp.end * sample_rate))))
        env[filled:a] = level
        if b > a:
            # Luiska voi jäädä kesken, jos alue loppuu sen keskellä; silloin
            # se katkeaa siihen eikä kutistu. Pilkottu pala on lyhyempi kuin
            # alue, ei hitaampi. Muoto on sama raised-cosine kuin kokonaisella
            # luiskalla — ks. `_share`.
            span = max(1, int(round(ramp.length * sample_rate)))
            share = (np.arange(b - a, dtype=np.float32) + 1.0) / span
            env[a:b] = level + (ramp.gain - level) * _share(np.minimum(share, 1.0))
        filled = b
        level = float(env[b - 1]) if b > a else level
        if b >= n:
            return env
        if b > a:
            level = ramp.gain
    env[filled:] = level
    return env


@dataclass(frozen=True)
class Clip:
    """Yksi kuuluva leike ohjelma-aikajanalla.

    Vaimennettua leikettä ei ole: ``plan`` pudottaa ne ja laskee ne
    erikseen. Näin «miksauksessa oleva leike» tarkoittaa aina «tämä
    kuuluu», eikä jokaisen lukijan tarvitse muistaa tarkistaa lippua.

    Äänenvoimakkuus on ``gain`` kertaa ``ramps``-käyrä, eikä käyrä ole
    häivytys hiljaisuuteen: ks. ``Ramp``. Luiskat on leikattu leikkeen
    sisään, joten lukijan — myös sen joka on toista kieltä — ei tarvitse
    tietää mitä alueen ulkopuolelle jäävä luiska tarkoittaa.
    """

    path: str
    speaker: str
    start: float
    length: float
    file_offset: float
    gain: float = 1.0
    pan: float = 0.0
    ramps: tuple[Ramp, ...] = ()

    @property
    def end(self) -> float:
        return self.start + self.length

    def level_at(self, when: float) -> float:
        """Käyrän arvo ``when`` sekuntia leikkeen alusta."""
        return level_at(self.ramps, when)

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


def _ramps(region_elem, length: float, unknown: dict[str, int]) -> tuple[Ramp, ...]:
    """Alueen äänenvoimakkuuskäyrä `<Fade>`-lapsielementeistä.

    Attribuutit ovat ``Start``, ``Length`` ja ``Gain``. Aiempi versio luki
    ``In`` ja ``Out``, joita Hindenburg ei kirjoita, joten **jokaisen
    istunnon jokainen häivytys luettiin nollana** — eikä mikään kertonut
    siitä: tuntemattomaksi kirjattiin vain tuntematon *elementti*, ei
    tuntematon attribuutti sen sisällä. Siksi juuri se aukko, jonka läpi
    vika olisi pitänyt nähdä, oli vian kohdalla.
    """
    ramps: list[Ramp] = []
    for child in region_elem:
        name = localname(child)
        if not name:  # kommentit ja käsittelyohjeet
            continue
        if name != FADE_ELEMENT:
            unknown[name] = unknown.get(name, 0) + 1
            continue
        for attr in child.attrib:
            attr_name = localname_attr(attr)
            if attr_name not in KNOWN_FADE_ATTRS:
                key = f"{FADE_ELEMENT}/{attr_name}"
                unknown[key] = unknown.get(key, 0) + 1
        span = time_to_seconds(child.get("Length"))
        if span <= 0:
            continue
        begin = time_to_seconds(child.get("Start"))
        if begin >= length:
            continue
        ramps.append(
            Ramp(
                start=max(0.0, begin),
                length=min(span, length - begin),
                gain=db_to_linear(_number(child.get("Gain"), 0.0)),
            )
        )
    ramps.sort(key=lambda r: r.start)
    return tuple(ramps)


def _gain_and_pan(elem, known: frozenset[str], unknown: dict[str, int], prefix: str = ""):
    """Tason ja panoroinnin luku, ja kaiken muun kertominen."""
    for attr in elem.attrib:
        name = localname_attr(attr)
        if name not in known:
            key = f"{prefix}{name}"
            unknown[key] = unknown.get(key, 0) + 1
    # `ClipGain` voittaa `Gain`in eikä laske sen kanssa yhteen: mitattu.
    # Summa olisi ollut 11,2 dB liikaa vaimennusta, eli leike lähes
    # kuulumattomiin — kelvollinen tiedosto, väärä miksaus.
    level = elem.get("ClipGain")
    if level is None:
        level = elem.get("Gain")
    return (
        db_to_linear(_number(level, 0.0)),
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
            # Raidan vaimennin on `Volume`, desibeleinä — mitattu h-test A:sta
            # ja sen renderöinnistä (+6 → −13,98 dBFS, −6 → −26,03; lähde
            # −20). Ennen mittoa se kirjattiin tuntemattomaksi ja ohitettiin,
            # eli jokainen fader-asetus oli miksausbonukseltaan nolla.
            track_gain *= db_to_linear(_number(track_elem.get("Volume"), 0.0))
            track_muted = _truthy(track_elem.get("Muted"))

        for region in track.regions:
            end = region.start + region.length
            mixdown.duration = max(mixdown.duration, end)

            if region.length <= 0:
                continue

            elem = region.elem
            gain, pan = (1.0, 0.0)
            ramps: tuple[Ramp, ...] = ()
            if elem is not None:
                gain, pan = _gain_and_pan(elem, KNOWN_REGION_ATTRS, mixdown.unknown)
                # Leikattu tässä alueen sisään, jotta jokainen lukija — myös
                # katselimen Swift-puoli, joka ei jaa tämän kanssa riviäkään —
                # saa valmiit luvut eikä sääntöä opeteltavakseen.
                ramps = _ramps(elem, region.length, mixdown.unknown)

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
                    ramps=ramps,
                )
            )

    mixdown.clips.sort(key=lambda c: (c.start, c.speaker))
    return mixdown


def region_children(track_elem) -> list:
    """Raidan alueet elementteinä. ``prospect`` ja testit käyttävät tätä."""
    return children(track_elem, "Region")
