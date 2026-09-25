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
from itertools import pairwise

import numpy as np

from .model import HOP, Segment

PROJECT_W = 1080
PROJECT_H = 1920

# Tämän vähemmän näytteitä ei ole kehys, vaan sattuma: alle kolmen
# keyframen mediaani on kohinaa, kolme sekuntia on lyhin mitä kehykseksi
# kutsutaan.
MIN_SAMPLES = 3

# Aikatoleranssi kun kehyksen rivit poimitaan taulukosta, sekunteina.
# Keyframien aikaleimat horjuvat kehyksen verran GOP:n reunoilla.
EPS_S = 0.05

# Suurin kasvojen tasauszoomi täytön päälle. Käsin tehdyssä pohjassa Tomi
# tarvitsi 1,22 ollakseen Mikon kokoinen, mutta 1,25:n katto ja mikroliike
# päälle teki 130 %:n kuvia, ja se oli käyttäjän mukaan liikaa
# (2026-09-25). Täyttö suurentaa 1080-lähteen jo 1920:een; jokainen
# lisäprosentti on pehmeämpi kuva. Pienemmät kasvot jäävät pienemmiksi.
MAX_ZOOM = 1.10

# Kehys pysyy paikallaan. Tuolissa huojuminen ei ole uusi kehys, joten
# paikka on liukuva mediaani ``STEADY_WINDOW``in yli, ja kehys siirtyy vasta
# kun kasvot ovat olleet yli ``STEADY_SHIFT``in päässä ``STEADY_HOLD``in
# ajan: kamera on siirretty, tai joku nousi ja istui toiseen asentoon.
# 0,04 lähteen leveydestä on täytössä 137 px, kahdeksasosa rajausikkunasta.
STEADY_WINDOW = 30.0
STEADY_SHIFT = 0.04
STEADY_HOLD = 30.0


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
    # Lähikuvien suurin kasvojen mediaanikorkeus: laajan ja ryhmäkuvan
    # puhuja zoomataan kohti tätä, jotta rajaus ei hypi kokoa leikkauksessa
    # lähikuvasta laajaan.
    target: float | None = None


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
    return Look(zooms=zooms, eyeline=lines[reference], target=target)


def steady(times: np.ndarray, values: np.ndarray, window: float = STEADY_WINDOW,
           shift: float = STEADY_SHIFT, hold: float = STEADY_HOLD) -> list[tuple[float, float]]:
    """Paikka portaina: ``[(alkuaika, taso), …]``, taso vaihtuu harvoin.

    Liukuva mediaani ottaa huojunnan pois; porras syntyy vasta kun mediaani
    on pysynyt yli ``shift``in päässä nykyisestä tasosta ``hold``in ajan,
    ja uusi taso on sen jakson raakamediaani. Lyhyt käynti muualla —
    nousu ja takaisin — ei siirrä kehystä. Ajetaan viennissä, ei
    säätökierroksella.
    """
    order = np.argsort(times)
    t = np.asarray(times, dtype=np.float64)[order]
    v = np.asarray(values, dtype=np.float64)[order]
    if not len(t):
        return []
    lo = np.searchsorted(t, t - window / 2)
    hi = np.searchsorted(t, t + window / 2, side="right")
    smooth = np.array([np.median(v[a:b]) for a, b in zip(lo, hi, strict=True)])
    level = float(np.median(v[t <= t[0] + window]))
    steps = [(float(t[0]), level)]
    away = None
    for i in range(len(t)):
        if abs(smooth[i] - level) <= shift:
            away = None
            continue
        if away is None:
            away = i
        if t[i] - t[away] >= hold:
            level = float(np.median(v[away:i + 1]))
            steps.append((float(t[away]), level))
            away = None
    return steps


def level_at(steps: list[tuple[float, float]], at: float) -> float:
    """Portaan taso hetkellä ``at``."""
    level = steps[0][1]
    for start, value in steps:
        if start > at:
            break
        level = value
    return level


def plan_shot(fx: float, fy: float, width: int, height: int,
              zoom: float = 1.0, eyeline: float | None = None,
              face_w: float = 0.0, others=(),
              keep: tuple[float, float] | None = None,
              headroom: float = 1.0, lead: float = 0.0,
              keep_pad: float | None = None) -> Reframe | None:
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
    half = PROJECT_W / shown_w / 2
    reach = slack_x / shown_w
    # ``lead``: kasvojen paikka rajauksessa keskeltä, rajauksen leveyksinä
    # (negatiivinen = vasemmalle). Nolla keskittää. Siirto ei saa viedä
    # kasvojen marginaalia: iso kasvo kapeassa rajauksessa (Mikko: 300 px
    # 580 px:ssä) jäi 15–30 px:n päähän reunasta, ja hetkellinen liike
    # leikkasi (video files cf82863). Siirto pienenee kunnes marginaali mahtuu.
    start = fx - lead * 2 * half
    if lead and face_w:
        room = FACE_MARGIN * face_w
        low_c = fx + face_w / 2 + room - half
        high_c = fx - face_w / 2 - room + half
        start = min(high_c, max(low_c, start)) if low_c <= high_c else fx
    centre = _clear_neighbours(fx, face_w, others, half, reach, start=start)
    if keep is not None:
        # Kuvan omat kasvot (mediaanilaatikko) eivät saa jäädä reunasta
        # ulos: vakaa kehys siirtyy juuri sen verran, ei enempää. Myös
        # mikroliikkeen suurimmalla zoomilla ``headroom``: Final Cut skaalaa
        # keskipisteen ympäri ja siirtää sitten, joten ``m``-kertaisella
        # zoomilla ikkunan keskipiste lähteessä on 0,5 + (c - 0,5) / m ja
        # puolikas half / m. Ilman tätä reuna jäi 17–19 px kasvojen sisään.
        a, b = keep
        pad = (KEEP_PAD if keep_pad is None else keep_pad) * (b - a)
        a, b = a - pad, b + pad
        m = max(1.0, headroom)
        low = max(b - half, 0.5 + m * (b - 0.5) - half)
        high = min(a + half, 0.5 + m * (a - 0.5) + half)
        if low <= high:
            if centre < low:
                centre = low
            elif centre > high:
                centre = high
        centre = min(0.5 + reach, max(0.5 - reach, centre))
    move_x = min(slack_x, max(-slack_x, -(centre - 0.5) * shown_w))
    # Kuvan nosto ylös siirtää kasvoja ylös: kasvojen etäisyys keskeltä
    # (alas positiivinen) on ``(fy - 0,5) * korkeus - nosto``.
    target = fy if eyeline is None else eyeline
    lift = (fy - 0.5) * shown_h - (target - 0.5) * PROJECT_H
    lift = min(slack_y, max(-slack_y, lift))
    return Reframe(scale=float(zoom), pos_x=move_x / PROJECT_H * 100,
                   pos_y=lift / PROJECT_H * 100)


# Puhujan kasvojen ympärille jätettävä tila, kasvon leveydestä, kun rajausta
# siirretään naapurin takia: kasvot eivät saa päätyä reunaan kiinni.
FACE_MARGIN = 0.25

# Pidettävän kasvolaatikon pehmuste, kasvon leveydestä. Mediaanireunaan
# osuva rajaus leikkasi silti puolta ruuduista muutaman pikselin (Mikko 86:
# 2,3 % mediaani, 4,6 % pahin, video files c849a5e); viisi prosenttia on
# 15 px 300 px:n kasvoilla.
KEEP_PAD = 0.05

# Shorts-tyylin perusrajaus: kasvot sivuun, tilaa katseen suuntaan, ja
# punch-in keskelle. Käyttäjän idea (2026-09-25): leikkaus vaihtaa silloin
# sekä koon että sommittelun ja luetaan tarkoitukselliseksi pienemmälläkin
# zoomilla, mikä säästää Full HD -lähdettä. 0,12 rajausikkunan leveydestä
# on 130 px: selvästi sivussa, kaukana reunasta.
LEAD_ROOM = 0.12

# Pienempi pään käännös ei kerro katseen suuntaa (``turn``, ks. CLAUDE.md:
# luokat asettuivat +0,46:een ja -0,28:aan).
LEAD_TURN = 0.05


def _clear_neighbours(fx: float, face_w: float, others, half: float,
                      reach: float, start: float | None = None) -> float:
    """Rajausikkunan keskipiste niin ettei yksikään naapuri jää puolikkaaksi.

    Oletus on puhujan kasvot keskellä. Jos naapurin kasvot osuvat reunaan,
    ikkunaa siirretään niin että ne jäävät kokonaan ulos, tai jos se ei
    onnistu, kokonaan sisään — kumpikin vain jos puhujan kasvot pysyvät
    marginaaleineen sisällä ja ikkuna lähteen päällä. Muuten keskitys jää.
    Kaikki lähteen leveyden murto-osina; ``half`` on ikkunan puolikas ja
    ``reach`` kuinka kauas keskeltä ikkuna saa mennä.
    """
    margin = FACE_MARGIN * face_w
    low, high = 0.5 - reach, 0.5 + reach
    centre = min(high, max(low, fx if start is None else start))

    def fits(c: float) -> bool:
        return (low - 1e-9 <= c <= high + 1e-9
                and c - half <= fx - face_w / 2 - margin
                and fx + face_w / 2 + margin <= c + half)

    for ox, ow in others:
        a, b = ox - ow / 2, ox + ow / 2
        left, right = centre - half, centre + half
        if not (a < left < b or a < right < b):
            continue
        tries = (b + half, a + half) if ox < fx else (a - half, b - half)
        for candidate in tries:
            if fits(candidate):
                centre = candidate
                break
    return centre


class Reframer:
    """Mittaus → kehys. Lukematon luokka: taulukot ovat muistissa.

    ``tables`` on sama sanakirja jonka reaktiokerroksen mittaus tuottaa:
    median avain → ``{"times", "found", "x", "w", …}``-taulukko. Vastaa kuvaa
    kohden ``None``illa kun kehystä ei ole — mittaamaton kuva jää
    täytön keskelle eikä arvausta tehdä, ja siitä kerrotaan viennin
    varoituksissa.
    """

    def __init__(self, tables: dict, look: Look | None = None,
                 crowd: dict | None = None, crowd_tables: dict | None = None,
                 names: list[str] | None = None):
        self.tables = tables
        self.look = look or Look()
        # Laajat ja ryhmäkuvat: median avain -> ``seats.FileSeats`` ja
        # joukkotaulukko, sekä puhujien nimet ruudukon järjestyksessä.
        self.crowd = crowd or {}
        self.crowd_tables = crowd_tables or {}
        self.index = {name: i for i, name in enumerate(names or [])}
        self._steady: dict = {}

    def _levels(self, key, times, x, y):
        """Vakaa paikka (x- ja y-portaat) kerran per tiedosto tai istuja."""
        hit = self._steady.get(key)
        if hit is None:
            hit = (steady(times, x), steady(times, y))
            self._steady[key] = hit
        return hit

    def from_item(
        self,
        item,
        t0: float,
        t1: float,
        focus: str = "",
        headroom: float = 1.0,
        extra: float = 1.0,
        off_axis: bool = False,
        own: bool = False,
    ) -> Reframe | None:
        """Kehys yhdelle klipille: mediaanikasvo klipin omilta riveiltä.

        ``t0``/``t1`` ovat aikajanan sekunteja; ne käännetään tiedoston
        sekunteiksi sijoituksen kautta (``file_time_at``), ja taulukon
        rivit otetaan kestosta pienellä toleranssilla molemmin puolin.

        ``focus`` on laajan tai ryhmäkuvan puhuja: kehys hänen kasvoilleen,
        jos hänet on tunnistettu tästä tiedostosta.

        ``extra`` on paikallaan pysyvä lisäzoomi (punch-in, mikroliikkeen
        kehys). Se lasketaan kehykseen mukaan: Final Cut skaalaa kuvan
        keskipisteen ympäri, joten 100 %:lle laskettu sijainti veisi
        sivussa olevat kasvot zoomatessa pois keskiviivalta.
        """
        if item.key in self.crowd:
            return self._crowd_shot(item, t0, t1, focus, headroom, extra)
        table = self.tables.get(item.key)
        if table is None or "x" not in table or not item.width or not item.height:
            return None
        f0 = item.file_time_at(t0)
        f1 = item.file_time_at(t1)
        if f0 is None or f1 is None:
            return None
        # Paikka tiedoston vakaasta portaasta, ei kuvan omasta mediaanista:
        # saman kameran kuvat samassa kohdassa jaksoa rajataan täsmälleen
        # samoin, eikä huojunta nytkäytä rajausta leikkauksesta toiseen.
        # Siksi kuvan omien löytöjen määrä ei ole ehto: vaatimus kolmesta
        # jätti nopean rytmin lyhyet kuvat keskelle (252/594 oikealla
        # jaksolla, kasvoista 30–100 % ulkona). Tiedostolta vaaditaan.
        found = table["found"]
        if int(np.count_nonzero(found)) < MIN_SAMPLES:
            return None
        x, y, _h = _faces(table)
        xs, ys = self._levels(item.key, table["times"][found], x, y)
        middle = (float(f0) + float(f1)) / 2
        fx, fy = level_at(xs, middle), level_at(ys, middle)
        face_w = float(np.median(table["w"][found]))
        if own:
            # Pilkotun kuvan pala: sommittelu vaihtuu joka palassa joka
            # tapauksessa, joten pala kehystetään omien kasvojensa mukaan eikä
            # kameran vakaan paikan. Muuten punch osui ohi kun puhuja istui
            # tavallisesta sivussa (Mikko 10: 93 px, video files cf82863).
            here = found & (table["times"] >= float(f0) - EPS_S) & (table["times"] < float(f1) + EPS_S)
            if np.any(here):
                fx = float(np.median(table["x"][here] + table["w"][here] / 2))
                fy = float(np.median(1.0 - (table["y"][here] + table["h"][here] / 2)))
                face_w = float(np.median(table["w"][here]))
        lead = 0.0
        if off_axis and "turn" in table:
            # Katsoo oikealle (turn > 0) -> kasvot vasemmalle, tilaa oikealle.
            turn = float(np.median(table["turn"][found]))
            if abs(turn) >= LEAD_TURN:
                lead = -LEAD_ROOM if turn > 0 else LEAD_ROOM
        return plan_shot(
            fx, fy, item.width, item.height,
            zoom=self.look.zooms.get(item.key, 1.0) * extra, eyeline=self.look.eyeline,
            keep=_shot_box(table, found, f0, f1), headroom=headroom, lead=lead,
            face_w=face_w,
            # Sivuun rajattu kuva: kuvan omien kasvojen ympärille neljännes-
            # kasvon marginaali puskun loppuzoomissa. Vakaan paikan mukaan
            # laskettu marginaali ei riittänyt kun kasvot istuivat siitä
            # sivussa, ja pusku keskipisteen ympäri söi vielä ~20 px
            # (Mikko 148, 51, 117, 180, 182: 15–29 px reunasta, video files
            # a6d8732).
            keep_pad=FACE_MARGIN if lead else KEEP_PAD,
        )


    def _seat_at(self, item, table, seat, middle):
        """Istujan vakaa paikka (x, y) tiedoston hetkellä ``middle``."""
        if middle is None or len(seat.rows) < MIN_SAMPLES:
            return seat.x, seat.y
        rows = seat.rows
        xs, ys = self._levels(
            (item.key, seat.speaker), table["times"][table["frame"][rows]],
            table["x"][rows] + table["w"][rows] / 2,
            1.0 - (table["y"][rows] + table["h"][rows] / 2))
        return level_at(xs, middle), level_at(ys, middle)

    def _crowd_shot(self, item, t0: float, t1: float, focus: str,
                    headroom: float = 1.0, extra: float = 1.0) -> Reframe | None:
        """Laaja tai ryhmäkuva: puhujan kasvoille, naapurit kokonaan sisään tai ulos.

        Ilman puhujaa (päätykuva, tauko) tai kun puhuja ei ole tässä
        tiedostossa, rajataan näkyvimpään istujaan eikä keskelle: keskellä
        on usein tyhjä väli kahden ihmisen välissä, ja rajaus leikkasi
        molemmat kasvot puoliksi.
        """
        found = self.crowd.get(item.key)
        table = self.crowd_tables.get(item.key)
        if found is None or table is None or not found.seats:
            return None
        if not item.width or not item.height:
            return None
        speaker = self.index.get(focus)
        if speaker not in found.seats:
            speaker = max(found.seats.values(),
                          key=lambda s: (s.h, -abs(s.x - 0.5))).speaker
        seat = found.seats[speaker]
        f0, f1 = item.file_time_at(t0), item.file_time_at(t1)
        middle = (float(f0) + float(f1)) / 2 if f0 is not None and f1 is not None else None
        x, y = self._seat_at(item, table, seat, middle)
        keep = None
        if f0 is not None and f1 is not None:
            mine = np.zeros(len(table["frame"]), dtype=bool)
            mine[seat.rows] = True
            keep = _shot_box({**table, "times": table["times"][table["frame"]]},
                             mine, f0, f1)
        others = [(self._seat_at(item, table, other, middle)[0], other.w)
                  for other in found.seats.values() if other.speaker != speaker]
        target = self.look.target
        h = seat.h
        zoom = min(MAX_ZOOM, max(1.0, target / h)) if target and h > 0 else 1.0
        zoom *= extra
        return plan_shot(x, y, item.width, item.height, zoom=zoom,
                         eyeline=self.look.eyeline, face_w=seat.w, others=others,
                         keep=keep, headroom=headroom)


def focus_segments(segments: list, grid, crowd: dict[str, list[int]],
                   min_shot: float) -> list:
    """Laajan ja ryhmäkuvan kuvat pilkottuna puhujan mukaan pystyvientiä varten.

    ``crowd`` on raidan avain -> puhujat jotka kuvassa voivat olla.
    Kussakin kohdassa rajataan siihen joka puhuu yksin; hiljaisuus ja
    päällekkäispuhe pitävät edellisen, ja ennen ensimmäistä puhetta ollaan
    ensimmäisessä puhujassa. Minimikestoa lyhyempi pätkä sulautuu
    edelliseen — se olisi välähdys eikä kuva. Silmukka kulkee jaksojen eikä
    näytteiden yli, kuten päätöskerroksessa.
    """
    need = max(1, int(round(min_shot / HOP)))
    out: list = []
    for seg in segments:
        covered = crowd.get(seg.angle)
        lo = max(0, int(round((seg.start - grid.program_start) / HOP)))
        hi = min(grid.n, int(round((seg.end - grid.program_start) / HOP)))
        if not covered or hi <= lo:
            out.append(seg)
            continue
        on = np.stack([grid.speakers[p].on[lo:hi] for p in covered])
        alone = on.sum(axis=0) == 1
        who = np.where(alone, np.asarray(covered)[np.argmax(on, axis=0)], -1)
        if not (who >= 0).any():
            out.append(seg)
            continue
        index = np.where(who >= 0, np.arange(len(who)), 0)
        np.maximum.accumulate(index, out=index)
        who = who[index]
        who[who < 0] = who[who >= 0][0]

        runs: list[list[int]] = []  # [alku, loppu, puhuja]
        edges = np.flatnonzero(np.diff(who)) + 1
        bounds = [0, *edges.tolist(), len(who)]
        for a, b in pairwise(bounds):
            if runs and (b - a < need or runs[-1][2] == who[a]):
                runs[-1][1] = b
            else:
                runs.append([a, b, int(who[a])])
        if len(runs) > 1 and runs[0][1] - runs[0][0] < need:
            runs[1][0] = runs[0][0]
            runs.pop(0)
        for index_run, (a, b, speaker) in enumerate(runs):
            start = seg.start if index_run == 0 else grid.program_start + (lo + a) * HOP
            end = seg.end if index_run == len(runs) - 1 else grid.program_start + (lo + b) * HOP
            out.append(Segment(seg.angle, seg.label, start, end,
                               focus=grid.speakers[speaker].name))
    return out


def _shot_box(table: dict, rows: np.ndarray, f0, f1) -> tuple[float, float] | None:
    """Kuvan omien löytöjen mediaanilaatikko vaakasuunnassa, tai ``None``.

    Mediaani eikä ääripää: hetkellinen liike ei siirrä rajausta, mutta koko
    kuvan kestävä nojaus siirtää.
    """
    here = rows & (table["times"] >= float(f0) - EPS_S) & (table["times"] < float(f1) + EPS_S)
    if not np.any(here):
        return None
    left = table["x"][here]
    return float(np.median(left)), float(np.median(left + table["w"][here]))


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
        if not seg.angle:
            continue
        for item in items_for(timeline, seg.angle):
            if item.placement_at(seg.start) is None:
                continue
            if reframer.from_item(item, seg.start, seg.end, focus=seg.focus) is not None:
                count += 1
                break
    return count
