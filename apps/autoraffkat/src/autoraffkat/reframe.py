"""Vertical reframing: per-shot framing from measured face positions.

Lähde on jo Vision-mitattu keyframeä kohden tiedostoa kohden — sama
välimuisti jota reaktiokerros käyttää — ja tämä moduuli kääntää mittauksen
klipin muodoksi: lähde täyttää projektin korkeuden ja kasvot osuvat
keskiviivalle. Tiedostoa ei avata täällä, sama sääntö kuin ``decide.py``ssä.

Geometria (Apuen oma FCPXML «Animation»-dokumentti, jonka mukaan position
yksikkö on projektin korkeuden prosentti **molemmissa** akseleissa ja scale
on murto-osa klipin sovitetusta peruskoosta — ensimmäinen aito tuonti
Final Cutiin varmistaa johdannaisen, ei tämä tiedosto):

1920×1080-lähde 1080×1920-projektissa: sovitus skaalaa 0.5625
(1080×607.5), korkeuden täyttö vaatii kertaa 3.1605, jolloin leveyttä
näkyy 3413 px ja lähdeleveydestä 1080/3413 ≈ 0.3165. Täytön jälkeen
näytetty korkeus on täsmälleen projektin korkeus, eli koko lähdekorkeus
on näkyvissä — **pystysiirtoa ei koskaan tarvita, ja mikä tahansa
nollasta poikkeava y paljastaisi reunan.** Siksi ``pos_y`` on aina nolla.
"""

from __future__ import annotations

from dataclasses import dataclass

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


@dataclass
class Reframe:
    """Yhden kuvan kehys: täyttöskaala ja vaakasiirto, ``pos_y`` aina nolla.

    Skaala on murto-osa klipin sovitetusta peruskoosta (fit), siirto
    projektin korkeuden prosentteina — Final Cutin omat yksiköt, eivät
    pikseleitä.
    """

    scale: float
    pos_x: float
    pos_y: float = 0.0


def plan_shot(cx: float, width: int, height: int) -> Reframe | None:
    """Yhden kuvan kehys mediaanikasvo-x:stä ja lähteen mitoista.

    ``cx`` on kasvojen keskipiste normalisoituna lähteen leveydestä
    (0 = vasen reuna). Palauttaa ``None`` kun kehystä ei ole: mitat
    puuttuvat tai lähde täyttää korkeutensa jo sovituksella, jolloin
    mitään ei kirjoiteta — tyhjä muunnos olisi Final Cutille asetus
    siinä missä mikä tahansa.
    """
    if not width or not height:
        return None
    fit = min(PROJECT_W / width, PROJECT_H / height)
    extra = PROJECT_H / (height * fit)
    if extra <= 1.0:
        # Sovitus täyttää korkeuden jo valmiiksi: ei rajattavaa, ei
        # muotoa. Skaala alle ykkösen ei ole kehystys vaan venytys.
        return None
    displayed_w = width * fit * extra
    # Siirto rajataan niin että rajausikkuna ei koskaan astu sisällön
    # ulkopuolelle — reunalle paljastuisi rako eikä kameraa olekaan.
    half_gap = (displayed_w - PROJECT_W) / 2 / displayed_w
    cx = min(0.5 + half_gap, max(0.5 - half_gap, cx))
    pos_x = -(cx - 0.5) * displayed_w / PROJECT_H * 100
    return Reframe(scale=extra, pos_x=pos_x)


class Reframer:
    """Mitatus → kehys. Lukematon luokka: taulukot ovat muistissa.

    ``tables`` on sama sanakirja jonka reaktiokerroksen mittaus tuottaa:
    median avain → ``{"times", "found", "cx", …}``-taulukko. Vastaa kuvaa
    kohden ``None``illa kun kehystä ei ole — mittaamaton kuva saa
    letterboxin eikä arvausta, ja siitä kerrotaan viennin varoituksissa.
    """

    def __init__(self, tables: dict):
        self.tables = tables

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
        if table is None or not item.width or not item.height:
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
        return plan_shot(
            float(np.median(table["cx"][rows])), item.width, item.height
        )


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
