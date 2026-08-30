"""Mikroliike: valekameraa pystyvideoita varten.

Pystykonvertoitu puhekuva on keskusrajaus joka ei liiku — kolmensadan
leikkauksen putki tuntuu kuvaruudulta eikä kameralta. Tämä suunnitelma
jakaa spinenen kuville hienovaraisen skaalauskäsittelyn: lyhyet kuvat
pysyvät paikallaan, pitkät saavat hitaan puskun, ja vaihtelu on
pseudosatunnaista mutta toistettavaa.

Liike on pelkkää skaalaa, ei paikkaa. Smart Conformin kuvaajasijainti on
aitorivi tässä työnkulussa, ja vaakasuora harhailu siirtäisi puhujan pois
juuri siinä kehyksen kohdassa missä rajaus on tehty. Skaala pysyy ykkösen
yläpuolella, joten mikään kuva ei koskaan näytä reunoiltaan.

Kaikki rajat ovat täällä eivätkä käyttöliittymässä, samalla rulella kuin
panoroinnin leveys: «kuinka paljon liike» on kysymys johon käyttäjällä ei
ole vastausta — se numero on tämän työkalun tehtävä, ja sen rinnalla
laugee mittaus eikä liukusäädin.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

# Siemen. Sama jakso tuottaa saman suunnitelman joka viennillä; eri luku
# antaa eri leikkauksen, joten «uusinta» on siemenen vaihto.
SEED = 2026

# Alle tämän keston kuva ei liiku. Kolmen sekunnin kuva ehtii alkaa ja
# loppua ennen kuin katsoja erottaa liikkeen leikkauksesta, ja lyhyen
# kuvan animaatio lukeutuu virheeksi eikä tyyliksi.
MIN_ANIM_S = 3.0

# Pituuskynnys, jolla puskun yläraja kasvaa. Mitattu omasta aineistosta:
# puheenvuorojen mediaani on 36 s, joten kahdeksan sekuntia erottaa
# monologin tavallisesta vaihtokuvasta.
LONG_S = 8.0

# Kokonaisalue, suhteena: 1.06 = 106 %. Yli kuuden prosentin zoom alkaa
# näkyä laadun heikkenemisenä (1080p-lähde rajattuna pystyyn) ja isompi
# liike luetaan tyylikeinoksi eikä kameraksi.
SCALE_MIN = 1.00
SCALE_MAX = 1.06

# Liikkumattoman lyhyen kuvan katto. Lyhyt kuva saa kehyksen joka
# erottuu naapureistaan mutta ei aikaa animaatiolle.
STATIC_MAX = 1.04

# Puskun määrä, suhteena kuvan kestosta riippumatta: hitain juuri ja
# juuri havaittava veto on kaksi prosenttia, ja yli viiden tyylikeino
# alkaa näkyä. Keskipitkä kuva saa vain alkuosan — sen ajassa ei ole
# tilaa syvyydelle.
PUSH_MIN = 0.02
PUSH_MAX = 0.05
PUSH_MID_MAX = 0.03

# Suurin sallittu skaalero vierekkäisten kuvien välillä. Isompi hyppy
# luetaan leikkaukseksi — tarkoitus on kameran vaihtelu, ei uusi leikkaus.
MAX_JUMP = 0.03

# Montako samaa kehystä putkeen sallitaan. Kaksi on vaihtelua; kolme
# alkaa näyttää toistolta.
MAX_REPEAT = 2

# Kaksi kehystä lähempänä toisiaan kuin tämä luetaan samaksi kehykseksi.
SAME_EPSILON = 0.005


@dataclass
class Move:
    """Yhden kuvan käsittely: skaala alussa ja lopussa.

    ``start_scale == end_scale`` on paikallaan pysyvä kehys, ja identtinen
    ykkönen (``identity``) tarkoittaa että mitään ei kirjoiteta vietyyn
    tiedostoon lainkaan — tyhjä asetus olisi Final Cutille asetus siinä
    missä mikä tahansa, samasta syystä kuin panoroinnissakin.
    """

    start_scale: float
    end_scale: float

    @property
    def animated(self) -> bool:
        return abs(self.end_scale - self.start_scale) > 1e-9

    @property
    def identity(self) -> bool:
        return (
            abs(self.start_scale - 1.0) < 1e-9
            and abs(self.end_scale - 1.0) < 1e-9
        )


def _clamp(value: float, low: float, high: float) -> float:
    return min(high, max(low, value))


def plan(
    durations: list[float],
    wides: list[bool],
    seed: int = SEED,
) -> list[Move]:
    """Jakaa kuville käsittelyn keston ja järjestyksen perusteella.

    ``durations`` on kuvien kestot sekunteina spinen järjestyksessä ja
    ``wides`` kertoo mitkä niistä ovat laajoja. Tulos on samanpitkä
    lista ``Move``-tietueita samassa järjestyksessä.

    Satunnaisuus on ``random.Random(seed)``iä: sama syöte antaa aina
    saman suunnitelman. Rajat pannaan täytäntöön paikkaamalla eikä
    hylkäämällä — hylkäyssilmukka voisi jäädä jumiin kun edellinen kuva
    on jo alueen reunassa.
    """
    rng = random.Random(seed)
    moves: list[Move] = []
    prev = 1.0
    same_run = 0
    for dur, wide in zip(durations, wides, strict=True):
        if wide:
            move = Move(1.0, 1.0)
        else:
            ceiling = STATIC_MAX if dur < MIN_ANIM_S else SCALE_MAX
            start = _frame(rng, prev, same_run, ceiling)
            if dur >= MIN_ANIM_S and rng.random() < 0.5:
                # Keskipitkä kuva: puolet jää kehykseksi, puolet saa
                # hitaan puskun. Noppi tekee rytmistä epäsäännöllisen —
                # tasainen vuorottelu olisi metronomi.
                push_hi = PUSH_MAX if dur >= LONG_S else PUSH_MID_MAX
                move = _animated(rng, prev, push_hi)
            else:
                move = Move(start, start)
        if abs(move.start_scale - prev) < SAME_EPSILON:
            same_run += 1
        else:
            same_run = 0
        prev = move.start_scale
        moves.append(move)
    return moves


def _animated(rng: random.Random, prev: float, push_hi: float) -> Move:
    """Kuva joka liikkuu: puskun pituus, suunta ja alkukohta rajoissa.

    Puskun pituus on luvattu rajojen sisään, ja alkukohta arvotaan siitä
    kapeasta kaistasta jossa koko puskun mahtuu alueelle ilman että
    skaala koskaan alittaa ykkösen tai ylittää kattoa. Kummankaan suunnan
    kaista voi joskus olla tyhjä — silloin käännytään toiseen; senkin
    ollessa tyhjä kuva jää kehykseksi, koska lupaus on rajat eikä liike.
    """
    push = rng.uniform(PUSH_MIN, push_hi)
    direction = rng.choice((1.0, -1.0))
    for d in (direction, -direction):
        band = (
            (SCALE_MIN, SCALE_MAX - push) if d > 0
            else (SCALE_MIN + push, SCALE_MAX)
        )
        low = max(band[0], prev - MAX_JUMP)
        high = min(band[1], prev + MAX_JUMP)
        if low <= high:
            # Pyöristys voi työntää kymmenenes-tuhannesosan rajan yli;
            # raja pannaan täytäntöön pyöristyksen jälkeen, ei ennen.
            start = _clamp(round(rng.uniform(low, high), 4), low, high)
            return Move(start, start + d * push)
    return Move(_clamp(prev, SCALE_MIN, SCALE_MAX), _clamp(prev, SCALE_MIN, SCALE_MAX))


def _frame(rng: random.Random, prev: float, same_run: int, ceiling: float) -> float:
    """Arpoo paikallaan pysyvän skaalan: rajoissa, lähellä edellistä.

    Hyppy rajoitetaan ``MAX_JUMP``iin molempiin suuntiin, ja kun sama
    kehys on jo toistunut ``MAX_REPEAT`` kertaa, seuraava pakotetaan
    riittävän kauas pois — vaihtelu joka ei vaihtele on juuri se mikä
    korvattava on.
    """
    low = max(SCALE_MIN, prev - MAX_JUMP)
    high = min(ceiling, prev + MAX_JUMP)
    value = _clamp(round(rng.uniform(low, high), 4), low, high)
    if same_run >= MAX_REPEAT and abs(value - prev) < SAME_EPSILON:
        away = MAX_JUMP if prev <= (low + high) / 2 else -MAX_JUMP
        value = _clamp(prev + away, SCALE_MIN, min(ceiling, SCALE_MAX))
    return round(value, 4)
