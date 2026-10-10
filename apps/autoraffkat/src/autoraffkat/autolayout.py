"""Automaattinen asettelu: mikä asettelu kuuluu mihinkin kohtaan jaksoa.

Nopea kerros, ei tiedostoja. Syöte on leikkauksen kuvien kestot ja tulos
asettelu kullekin: ``single`` (kuva täyttää ruudun) tai ``wide_top`` (laaja
ylhäällä, lähikuva alla).

Sääntö on kuvan kesto, koska se on jo se luku jonka rytmimoottori on
päättänyt keskustelun tahdista (``decide.py``: nopea vuorottelu leikkaa
lyhyeen, pitkä puheenvuoro pitää kuvan). Pitkä pito on yhden ihmisen tarina,
ja sille kuuluu lähikuva koko ruudulla. Vuorottelussa katsoja haluaa nähdä
molemmat ja huoneen, ja laaja ylhäällä antaa sen ilman että jokainen leikkaus
heittää paikkaa. Reaktiokuvat seuraavat isäntäkuvansa asettelua: pitoa
vasten neliöpino, vuorottelun keskellä alapaneelin vaihto.

**Välkettä ei sallita.** Asettelun vaihto on isompi muutos kuin kuvan vaihto,
joten jakso jonka kesto jää alle ``MIN_RUN``in sulautuu pidempään
naapuriinsa. Muuten kahden sekunnin pito vuorottelun keskellä heittäisi koko
kuvan rakenteen ympäri ja takaisin.
"""

from __future__ import annotations

from .layout import LAYOUT_SINGLE, LAYOUT_WIDE_TOP

# Tästä kestosta ylöspäin kuva on pito (yhden puhujan jakso), sitä lyhyempi
# on osa vuorottelua. Makuarvo, ei mitattu: rytmiprofiilien minimikuvat ovat
# 1,4–4,5 s ja vuorottelun kuvat niiden ja muutaman sekunnin väliltä, joten
# 12 s on selvästi pitoa; arvo tarkistetaan oikealla jaksolla ensimmäisen
# vientikokeilun jälkeen.
HOLD = 12.0

# Lyhin jakso jonka asettelu saa pitää. Makuarvo, ei mitattu: vaihtoa ei
# haluta useammin kuin kerran parissakymmenessä sekunnissa.
MIN_RUN = 20.0


def plan(durations: list[float]) -> list[str]:
    """Asettelu kullekin kuvalle, ``durations``in kanssa samassa järjestyksessä."""
    if not durations:
        return []
    layouts = [LAYOUT_SINGLE if d >= HOLD else LAYOUT_WIDE_TOP for d in durations]
    for _ in range(len(durations)):
        runs = _runs(layouts, durations)
        if len(runs) < 2:
            break
        short = min(range(len(runs)), key=lambda i: (runs[i][3], i))
        if runs[short][3] >= MIN_RUN:
            break
        # Pidempään naapuriin; tasatilanteessa edelliseen.
        before = runs[short - 1][3] if short > 0 else -1.0
        after = runs[short + 1][3] if short + 1 < len(runs) else -1.0
        winner = runs[short - 1] if before >= after else runs[short + 1]
        for i in range(runs[short][1], runs[short][2]):
            layouts[i] = winner[0]
    return layouts


def _runs(layouts: list[str], durations: list[float]) -> list[tuple[str, int, int, float]]:
    """Peräkkäiset samat asettelut: ``(asettelu, alku, loppu, kesto)``."""
    runs: list[tuple[str, int, int, float]] = []
    start = 0
    for i in range(1, len(layouts) + 1):
        if i == len(layouts) or layouts[i] != layouts[start]:
            runs.append((layouts[start], start, i, float(sum(durations[start:i]))))
            start = i
    return runs


def changes(layouts: list[str]) -> list[int]:
    """Kuvien indeksit joissa asettelu vaihtuu edelliseen verrattuna."""
    return [i for i in range(1, len(layouts)) if layouts[i] != layouts[i - 1]]
