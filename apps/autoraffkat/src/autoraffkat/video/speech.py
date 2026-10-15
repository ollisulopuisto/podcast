"""Puhe kuvasta: lähikuvan huulten liikkeestä verhokäyrä, kun mikkiä ei ole.

Sama työnjako kuin muualla: tässä on hidas osa (ruutujen purku ja
tunnistin) ja sen tulos on **verhokäyrä samassa muodossa kuin mikin**
(``speechmix.rms.envelope_for``: dB, yksi arvo ``HOP``in välein tiedoston
ajassa), joten ``analysis.build_grid`` ja ``grid.lane`` päättävät siitä
täsmälleen kuten mikistä. Kuvasta ei tehdä erillistä päätöstä.

**Mitattu.** pp 56, kaksi mikkiä ja kolme kameraa, neljä kahden minuutin
ikkunaa: lähikameran huulten liike erotti oman puheen mikin puheesta
AUC 0,82 ja 0,91 (laajakuva 0,73), ja kun miksauksen ääni kertoi *milloin*
joku puhuu, kahden lähikuvan vertailu *kuka* puhuu osui 93 %:iin
ruuduista (pätkät yli 1 s: 127/134). pp 55: 0,84 ja 0,87. pp 57 (vain
miksaus): neljä tunnettua kohtaa neljä oikein.

Huulten liike, ei suun aukko: aukko vaihtelee kasvoittain ja kameroittain
(0,11–0,64 samassa jaksossa), mutta sen *muutos* on puhetta kaikilla.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from speechmix import binaries
from speechmix.binaries import get_binary_path
from speechmix.rms import FLOOR_DB

from ..model import HOP

#: Kuvia sekunnissa. Avainruudut (1/s) eivät riitä: puhe on huulissa liikettä
#: kymmenesosasekunneissa, ja yksi kuva sekunnissa jättää siitä arvauksen.
#: Hinta mitattu: 30 s kuvaa 6,5 s (purku 3,4 + tunnistin 3,1), eli 4,6x
#: reaaliaika kameraa kohden.
FPS = 10
WIDTH = 960
#: Huulten liikkeen liukuva keskiarvo, kuvina (0,5 s).
MOTION_FRAMES = 5
#: Liikkeen suhteutus: raidan oma 90. persentiili. Kasvot ja kamerat ovat
#: eri etäisyydellä, joten absoluuttinen liike ei vertaudu kahden puhujan
#: välillä; oma puhetaso on se mikä vertautuu.
NORMALISE_PERCENTILE = 90.0
#: Kynnys pohjan päällä visuaaliselle kaistalle, dB. Mikin oletus on 12
#: (``TrackConfig.sensitivity_db``), mutta huulten liikkeen taso vaihtelee
#: vähemmän kuin äänen: pp 56:n kahdella ikkunalla ja kahdella lähikameralla
#: F1 oli 6/9/12/15 dB:llä 0,77-0,86 / 0,77-0,90 / 0,63-0,89 / 0,28-0,84 --
#: 9 on ainoa jolla jokainen neljästä pysyi yli 0,77:n.
VISUAL_MARGIN_DB = 9.0
#: Verhokäyrän avain ``Analysis.envelopes``issa: median avain + tämä. Mikin
#: ja kuvan käyrä ovat eri mittauksia samasta kulmasta.
SUFFIX = "#visual"
#: Purku tehdään enintään näin pitkinä paloina: tunti on 36 000 JPEGiä, ja
#: yhtenä palana ne kaikki ovat levyllä yhtä aikaa (n. 4 GB kameraa kohden)
#: eikä edistymistä näy ennen loppua.
CHUNK_SECONDS = 300.0
#: Tunnistimen säikeet: puolet koneen ytimistä, vähintään kaksi (sama sääntö
#: kuin ``analysis.ENVELOPE_WORKERS``: kone jaksaa vielä purun ja
#: käyttöliittymän). Mitattu 8-ytimisellä koneella 60 s:n kuvasta (600
#: kuvaa): 1 säie 63 kuvaa/s, 2 säiettä 162, 4 säiettä 201, 8 säiettä 197 --
#: käyrä tasaantuu neljään, joten lisäsäikeet eivät hyödytä mutta eivät
#: myöskään haittaa. Purku on silti pullonkaula (5,9x reaaliaika,
#: laitteistopurkain), ja kaksi kameraa rinnakkain ei ollut nopeampi kuin yksi.
CACHE_VERSION = 1
TIMEOUT = 3600.0

#: ``(tiedosto-alku s, kesto s)``: purettava väli tiedoston ajassa.
Range = tuple[float, float]


def motion(mouth: np.ndarray) -> np.ndarray:
    """Suun aukon muutos kuvien välillä, liukuvasti. Puuttuva kasvo ei liiku."""
    mouth = np.asarray(mouth, dtype=np.float64)
    if mouth.size == 0:
        return mouth
    change = np.abs(np.diff(mouth, prepend=np.nan))
    change = np.where(np.isfinite(change), change, 0.0)
    pad = MOTION_FRAMES // 2
    padded = np.pad(change, (pad, MOTION_FRAMES - 1 - pad), mode="edge")
    return np.convolve(padded, np.ones(MOTION_FRAMES) / MOTION_FRAMES, mode="valid")


def levels_db(parts: list[np.ndarray]) -> list[np.ndarray]:
    """Liike desibeleiksi, suhteutettuna kaikkien osien yhteiseen p90:een.

    Yksi asteikko koko tiedostolle: osat ovat saman kasvon eri kohtia, eikä
    jokainen saa normalisoitua omaan huippuunsa (hiljainen osa näyttäisi
    silloin yhtä äänekkäältä kuin vilkas).
    """
    joined = np.concatenate([p for p in parts if p.size]) if parts else np.zeros(0)
    scale = float(np.percentile(joined, NORMALISE_PERCENTILE)) if joined.size else 0.0
    scale = max(scale, 1e-6)
    return [20.0 * np.log10(p / scale + 1e-3) for p in parts]


def to_envelope(
    ranges: list[Range], levels: list[np.ndarray], fps: float = FPS
) -> np.ndarray:
    """Tasot verhokäyräksi tiedoston ajassa (``HOP``in välein, ``FLOOR_DB`` mittaamattomissa)."""
    end = max((s + d for s, d in ranges), default=0.0)
    env = np.full(int(np.ceil(end / HOP)) + 1, FLOOR_DB, dtype=np.float32)
    for (start, dur), lv in zip(ranges, levels, strict=True):
        if lv.size == 0:
            continue
        i0 = int(np.ceil(start / HOP))
        i1 = min(env.size, int(np.floor((start + dur) / HOP)) + 1)
        t = np.arange(i0, i1) * HOP
        frame_t = start + np.arange(lv.size) / fps
        env[i0:i1] = np.interp(t, frame_t, lv).astype(np.float32)
    return env


def _extract(path: str, start: float, dur: float, into: Path) -> list[Path]:
    """``FPS`` kuvaa sekunnissa väliltä JPEGeiksi."""
    cmd = [
        get_binary_path("ffmpeg"), "-nostdin", "-v", "error",
        *binaries.hw_decode_args(),
        "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", path,
        "-vf", f"fps={FPS},scale={WIDTH}:-2", "-q:v", "3",
        str(into / "%06d.jpg"),
    ]
    done = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT,
                          stdin=subprocess.DEVNULL)
    frames = sorted(into.glob("*.jpg"))
    if done.returncode != 0 or not frames:
        raise RuntimeError(f"{os.path.basename(path)}: purku epäonnistui — "
                           f"{(done.stderr or '').strip().splitlines()[-1:]}")
    return frames


def vision_workers() -> int:
    """Tunnistimen säikeiden määrä tällä koneella."""
    return max(2, (os.cpu_count() or 4) // 2)


def _detectors(detector, n: int) -> list:
    """Yksi tunnistin per säie. ``clone()`` jos tunnistimella on sellainen,
    muuten sama olio (tunnistimen on silloin kestettävä rinnakkaiskutsut)."""
    clone = getattr(detector, "clone", None)
    return [clone() for _ in range(n)] if clone else [detector] * n


def mouth_series(
    path: str, start: float, dur: float, detector, extract: Callable = _extract,
    workers: int | None = None,
) -> np.ndarray:
    """Suurimman kasvon suun aukko jokaisessa kuvassa (``nan`` jos kasvoa ei ole).

    Kuvat mitataan ``workers`` säikeellä ja palautetaan kuvajärjestyksessä:
    kuva ja aikaleima pariutuvat indeksillä, joten järjestys on sopimus.
    """
    def measure(det, frame) -> float:
        faces = det.measure_all(str(frame))
        return max(faces, key=lambda f: f["w"] * f["h"])["mouth"] if faces else np.nan

    with tempfile.TemporaryDirectory() as tmp:
        frames = extract(path, start, dur, Path(tmp))
        out = np.full(len(frames), np.nan)
        n = max(1, min(workers or vision_workers(), len(frames)))
        detectors = _detectors(detector, n)

        def work(k: int) -> list[tuple[int, float]]:
            return [(i, measure(detectors[k], frames[i])) for i in range(k, len(frames), n)]

        with ThreadPoolExecutor(n) as pool:
            for part in pool.map(work, range(n)):
                for i, value in part:
                    out[i] = value
    return out


def cache_key(path: str, ranges: list[Range], detector) -> str:
    st = os.stat(path)
    raw = "|".join([
        path, str(st.st_size), str(st.st_mtime_ns), repr(ranges), str(FPS),
        str(WIDTH), detector.name, str(detector.version), str(CACHE_VERSION),
    ])
    return hashlib.sha1(raw.encode()).hexdigest()


def cache_dir() -> Path:
    root = Path.home() / "Library" / "Caches" / "autoraffkat" / "speech"
    root.mkdir(parents=True, exist_ok=True)
    return root


def envelope(
    path: str,
    ranges: list[Range],
    detector,
    progress: Callable[[float], None] | None = None,
    extract: Callable = _extract,
    cache: Path | None = None,
) -> np.ndarray:
    """Tiedoston puheverhokäyrä huulten liikkeestä. Hidas: välimuistitettu levylle."""
    ranges = [(round(s, 3), round(d, 3)) for s, d in ranges if d > 0.5]
    if not ranges:
        return np.full(1, FLOOR_DB, dtype=np.float32)
    folder = cache or cache_dir()
    target = folder / f"{cache_key(path, ranges, detector)}.npy"
    if target.is_file():
        return np.load(target)
    total = sum(d for _, d in ranges)
    done = 0.0
    parts = []
    for start, dur in ranges:
        pieces = []
        at = 0.0
        while at < dur - 1e-6:
            step = min(CHUNK_SECONDS, dur - at)
            pieces.append(mouth_series(path, start + at, step, detector, extract))
            at += step
            done += step
            if progress is not None:
                progress(min(1.0, done / total))
        # Liike lasketaan koko alueesta, ei palasta: palojen rajalla ei ole taukoa.
        parts.append(motion(np.concatenate(pieces)))
    env = to_envelope(ranges, levels_db(parts))
    np.save(target, env)
    return env
