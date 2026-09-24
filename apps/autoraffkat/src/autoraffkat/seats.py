"""Kuka on kukin kasvo laajassa ja ryhmäkuvassa.

Pystyviennissä laaja ja ryhmäkuva kehystetään puhujan kasvoille, ja siihen
on tiedettävä mikä kasvo kuvassa on kenenkin. Paikka ei kerro sitä, eikä
kulma: sama kamera voi kuvata osassa 1 kahta ja osassa 2 yhtä ihmistä,
kun vieras on lähtenyt eikä kameraa siirretty. Siksi päätös tehdään
**tiedostoittain** ja vain niistä puhujista jotka tiedoston aikana
puhuvat.

Todiste on suu: puhujan suu on auki useammin kun hänen mikkinsä puhuu kuin
silloin kun se on hiljaa. Avainruutuja on sekunnissa yksi, joten
yksittäinen ruutu ei kerro mitään, mutta tunnin otoksessa ero on
tuhansien ruutujen keskiarvo. Jokaiselle kasvoryhmälle ja puhujalle
lasketaan ero, ja kasvot jaetaan puhujille niin että erojen summa on
suurin. ``margin`` on paras summa miinus toiseksi paras: pieni marginaali on
epävarma jako, ja käyttäjä voi antaa järjestyksen käsin (``order``).

Pelkkää numpyä, ei tiedostonlukua: ajetaan säätökierroksella kuten
``decide.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import permutations

import numpy as np

from .model import HOP
from .reactions import to_timeline

# Taustalla näkyvä kasvo (televisio, ohikulkija) on pieni. Alle puolet
# tiedoston kasvojen mediaanikorkeudesta ei ole istuja.
MIN_RELATIVE_SIZE = 0.5

# Näin monta ruutua kummaltakin puolelta (puhuu / ei puhu) ennen kuin ero
# on todiste. Alle sen keskiarvo on yksittäisten ruutujen sattumaa.
MIN_EVIDENCE = 5

KMEANS_ROUNDS = 25


@dataclass
class Seat:
    """Yhden puhujan paikka yhdessä tiedostossa."""

    speaker: int            # puhujan indeksi ``Grid.speakers``issa
    x: float                # kasvon keskipiste, lähteen leveydestä
    y: float                # kasvon keskipiste ylhäältä, lähteen korkeudesta
    h: float                # kasvon korkeus, lähteen korkeudesta
    rows: np.ndarray        # taulukon rivit (löydöt) jotka ovat hänen


@dataclass
class FileSeats:
    """Tiedoston istumajärjestys: puhujan indeksi -> paikka."""

    seats: dict[int, Seat] = field(default_factory=dict)
    margin: float = 0.0     # paras jako miinus toiseksi paras, suun aukkona
    manual: bool = False    # järjestys annettiin käsin

    def left_to_right(self) -> list[int]:
        return [s.speaker for s in sorted(self.seats.values(), key=lambda s: s.x)]


def _centres(table: dict) -> tuple[np.ndarray, np.ndarray]:
    x = table["x"] + table["w"] / 2
    y = 1.0 - (table["y"] + table["h"] / 2)
    return x, y


def _kmeans(values: np.ndarray, k: int) -> np.ndarray:
    """Yksiulotteinen k-means. Palauttaa jokaisen arvon ryhmän, vasemmalta."""
    centres = np.quantile(values, (np.arange(k) + 0.5) / k)
    labels = np.zeros(len(values), dtype=np.int64)
    for _ in range(KMEANS_ROUNDS):
        labels = np.argmin(np.abs(values[:, None] - centres[None, :]), axis=1)
        moved = np.array([values[labels == c].mean() if np.any(labels == c)
                          else centres[c] for c in range(k)])
        if np.allclose(moved, centres):
            break
        centres = moved
    order = np.argsort(centres)
    rank = np.empty(k, dtype=np.int64)
    rank[order] = np.arange(k)
    return rank[labels]


def seat_file(table: dict, item, grid, speakers: list[int],
              order: list[int] | None = None) -> FileSeats | None:
    """Tiedoston kasvot puhujille.

    ``speakers`` ovat ne puhujat jotka kuvassa voivat olla (laaja: kaikki,
    ryhmäkuva: sen puhujat). Niistä mukaan tulevat vain ne jotka puhuvat
    tämän tiedoston aikana. ``order`` on käsin annettu järjestys
    vasemmalta oikealle; se rajataan samoin ja ohittaa mittauksen, jos
    kasvoryhmiä on yhtä monta.
    """
    if table is None or "frame" not in table or not len(table["frame"]):
        return None
    heights = table["h"]
    big = heights >= MIN_RELATIVE_SIZE * float(np.median(heights))
    rows = np.flatnonzero(big)
    if not len(rows):
        return None

    frames = table["frame"][rows]
    stamps = to_timeline(item, np.asarray(table["times"], dtype=np.float64)[frames])
    cells = np.full(len(rows), -1, dtype=np.int64)
    ok = np.isfinite(stamps)
    cells[ok] = np.rint((stamps[ok] - grid.program_start) / HOP).astype(np.int64)
    cells[(cells < 0) | (cells >= grid.n)] = -1
    inside = cells[cells >= 0]
    if not len(inside):
        return None
    lo, hi = int(inside.min()), int(inside.max()) + 1
    present = [p for p in speakers if grid.speakers[p].on[lo:hi].any()]
    if not present:
        return None

    counts = np.bincount(frames)
    typical = int(round(float(np.percentile(counts[counts > 0], 75))))
    k = max(1, min(len(present), typical))

    x, _y = _centres(table)
    labels = _kmeans(x[rows], k)

    if order is not None:
        wanted = [p for p in order if p in present]
        if len(wanted) == k:
            return _seats(table, rows, labels, {c: wanted[c] for c in range(k)},
                          margin=0.0, manual=True)

    evidence = np.zeros((k, len(present)))
    mouth = table["mouth"][rows]
    for c in range(k):
        mine = (labels == c) & (cells >= 0)
        for j, p in enumerate(present):
            talking = grid.speakers[p].on[cells[mine]]
            if talking.sum() >= MIN_EVIDENCE and (~talking).sum() >= MIN_EVIDENCE:
                values = mouth[mine]
                evidence[c, j] = values[talking].mean() - values[~talking].mean()

    totals = []
    for pick in permutations(range(len(present)), k):
        totals.append((sum(evidence[c, j] for c, j in enumerate(pick)), pick))
    totals.sort(key=lambda item: item[0], reverse=True)
    best, pick = totals[0]
    margin = best - totals[1][0] if len(totals) > 1 else 0.0
    return _seats(table, rows, labels, {c: present[j] for c, j in enumerate(pick)},
                  margin=float(margin), manual=False)


def _seats(table, rows, labels, who: dict[int, int], margin: float,
           manual: bool) -> FileSeats:
    x, y = _centres(table)
    out = FileSeats(margin=margin, manual=manual)
    for c, speaker in who.items():
        mine = rows[labels == c]
        out.seats[speaker] = Seat(
            speaker=speaker,
            x=float(np.median(x[mine])),
            y=float(np.median(y[mine])),
            h=float(np.median(table["h"][mine])),
            rows=mine,
        )
    return out
