"""Kuka istuu missä, ja kuinka paljon sitä saa kuulla.

Kaksi asiaa, jotka kuuluvat yhteen: **istumajärjestys** mitataan kuvasta, ja
**panorointi** johdetaan siitä. Kumpikin on nopeaa laskentaa valmiiden
mittausten päällä — ei tiedostojen lukemista — joten tämä saa olla
säätökierroksessa mukana, samalla säännöllä kuin ``decide.py`` ja
``reactions.py``.

Panorointi ei kuulu tiedostoihin. Se on Final Cutin ``adjust-panner``,
koska se on tasopäätös siinä missä vaimennuskin: leikkaaja saa muuttaa sen
jälkikäteen ilman että mitään ajetaan uudestaan. Sama peruste kuin
reaktiokuvien omalla lanella.

Panorointi on myös **hyvin** hienovarainen. Kuulokkeilla kuunneltuna sitä ei
juuri huomaa, ja se on tarkoituskin: puhe kuuluu keskeltä, ja leveä
panorointi tekee kahden puhujan keskustelusta radiokuunnelman. Muutama
prosentti riittää antamaan kuvalle ja äänelle saman maantieteen.
"""

from __future__ import annotations

import numpy as np

from speechmix import panning

# Leveys ja sen perustelu asuvat kirjastossa, jotta automixer levittää
# samalla tavalla. Nimet pysyvät täällä, koska testit ja dokumentit
# viittaavat niihin.
PAN_WIDTH = panning.PAN_WIDTH
PAN_MAX_SPEAKERS = panning.PAN_MAX_SPEAKERS

# Kuinka monta mittausta puhujalta tarvitaan ennen kuin puolta uskotaan.
#
# Viisi, ei sata. Kysymys on yksi merkki puhujaa kohti, ja luokat ovat
# kaukana toisistaan: mitattuna oikealla jaksolla vasemmalla istuvan
# mediaani oli +0,46 ja oikealla istuvan -0,28. Viidellä satunnaisella
# ruudulla merkki osui 400/400 kertaa. Sata olisi vaatinut täyden
# mittauksen, ja silloin panorointi riippuisi minuuttien ajosta jota se ei
# tarvitse — ks. ``video.analyse.seating``.
SIDE_MIN_FRAMES = 5


def side(table: dict) -> float:
    """Puhujan paikka vasen–oikea, välillä -1…+1, tai ``nan``.

    Mitta on ``turn``: nenän sijainti silmien puolivälin suhteen, jaettuna
    silmien etäisyydellä. Kaksi vastakkain istuvaa katsoo toisiaan, joten
    **vasemmalla istuva katsoo oikealle** ja hänen nenänsä on kuvassa
    silmiensä oikealla puolella — ``turn`` on positiivinen.

    Merkki on siis päinvastoin kuin arvaus «nenä osoittaa sinne missä
    istutaan», ja juuri siksi se on tarkistettu kuvista eikä päätelty:
    oikealla jaksolla vasemmalla istuvan mediaani oli +0,46 ja oikealla
    istuvan -0,28, molemmissa osissa sama.

    Kehystys (``cx``) ei kelpaa tähän. Samalla jaksolla mitattuna molemmat
    olivat kuvan oikealla puoliskolla, +0,51 ja +0,60, eli kehystys kertoo
    kuvaajan tavoista eikä istumajärjestyksestä.
    """
    found = np.asarray(table.get("found", []), dtype=bool)
    if found.sum() < SIDE_MIN_FRAMES:
        return float("nan")
    turn = np.asarray(table["turn"], dtype=np.float64)[found]
    turn = turn[np.isfinite(turn)]
    if turn.size < SIDE_MIN_FRAMES:
        return float("nan")
    # Mediaani eikä keskiarvo: yksittäinen väärin osunut maamerkki voi olla
    # kaukana, eikä sen pidä siirtää koko puhujaa.
    return float(np.clip(np.median(turn), -1.0, 1.0))


def order(sides: dict) -> list:
    """Puhujat vasemmalta oikealle. Mittaamattomat viimeisiksi, nimen mukaan.

    Järjestys on ``-turn``: positiivinen ``turn`` on vasemmalla, ja
    vasemmalta oikealle luettuna se tarkoittaa laskevaa ``turn``ia.
    """
    known = sorted((n for n in sides if np.isfinite(sides[n])),
                   key=lambda n: -sides[n])
    unknown = sorted(n for n in sides if not np.isfinite(sides[n]))
    return known + unknown


def pans(sides: dict) -> dict:
    """Puhuja -> panorointi Final Cutin asteikolla, -100…+100.

    Paikat jaetaan tasan mitatun järjestyksen mukaan, ei mitatun kulman
    suhteessa: kulma kertoo **järjestyksen** luotettavasti mutta etäisyyden
    ei lainkaan — se riippuu tuolien asennosta ja objektiivista. Kolme
    puhujaa on siis vasen, keskus, oikea, ei «kaksi lähes samassa».

    Kaikki mittaamattomat jäävät keskelle: paikkaa jota ei tiedetä ei
    arvata, ja keskus on ainoa arvo joka ei ole koskaan väärin.
    """
    names = order(sides)
    measured = [n for n in names if np.isfinite(sides.get(n, float("nan")))]
    out = dict.fromkeys(sides, 0.0)
    for name, value in zip(measured, panning.spread(len(measured)), strict=True):
        out[name] = value
    return out
