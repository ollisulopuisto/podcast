"""Puhemaskit ruudukolla: kuka on äänessä, kenen mikki on kiinni.

Siirretty tänne sovelluksista, ei kopioitu: nämä olivat autoraffkatin
``decide.py``:ssä ja ``audio/mix.py``:ssä, ja molemmat tarvitsivat samat
apurit. Kaksi kopiota samasta maskilogiikasta olisi täsmälleen se ajautuminen
jonka takia tämä paketti on olemassa.

Ruudukko on aikajanan aikaa ``HOP`` sekunnin askelin. Mikään täällä ei lue
tiedostoja eikä tunne istuntoformaattia: sisään maskeja, ulos maskeja.

``settings`` on mikä tahansa olio jolta löytyvät kentät joita funktio lukee —
isäntä omistaa asetukset, kirjasto lukee niistä vain sen mitä tarvitsee.
"""

import numpy as np

from .grid import HOP_SEC

#: Ruudukon askel sekunneissa. Sama luku ohjaa kuvan leikkausta ja äänen
#: vaimennusta, koska molemmat lukevat samaa puheentunnistusta — ja siksi
#: se on **yksi olio** eikä kaksi yhtä suurta lukua. Se asuu ``grid``issä,
#: joka on ruudukon moduuli; tämä nimi jää, koska kolme moduulia ja
#: molemmat sovellukset tuovat sen täältä.
HOP = HOP_SEC


def runs(values: np.ndarray) -> list[tuple[int, int, int]]:
    """Jaksot (alku, loppu, arvo). Loppu on poissulkeva."""
    if values.size == 0:
        return []
    change = np.flatnonzero(values[1:] != values[:-1]) + 1
    bounds = np.concatenate(([0], change, [values.size]))
    return [
        (int(bounds[i]), int(bounds[i + 1]), int(values[bounds[i]]))
        for i in range(bounds.size - 1)
    ]

def hops(seconds: float) -> int:
    """Sekunnit ruudukon askeliksi, aina vähintään yksi."""
    return max(1, int(round(seconds / HOP)))

def open_runs(mask: np.ndarray, k: int) -> np.ndarray:
    """Poistaa k:ta lyhyemmät todet jaksot. Tämä on vahvistusaika."""
    if k <= 1 or mask.size == 0:
        return mask
    out = mask.copy()
    for start, end, value in runs(mask.astype(np.int8)):
        if value and (end - start) < k:
            out[start:end] = False
    return out

def open_windows(
    on: np.ndarray, lookahead: float, hold: float, min_open: float
) -> np.ndarray:
    """Mistä mikki on auki, kun ``on`` on kynnyksen ylitys.

    Kynnyksen ylitys sellaisenaan on kelvoton portin ohjaukseksi: se välkkyy
    tavuvälien yli ja reagoi yksittäiseen yskäisyyn. Kolme muunnosta tekevät
    siitä käyttökelpoisen, ja ne vastaavat kolmea säädintä:

    * ``min_open`` pudottaa liian lyhyet jaksot — yskäisy ja naksahdus eivät
      avaa mikkiä.
    * ``lookahead`` avaa portin ennen puheen alkua. Tämä on mahdollista vain
      koska käsittely on jälkikäteistä; reaaliaikainen portti ei voi avautua
      ennen kuin ääni on jo tullut, ja siksi siltä katoaa sanojen alkuja.
    * ``hold`` pitää portin auki puheen jälkeen, jolloin lauseen häntä ja
      hengitys jäävät mukaan eikä väleihin tule pumppausta.

    Silmukka kulkee jaksojen yli, ei näytteiden.
    """
    if on.size == 0:
        return on
    mask = open_runs(on, hops(min_open)) if min_open > 0 else on
    before = hops(lookahead) if lookahead > 0 else 0
    after = hops(hold) if hold > 0 else 0
    if not (before or after):
        return mask
    out = np.zeros_like(mask)
    for start, end, value in runs(mask.astype(np.int8)):
        if value:
            out[max(0, start - before) : min(mask.size, end + after)] = True
    return out

def trim_end(mask: np.ndarray, seconds: float) -> np.ndarray:
    """Lyhentää jokaista totta jaksoa lopusta annetun verran.

    Tätä tarvitaan vaimennuksen paluuseen: liu'un on ehdittävä loppuun ennen
    kuin peittävä ääni loppuu, muuten se kuuluu hiljaisuudessa.
    """
    if seconds <= 0 or mask.size == 0:
        return mask
    cut = hops(seconds)
    out = np.zeros_like(mask)
    for start, end, value in runs(mask.astype(np.int8)):
        if value and end - start > cut:
            out[start : end - cut] = True
    return out

def drop_short(mask: np.ndarray, seconds: float) -> np.ndarray:
    """Pudottaa annettua lyhyemmät todet jaksot pois."""
    return open_runs(mask, hops(seconds)) if seconds > 0 else mask

def close_gaps(mask: np.ndarray, seconds: float) -> np.ndarray:
    """Täyttää annettua lyhyemmät epätodet jaksot. ``drop_short``in duaali.

    Reunat eivät ole aukkoja. ``~mask`` tekisi ensimmäisestä ja viimeisestä
    epätodesta jaksosta täytettävän, jolloin maski laajenisi molempiin päihin
    — ja portin tapauksessa se tarkoittaisi vaimennusta ennen kuin peittävä
    ääni on tullut, mikä on juuri se lasku joka kuuluu.
    """
    if seconds <= 0 or mask.size == 0:
        return mask
    out = mask.copy()
    for start, end, value in runs(mask.astype(np.int8)):
        if value or start == 0 or end == mask.size:
            continue
        if (end - start) < hops(seconds):
            out[start:end] = True
    return out

def speech_masks(grid) -> dict:
    """Puhuja -> milloin hän on äänessä, ruudukon tarkkuudella."""
    return {lane.name: np.asarray(lane.on, dtype=bool)
            for lane in getattr(grid, "speakers", [])}

def _gates(grid, settings: object) -> tuple[list, list]:
    """Portit joita vaimennus lukee: ``(auki, peittävä)`` puhujittain.

    Erillään, koska sekä ``duck_masks`` että ``covering_masks`` tarvitsevat
    juuri nämä. Kaksi kappaletta samasta portista ajautuisi erilleen, ja ero
    näkyisi vasta siinä että lasku ajoittuu eri kohtaan kuin vaimennus alkaa.
    """
    active = np.stack([lane.on for lane in grid.speakers])
    levels = np.stack([lane.level for lane in grid.speakers])
    # Vain äänessä olevat kilpailevat; hiljainen ei voi olla kovin.
    loudest = np.where(active, levels, -300.0).max(axis=0)
    keep = active & (levels >= loudest - settings.duck_dominance_db)
    # Auki: ennakko mukana, jotta sanan alku ei katoa.
    opened = [
        open_windows(
            keep[i], settings.duck_lookahead, settings.duck_hold, settings.duck_min_open
        )
        for i in range(len(grid.speakers))
    ]
    # Peittävä puhe. Ilman ennakkoa, koska tämä ajoittaa laskun: lasku ei saa
    # alkaa ennen kuin peittävä ääni on tullut. Lopusta leikataan pito ja
    # paluun mitta pois, jotta myös nousu ehtii tapahtua peittävän äänen alla
    # eikä sen jälkeisessä hiljaisuudessa.
    masking = [
        trim_end(
            open_windows(keep[i], 0.0, settings.duck_hold, settings.duck_min_open),
            settings.duck_hold + settings.duck_release,
        )
        for i in range(len(grid.speakers))
    ]
    return opened, masking


def covering_masks(grid, settings: object) -> dict:
    """Milloin **jonkun muun** puhe peittää tämän puhujan.

    Sama ``others`` jota ``duck_masks`` käyttää, mutta ulospäin: laskun
    nopeus riippuu siitä osuuko vaimennuksen alku tämän maskin **nousuun**.
    Osuu = peittävän puhujan aloitus on juuri siinä, ja lasku jää sen alle.
    """
    if grid is None or not settings.duck or len(grid.speakers) < 2:
        return {}
    _, masking = _gates(grid, settings)
    out = {}
    for i, lane in enumerate(grid.speakers):
        others = np.zeros_like(masking[i])
        for j in range(len(grid.speakers)):
            if j != i:
                others |= masking[j]
        out[lane.name] = others
    return out


def duck_masks(grid, settings: object) -> dict:
    """Puhujakohtaiset «mikki kiinni» -maskit ruudukossa.

    Ohjaus on sama puheentunnistus kuin kuvan leikkauksessa — se on jo säädetty
    herkkyyssäätimillä ja näkyy esikatselupalkissa — mutta omilla ajoillaan.

    Kolme sääntöä, joista jokainen korjaa yhden tavan kuulostaa pahalta:

    **Vaimennus tapahtuu vain toisen puheen alla.** Jos kukaan ei puhu, kaikki
    mikit jäävät auki. Hiljaisuuteen laskeva portti kuuluu aina, koska mikään
    ei peitä sitä; toisen puhujan aloituksen alla lasku katoaa kuulumattomiin.
    Tämä on syy siihen että maskeri lasketaan **ilman ennakkoa**: lasku ei saa
    alkaa ennen kuin peittävä ääni on jo tullut.

    **Kovin voittaa.** Kaksi mikkiä samassa huoneessa kuulevat molemmat
    puhujat, joten kumpikin ylittää kynnyksen — mitattuna 41 % ajasta yhtä
    aikaa. Vuoto on kuitenkin mediaanissa 12,8 dB hiljempaa, joten auki jää
    kovin ja ne jotka ovat ``duck_dominance_db``:n sisällä siitä.

    **Lyhyitä vaimennuksia ei tehdä.** Ilman tätä syntyi 20 millisekunnin
    kuoppia: naksahdus, ei vaimennus.

    **Eikä lyhyitä aukkoja niiden sisään.** Hystereesi oli yksipuolinen:
    lyhyet vaimennukset pudotettiin, lyhyitä aukkoja ei poistanut mikään.
    Vuoto on mediaanissa 12,8 dB hiljempaa, mutta plosiivi tai naurahdus käy
    ``duck_dominance_db``:n sisällä, ja yksi sellainen osti vuotavalle mikille
    ``duck_min_open + duck_hold`` mittaisen aukon kesken toisen lausetta.
    Täystasoinen vuoto puolen sekunnin ajan toisen mikin omaa puhetta vasten
    on kampasuodatusta, ja se kuuluu metallisena kaikuna — ei porttina, joten
    sitä ei osaa etsiä portin säätimistä.
    """
    if grid is None or not settings.duck or len(grid.speakers) < 2:
        return {}
    opened, masking = _gates(grid, settings)

    out = {}
    for i, lane in enumerate(grid.speakers):
        others = np.zeros_like(opened[i])
        for j in range(len(grid.speakers)):
            if j != i:
                others |= masking[j]
        closed = others & ~opened[i]
        # Aukot umpeen ennen kuin lyhyet vaimennukset pudotetaan: vaimennus
        # jonka välähdys katkaisee on **yksi** vaimennus, ja se on
        # arvioitava sellaisena.
        closed = close_gaps(closed, settings.duck_min_gap)
        out[lane.name] = drop_short(closed, settings.duck_min_closed)
    return out

def solo_masks(grid) -> dict:
    """Puhujakohtaiset «vain minä äänessä» -maskit ruudukossa.

    Ristivuodon estimointi tarvitsee juuri nämä: jaksot joissa kohdemikin
    oma puhuja on vaiti ja lähde puhuu ovat ainoa paikka jossa kohteessa
    kuuluva ääni on **pelkkää** vuotoa. Muualta estimoitu suodin vähentäisi
    kohteen omaa puhetta, koska sekin korreloi lähteen kanssa aina kun
    puhujat menevät päällekkäin.
    """
    if grid is None or len(grid.speakers) < 2:
        return {}
    active = np.stack([lane.on for lane in grid.speakers])
    out = {}
    for i, lane in enumerate(grid.speakers):
        others = np.zeros_like(active[i])
        for j in range(len(grid.speakers)):
            if j != i:
                others |= active[j]
        out[lane.name] = active[i] & ~others
    return out

