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
from dataclasses import dataclass, replace

import numpy as np

from .model import HOP

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

# Kokonaisalue, suhteena: 1.10 = 110 %. Alkuperäinen 1,06 piti puskun
# liian pienenä nähtäväksi (käyttäjä 2026-09-25); kasvojen tasauszoomin
# katto laskettiin samalla 1,25:stä 1,10:een, joten yhteensä kuva jää
# alle entisen 1,25 × 1,06:n.
SCALE_MIN = 1.00
SCALE_MAX = 1.10

# Liikkumattoman lyhyen kuvan katto. Lyhyt kuva saa kehyksen joka
# erottuu naapureistaan mutta ei aikaa animaatiolle.
STATIC_MAX = 1.04

# Puskun määrä, suhteena kuvan kestosta riippumatta. 2–5 % oli käyttäjän
# mukaan liian hidas huomattavaksi (2026-09-25): kokoero kuvan aikana on
# nähtävä, muuten liike on olematta. Nyt 4–8 %; keskipitkä kuva saa
# enintään 5 %, sen ajassa ei ole tilaa syvyydelle.
PUSH_MIN = 0.04
PUSH_MAX = 0.08
PUSH_MID_MAX = 0.05

# Suurin sallittu skaalero vierekkäisten kuvien välillä. Isompi hyppy
# luetaan leikkaukseksi — tarkoitus on kameran vaihtelu, ei uusi leikkaus.
MAX_JUMP = 0.03

# Montako samaa kehystä putkeen sallitaan. Kaksi on vaihtelua; kolme
# alkaa näyttää toistolta.
MAX_REPEAT = 2

# Kaksi kehystä lähempänä toisiaan kuin tämä luetaan samaksi kehykseksi.
SAME_EPSILON = 0.005

# ------------------------------------------------------------- shorts-tyyli
#
# Tyylit: «calm» on kameran vaihtelu (yllä olevat rajat, hypyt alle 3 %),
# «shorts» on lyhytvideoiden leikkaus: punch-in painotuksessa, pusku kun
# sama puhuja jatkaa. Käyttäjä 2026-09-25: vaihtoehtona, ei korvaajana.
STYLE_CALM = "calm"
STYLE_SHORTS = "shorts"
STYLES = (STYLE_CALM, STYLE_SHORTS)

# Punch-inin koko. Pelkkä koon muutos luetaan tarkoitukselliseksi vasta
# noin 15 %:sta, mutta perusrajaus on sivussa ja punch keskellä
# (``reframe.LEAD_ROOM``, käyttäjän idea 2026-09-25): leikkaus vaihtaa
# myös sommittelua, joten 12 % riittää. Full HD -lähdettä se säästää:
# täyttö on jo 1,78-kertainen, punchin kanssa 1,99.
PUNCH = 1.12

# Leikkaus näin paljon ennen lauseen alkua, kuten J-cutin ennakko: kuva
# vaihtuu kun sana alkaa, ei sen jälkeen.
PUNCH_LEAD = 0.1

# Punch-in tulee puhujan vaihtuessa, ei tauosta eikä voimakkuudesta.
# Koko jakson litteroinnista mitattuna (video files, 540 puheen alkua)
# tauon pituus, alun huippu, tason lasku ennen taukoa eikä sävelkulku
# erottanut lauseen alkua lauseen keskeltä: puhujat pitävät ½–1 s:n
# ajattelutaukoja kesken lauseen, ja jatko on jopa hieman kovempi. Vain
# puhujan vaihto erotti. Käyttäjä 2026-09-25: puhujan vaihto riittää, ja
# litterointi on mahdollinen vain colab-transcribella.


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
    style: str = STYLE_CALM,
    punches: list[bool] | None = None,
    split: list[bool] | None = None,
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
    if style == STYLE_SHORTS:
        count = len(durations)
        return _plan_shorts(rng, durations, wides,
                            punches or [False] * count, split or [False] * count)
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


def _plan_shorts(rng, durations, wides, punches, split) -> list[Move]:
    """Shorts: punch 115 %:iin tai 100 %, pusku vain pilkkomattomaan pitkään kuvaan.

    Saman kameran leikkauksessa koko joko pysyy tai hyppää punchin verran:
    pilkotun kuvan pohjapalat pysyvät 100 %:ssa, jottei pusku jätä seuraavaa
    punchia 5–10 %:n välihypyksi, joka näyttäisi virheeltä. Pusku on aina
    sisään: puhujan jatkaessa ajatus rakentuu, ja vapautus tulee
    leikkauksesta. Laaja pysyy paikallaan, kuten rauhallisessakin tyylissä.
    """
    moves = []
    for dur, wide, punch, piece in zip(durations, wides, punches, split, strict=True):
        if wide:
            moves.append(Move(1.0, 1.0))
        elif punch:
            moves.append(Move(PUNCH, PUNCH))
        elif piece or dur < MIN_ANIM_S:
            moves.append(Move(1.0, 1.0))
        else:
            push = rng.uniform(PUSH_MIN, PUSH_MAX if dur >= LONG_S else PUSH_MID_MAX)
            moves.append(Move(1.0, round(1.0 + push, 4)))
    return moves


def punch_segments(segments: list, grid, min_shot: float) -> list:
    """Lähikuvat pilkottuna punch-ineiksi puhujan vaihtuessa.

    Kaksi kohtaa, molemmat puhujan vaihtoja:

    * **Lähikuvan sisällä**: puhuja jatkaa sen jälkeen kun joku muu on
      puhunut välissä (välihuomautus, lyhyt vastaus). Pelkkä tauko saman
      puhujan puheessa ei ole vaihto.
    * **Vuoron alussa**: kun kuva palaa puhujaan, rajaus vaihtuu edellisestä
      kerrasta — perus ja punch vuorottelevat kameroittain, joten vuoron
      ottaminen näkyy myös koon vaihtumisena.

    Jokainen pala on vähintään ``min_shot``. Vain lähikuvat: laajan ja
    ryhmäkuvan pystyrajaus on jo puhujan mukaan. Silmukka kulkee puheen
    jaksojen eikä näytteiden yli.
    """
    by_camera = {lane.close_key: lane for lane in grid.speakers if lane.close_key}
    last: dict[str, bool] = {}
    out = []
    for seg in segments:
        lane = by_camera.get(seg.angle)
        lo = max(0, int(round((seg.start - grid.program_start) / HOP)))
        hi = min(grid.n, int(round((seg.end - grid.program_start) / HOP)))
        if lane is None or hi - lo < 2:
            out.append(seg)
            continue
        punch = not last[seg.angle] if seg.angle in last else False
        others = [other.on for other in grid.speakers if other is not lane]
        edges = np.diff(lane.on.astype(np.int8), prepend=0)
        starts = np.flatnonzero(edges == 1)
        ends = np.flatnonzero(edges == -1)
        cuts = []
        previous = seg.start
        for index in starts[(starts > lo) & (starts < hi)]:
            before = ends[ends <= index]
            if not len(before):
                continue
            gap = slice(int(before[-1]), int(index))
            if not any(other[gap].any() for other in others):
                continue
            at = grid.program_start + index * HOP - PUNCH_LEAD
            if at - previous >= min_shot and seg.end - at >= min_shot:
                cuts.append(at)
                previous = at
        bounds = [seg.start, *cuts, seg.end]
        for k in range(len(bounds) - 1):
            state = punch if k % 2 == 0 else not punch
            out.append(replace(seg, start=bounds[k], end=bounds[k + 1], punch=state))
            last[seg.angle] = state
    return out


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
    # Edellinen kuva voi olla paikallaan pysyvän katon yläpuolella (pusku
    # päättyi 110 %:iin). Silloin hyppyraja voittaa katon: näkyvä hyppy on
    # pahempi kuin lyhyt kuva hieman katon yli.
    high = max(high, low)
    value = _clamp(round(rng.uniform(low, high), 4), low, high)
    if same_run >= MAX_REPEAT and abs(value - prev) < SAME_EPSILON:
        away = MAX_JUMP if prev <= (low + high) / 2 else -MAX_JUMP
        value = _clamp(prev + away, SCALE_MIN, min(ceiling, SCALE_MAX))
    return round(value, 4)
