"""Leikkaus liikkeeseen: peräkkäisten avainruutujen keskimääräinen erotus.

Mittaus on tarkoituksella yksinkertainen: pienennettyjen harmaasävyruutujen
keskimääräinen absoluuttinen luminanssiero (0–255). Se nousee kun kuvassa
liikutaan — käsi, pään kääntö, pystyyn nouseminen — ja pysyy matalana
statiivisella kolmijalalla. Tarkkaa liiketunnistusta ei tarvita: päätöskerros
vain siirtää jo päätetyn leikkauksen lähimpään mitattuun liikehetkeen
lyhyen ulottuvan sisällä (``decide.MOTION_REACH``), ei valitse leikkauskohtia.

Mittaus tehdään **avainruuduista** kuten kasvomittauskin, mutta ilman
koneoppimista: yksi ffmpeg-suodatinajo tuottaa sekä aikaleimat että
erotukset, joten tämä toimii myös ilman Visionia. Erotus paritetaan
aikaleimaan järjestyksellä kuten ``measure.py``ssä — pituuksien eriytyminen
on virhe, ei varoitus.

Kynnys on vakio (``MOTION_MIN``), ei säädin: «kuinka paljon liike» on
kysymys johon käyttäjällä ei ole vastausta — se numero on tämän työkalun
tehtävä, ja sen rinnalla laugee mittaus eikä liukusäädin.
"""

from __future__ import annotations

import os
import re
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from speechmix.binaries import get_binary_path

from . import measure

MAX_PARALLEL = 4

# Liikkeen kynnys luminanssierona (0–255): statiivinen kolmijalkakuva
# pysyy parissa yksikössä (kohina, valon välähdys), käden tai pään liike
# sekunnin avainruutuvälillä nousee selvästi sen yli.
MOTION_MIN = 8.0

# Purkuleveys erotusta varten: pieni riittää, koska mitattava asia on
# koko kuvan liike, ei yksityiskohta — ja pieni kuva nopeuttaa suodatusta.
WIDTH = 96


def _motion_kind() -> object:
    """Välimuistiavaimen «tunnistin»: nimi ja versio kuten detect.Detector."""
    class _Kind:
        name = "motion"
        version = 1

    return _Kind()


def measure_motion(path: str, progress=None) -> dict:
    """Mittaa tiedoston liikkeen: jokaisen avainruudun erotus edelliseen.

    Palauttaa ``{"times": ..., "motion": ...}`` samanmuotoisena kuin
    ``measure.measure_file``: aikaleima ja mittaus pariutuvat indeksillä.
    Ensimmäisen avainruudun liike on nolla — siihen ei ole edellistä
    ruutua josta erottaa.
    """
    name = os.path.basename(path)
    measure._log(f"{name}: liikkeen mittaus alkaa")
    ffmpeg = get_binary_path("ffmpeg")
    # showinfo tulostaa jokaisen avainruudun aikaleiman, tblend laskee
    # erotuksen edelliseen ruutuun ja signalstats sen keskiarvon, metadata
    # tulostaa erotukset virran mukana. Yksi ajo tuottaa molemmat, ja
    # -skip_frame nokey jättää väliruudut purkamatta kuten
    # kasvomittauksessa: purku on tämän työn ainoa kallis osa.
    cmd = [
        ffmpeg, "-nostdin", "-v", "info",
        "-skip_frame", "nokey", "-i", path,
        "-vf", f"scale={WIDTH}:-2,showinfo,tblend=all_mode=difference,"
               "signalstats,"
               "metadata=mode=print:key=lavfi.signalstats.YAVG",
        "-an", "-f", "null", "-",
    ]
    proc = subprocess.Popen(
        cmd, stderr=subprocess.PIPE, text=True, stdin=subprocess.DEVNULL)
    times: list[float] = []
    diffs: list[float] = []
    tail: list[str] = []
    for line in proc.stderr or []:
        tail.append(line.strip())
        if len(tail) > 10:
            tail.pop(0)
        if "showinfo" in line and "pts_time" in line:
            m = re.search(r"pts_time:\s*([-\d.]+)", line)
            if m:
                try:
                    times.append(float(m.group(1)))
                except ValueError:
                    continue
        m = re.search(r"lavfi\.signalstats\.YAVG=\s*([-\d.]+)", line)
        if m:
            try:
                diffs.append(float(m.group(1)))
            except ValueError:
                continue
    proc.wait(timeout=measure.TIMEOUT)
    if proc.returncode != 0:
        last_line = tail[-1] if tail else ""
        raise measure.MeasureError(
            f"{name}: liikkeen purku epäonnistui"
            + (f" — {last_line}" if last_line else ""))

    # tblend ei tulosta ensimmäistä ruutua, joten erotuksia on yksi
    # vähemmän kuin aikaleimoja. Pariutus on järjestyspohjainen kuten
    # muuallakin, ja pituuksien eriytyminen tarkoittaa että jokin mittaus
    # olisi väärässä kohdassa aikajanaa — virhe, ei varoitus.
    if not times or len(times) != len(diffs) + 1:
        raise measure.MeasureError(
            f"{name}: {len(times)} avainruutua mutta {len(diffs)} erotusta")
    values = np.zeros(len(times), dtype=np.float32)
    values[1:] = np.asarray(diffs, dtype=np.float32)
    if progress is not None:
        progress(1.0)
    return {"times": np.asarray(times, dtype=np.float32), "motion": values}


def motion_table(path: str, progress=None) -> dict:
    """Liiketaulukko välimuistista, tai lasketaan ja talletetaan.

    Sama levyvälimuisti kuin kasvotaulukoilla: avain sisältää polun,
    koon, muokkausajan ja mittauksen nimen ja version.
    """
    return measure._cached(
        path, _motion_kind(), lambda: measure_motion(path, progress))


def tables(files: list[tuple[str, str]], progress=None) -> tuple[dict, dict]:
    """Mittaa liiketaulukot rinnakkain. ``files`` on (media-avain, polku).

    Puuttuva tiedosto ei kaada koko ajoa kuten ei kasvomittauksessakaan:
    media voi olla irrotetulla levyllä, ja se kerrotaan virheenä.
    """
    out: dict = {}
    errors: dict = {}
    todo = []
    for key, path in files:
        if not os.path.exists(path):
            errors[key] = f"{os.path.basename(path)}: mediaa ei löydy"
        else:
            todo.append((key, path))
    if not todo:
        return out, errors

    workers = max(1, min(MAX_PARALLEL, len(todo), os.cpu_count() or 1))
    lock = threading.Lock()
    shares = [0.0] * len(todo)

    def report(index: int, fraction: float) -> None:
        if progress is None:
            return
        with lock:
            shares[index] = fraction
            progress(sum(shares) / len(shares))

    def run(index: int):
        key, path = todo[index]
        try:
            table = motion_table(
                path,
                progress=(lambda f, i=index: report(i, f)) if progress else None)
            report(index, 1.0)
            return key, table, None
        except (measure.MeasureError, OSError, RuntimeError) as exc:
            return key, None, str(exc)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for key, table, error in pool.map(run, range(len(todo))):
            if error:
                errors[key] = error
            else:
                out[key] = table
    return out, errors


def marks(angle_items: dict, tables: dict, grid, program_start: float,
          threshold: float = MOTION_MIN):
    """(kulmien avaimet, (kulmia, n) totuustaulukko) liikehetkistä.

    Sama muoto kuin ``reactions.marks``: päätöskerros saa pelkän taulukon,
    ei tiedostonlukua eikä mittausrajapintaa. ``angle_items`` kuvaa kulman
    (raidan avaimen) sen media-alkioihin, ja ``tables`` on media-avaimittain
    mitatut liiketaulukot. Palauttaa ``None`` jos yhtään hetkeä ei ole —
    päätöskerros toimii silloin täsmälleen kuin ilman mittaustakin.
    """
    from ..model import HOP
    from ..reactions import to_timeline

    keys: list[str] = []
    rows: list[np.ndarray] = []
    any_hit = False
    for key, items in angle_items.items():
        row = np.zeros(grid.n, dtype=bool)
        for item in items:
            table = tables.get(item.key)
            if table is None:
                continue
            stamps = to_timeline(
                item, np.asarray(table["times"], dtype=np.float64))
            values = np.asarray(table["motion"], dtype=np.float64)
            hits = np.isfinite(stamps) & (values >= threshold)
            for cell in ((stamps[hits] - program_start) / HOP).astype(int):
                if 0 <= cell < grid.n:
                    row[cell] = True
                    any_hit = True
        keys.append(key)
        rows.append(row)
    if not any_hit:
        return None
    return keys, np.asarray(rows, dtype=bool)
