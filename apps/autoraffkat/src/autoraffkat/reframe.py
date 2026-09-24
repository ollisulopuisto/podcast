"""Vertical reframing: per-shot framing from measured face positions.

Lähde on jo Vision-mitattu keyframeä kohden tiedostoa kohden — sama
välimuisti jota reaktiokerros käyttää — ja tämä moduuli kääntää mittauksen
klipin muodoksi. Tiedostoa ei avata täällä, sama sääntö kuin ``decide.py``ssä.

Pohja on Final Cutin oma: kuvakulmalle ``<adjust-conform type="fill"/>``
(Spatial Conform «Fill») ja sen päälle ``adjust-transform``. Näin
käyttäjän itse tekemä pystypohja on kirjoitettu (hmh hannes vertical base,
2026-09-25): Tomin kamera ``scale="1.22 1.22"``, ``position="-30.7292
-8.59375"``, Mikon kamera 100 % ja pelkkä vaakasiirto.

Täytössä skaala on suhteessa **täytettyyn** kokoon: 1,0 on lähde joka
täyttää projektin korkeuden, 1920×1080-lähteellä 3413×1920 px, josta
näkyy leveydeltään 1080/3413 ≈ 0,3165. Sijainti on prosentteina projektin
korkeudesta molemmissa akseleissa (1 = 19,2 px), y ylöspäin positiivinen.
100 %:ssa pystysuunnassa ei ole liikkumavaraa — koko lähdekorkeus on
näkyvissä — joten pystysiirto on mahdollinen vain zoomatulle kuvalle, ja
vain sen verran kuin zoomi antaa.

Kasvojen paikka on **laatikko** (``x + w/2``, ``y + h/2``), ei
``cx``/``cy``: ne ovat maamerkkien keskiarvo kasvolaatikon *sisällä*
(Visionin ``normalizedPoints`` normalisoidaan laatikkoon), joten ne ovat
~0,5 missä kasvot sitten ovatkin. Kehystys luki niitä kuvan paikkana ja
keskitti käytännössä kuvan keskelle.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .decide import WIDE_LABEL

PROJECT_W = 1080
PROJECT_H = 1920

# Tämän vähemmän näytteitä ei ole kehys, vaan sattuma: alle kolmen
# keyframen mediaani on kohinaa, kolme sekuntia on lyhin mitä kehykseksi
# kutsutaan.
MIN_SAMPLES = 3

# Aikatoleranssi kun kehyksen rivit poimitaan taulukosta, sekunteina.
# Keyframien aikaleimat horjuvat kehyksen verran GOP:n reunoilla.
EPS_S = 0.05

# Suurin zoomi täytön päälle. Käsin tehdyssä pohjassa Tomi tarvitsi 1,22
# ollakseen Mikon kokoinen; täyttö suurentaa 1080-lähteen jo 1920:een, eli
# 1,25 on 2,2-kertainen suurennus lähteestä, ja jokainen lisäprosentti on
# pehmeämpi kuva. Pienemmät kasvot jäävät pienemmiksi eikä niitä pakoteta.
MAX_ZOOM = 1.25


@dataclass
class Reframe:
    """Yhden kuvan kehys: skaala täytön päälle ja siirto.

    Skaala on suhde täytettyyn kokoon (1,0 = korkeus täynnä), siirto
    projektin korkeuden prosentteina — Final Cutin omat yksiköt, eivät
    pikseleitä.
    """

    scale: float
    pos_x: float
    pos_y: float = 0.0


@dataclass
class Look:
    """Koko jakson kehystyssäännöt: kameroittain zoomi ja yhteinen silmälinja.

    Zoomi on kameran eikä kuvan ominaisuus: sama kamera eri zoomilla
    peräkkäisissä kuvissa näyttäisi hyppivältä. ``eyeline`` on
    100 %:n kameran kasvojen korkeus ylhäältä (0–1 projektin
    korkeudesta); ``None`` pitää kasvot siinä kohdassa jossa ne olisivat.
    """

    zooms: dict[str, float] = field(default_factory=dict)  # median avain -> zoomi
    eyeline: float | None = None


def _faces(table: dict, rows=None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Kasvojen keskipiste (x, y ylhäältä) ja korkeus löydetyiltä riveiltä."""
    found = table["found"] if rows is None else rows
    x = table["x"][found] + table["w"][found] / 2
    y = 1.0 - (table["y"][found] + table["h"][found] / 2)
    return x, y, table["h"][found]


def look(tables: dict, timeline, roles) -> Look:
    """Kameroiden zoomit tasaavat kasvojen koon; suurimmat kasvot 100 %.

    Mediaani kameran kaikista löydöistä: ohjelman mittainen otos ei
    heilu yksittäisen nojautumisen mukana. Kasvojen korkeus on lähteen
    korkeuden murto-osa, ja täytössä lähteen korkeus on projektin korkeus,
    joten suhde on suoraan zoomi.
    """
    heights: dict[str, float] = {}
    lines: dict[str, float] = {}
    for key in roles.closes.values():
        for item in timeline.track_media(key):
            table = tables.get(item.key)
            if table is None or "h" not in table:
                continue
            if int(np.count_nonzero(table["found"])) < MIN_SAMPLES:
                continue
            _x, y, h = _faces(table)
            heights[item.key] = float(np.median(h))
            lines[item.key] = float(np.median(y))
    if not heights:
        return Look()
    target = max(heights.values())
    zooms = {k: float(min(MAX_ZOOM, max(1.0, target / h))) for k, h in heights.items()}
    reference = max(heights, key=heights.get)
    return Look(zooms=zooms, eyeline=lines[reference])


def plan_shot(fx: float, fy: float, width: int, height: int,
              zoom: float = 1.0, eyeline: float | None = None) -> Reframe | None:
    """Yhden kuvan kehys kasvojen paikasta, täytön päälle.

    ``fx`` on kasvojen keskipiste lähteen leveydestä (0 = vasen reuna),
    ``fy`` korkeudesta ylhäältä. Vaakasuunnassa kasvot keskiviivalle,
    pystysuunnassa ``eyeline``lle jos zoomi antaa liikkumavaraa. Siirto
    rajataan niin ettei rajausikkuna koskaan astu sisällön ulkopuolelle.
    Palauttaa ``None`` kun kehystettävää ei ole: mitat puuttuvat tai lähde
    ei ole projektia leveämpi eikä zoomia ole.
    """
    if not width or not height:
        return None
    fill = max(PROJECT_W / width, PROJECT_H / height)
    shown_w = width * fill * zoom
    shown_h = height * fill * zoom
    if shown_w <= PROJECT_W + 1e-6 and zoom <= 1.0:
        return None
    slack_x = max(0.0, (shown_w - PROJECT_W) / 2)
    slack_y = max(0.0, (shown_h - PROJECT_H) / 2)
    move_x = min(slack_x, max(-slack_x, -(fx - 0.5) * shown_w))
    # Kuvan nosto ylös siirtää kasvoja ylös: kasvojen etäisyys keskeltä
    # (alas positiivinen) on ``(fy - 0,5) * korkeus - nosto``.
    target = fy if eyeline is None else eyeline
    lift = (fy - 0.5) * shown_h - (target - 0.5) * PROJECT_H
    lift = min(slack_y, max(-slack_y, lift))
    return Reframe(scale=float(zoom), pos_x=move_x / PROJECT_H * 100,
                   pos_y=lift / PROJECT_H * 100)


class Reframer:
    """Mittaus → kehys. Lukematon luokka: taulukot ovat muistissa.

    ``tables`` on sama sanakirja jonka reaktiokerroksen mittaus tuottaa:
    median avain → ``{"times", "found", "x", "w", …}``-taulukko. Vastaa kuvaa
    kohden ``None``illa kun kehystä ei ole — mittaamaton kuva jää
    täytön keskelle eikä arvausta tehdä, ja siitä kerrotaan viennin
    varoituksissa.
    """

    def __init__(self, tables: dict, look: Look | None = None):
        self.tables = tables
        self.look = look or Look()

    def from_item(
        self,
        item,
        t0: float,
        t1: float,
    ) -> Reframe | None:
        """Kehys yhdelle klipille: mediaanikasvo klipin omilta riveiltä.

        ``t0``/``t1`` ovat aikajanan sekunteja; ne käännetään tiedoston
        sekunteiksi sijoituksen kautta (``file_time_at``), ja taulukon
        rivit otetaan kestosta pienellä toleranssilla molemmin puolin.
        """
        table = self.tables.get(item.key)
        if table is None or "x" not in table or not item.width or not item.height:
            return None
        f0 = item.file_time_at(t0)
        f1 = item.file_time_at(t1)
        if f0 is None or f1 is None:
            return None
        rows = (
            (table["times"] >= f0 - EPS_S)
            & (table["times"] < f1 + EPS_S)
            & table["found"]
        )
        if int(rows.sum()) < MIN_SAMPLES:
            return None
        x, y, _h = _faces(table, rows)
        return plan_shot(
            float(np.median(x)), float(np.median(y)), item.width, item.height,
            zoom=self.look.zooms.get(item.key, 1.0), eyeline=self.look.eyeline,
        )


def close_up_tables(tables: dict, timeline, roles) -> dict:
    """Mittaustaulukot vain lähikuvien medioille.

    Kehys on *yhden* kasvon mediaani, joten se kuuluu vain kuvaan jossa on
    yksi ihminen. Ryhmäkuvalle taulukko voi olla olemassa — sama kamera oli
    joskus lähikuva — ja silloin rajaus leikkaisi toisen puhujan pois. Ilman
    taulukkoa kuva jää täytön keskelle, kuten laaja.
    """
    keep = {item.key for key in roles.closes.values()
            for item in timeline.track_media(key)}
    return {key: table for key, table in tables.items() if key in keep}


def items_for(timeline, key: str) -> list:
    """Segmentin kulman media-alkiot: raita osineen tai suora media-avain.

    Monikamerassa kulma on raita (osineen); tasaviedossa avain on media.
    Molemmat päättyvät tänne, jotta laskuri ja kirjoittaja eivät voi
    eriä siitä mistä kehys kysytään.
    """
    items = timeline.track_media(key)
    if items:
        return items
    by_key = timeline.media_by_key()
    return [by_key[key]] if key in by_key else []


def framed_count(reframer: Reframer, timeline, segments: list) -> int:
    """Montako lähikuvaa saa kehyksen — sama kysymys kuin kirjoittajalla.

    Laajat ohitetaan ja mittaamattomat jäävät ilman. Luku erottaa
    «mitattu mutta mikään ei täytä» tyhjästä mittauksesta: molemmat
    kuuluvat, mutta eri varoituksella eikä hiljaisuudella.
    """
    count = 0
    for seg in segments:
        if seg.label == WIDE_LABEL or not seg.angle:
            continue
        for item in items_for(timeline, seg.angle):
            if item.placement_at(seg.start) is None:
                continue
            if reframer.from_item(item, seg.start, seg.end) is not None:
                count += 1
                break
    return count
