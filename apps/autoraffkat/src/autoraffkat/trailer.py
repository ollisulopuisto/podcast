"""Trailerin pilkkominen ja kohteen paikka kehystystä varten.

Kaksi mittausta yhdestä videosta, kumpikin levyvälimuistissa kuten muutkin
mittaukset:

* **kohtaukset**: ffmpegin kohtauspisteytys jokaiselle ruudulle, joka ylittää
  lattian. Kynnys on vasta tässä moduulissa, joten sen muuttaminen ei vaadi
  uutta ajoa.
* **kohde**: spektrijäännös-saliency harmaasävyruuduista kahden ruudun
  sekuntinopeudella. Se on puhdasta numpyä eikä tarvitse Visionia, joten
  sama tulos syntyy missä tahansa. Kasvoja ei etsitä: trailerissa kohde on
  harvoin kasvot, ja kehys on joka tapauksessa ylikirjoitettavissa käsin.

Tuloksena kullekin palalle on yksi luku: kohteen vaakasuuntainen paikka
(0–1 lähteen leveydestä). Ikkuna lasketaan siitä ``window``illa kullekin
kaistalle (puolikas tai koko ruutu).
"""

from __future__ import annotations

import os
import re
import subprocess
from itertools import pairwise

import numpy as np

from speechmix.binaries import get_binary_path

from .probe import info
from .video import measure

# Lattia jonka alle ei kirjata: kynnys valitaan vasta ``cut_points``issa.
SCENE_FLOOR = 0.10
# Kohtauksen vaihdon kynnys. Trailerin kovat leikkaukset ovat 0,4–1,0,
# pehmeä häivytys jää tämän alle eikä ole kohtaus.
SCENE_DEFAULT = 0.30
# Lyhin pala sekunteina: trailerin nopea leikkaus on 1–3 s, tätä lyhyempi
# on välähdys eikä siihen kehystetä mitään.
MIN_PIECE = 1.0

SAMPLE_FPS = 2
SAL_W = 128
# Yläraja näytteille (tunti): purku ei saa kasvattaa muistia rajatta pitkällä videolla.
MAX_SAMPLES = 7200

TIMEOUT = 1800


class TrailerError(Exception):
    """Mittaus ei onnistunut."""


class _Kind:
    def __init__(self, name: str, version: int):
        self.name = name
        self.version = version


# ------------------------------------------------------------------ pilkonta


def scene_table(path: str) -> dict:
    """``{"times", "score"}`` kaikista ruuduista joiden kohtauspiste ≥ lattia."""
    return measure._cached(path, _Kind("scenes", 1), lambda: _measure_scenes(path))


def _measure_scenes(path: str) -> dict:
    ffmpeg = get_binary_path("ffmpeg")
    cmd = [
        ffmpeg, "-nostdin", "-v", "info", "-i", path,
        "-vf", f"select='gte(scene,{SCENE_FLOOR})',"
               "metadata=mode=print:key=lavfi.scene_score",
        "-an", "-f", "null", "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          stdin=subprocess.DEVNULL, timeout=TIMEOUT)
    if proc.returncode != 0:
        raise TrailerError(f"{os.path.basename(path)}: kohtausmittaus epäonnistui")
    times: list[float] = []
    scores: list[float] = []
    for line in proc.stderr.splitlines():
        m = re.search(r"pts_time:\s*([-\d.]+)", line)
        if m and "Parsed_metadata" in line:
            times.append(float(m.group(1)))
        m = re.search(r"lavfi\.scene_score=\s*([-\d.]+)", line)
        if m:
            scores.append(float(m.group(1)))
    if len(times) != len(scores):
        raise TrailerError(
            f"{os.path.basename(path)}: {len(times)} aikaleimaa, {len(scores)} pistettä")
    return {"times": np.asarray(times, dtype=np.float32),
            "score": np.asarray(scores, dtype=np.float32)}


def cut_points(table: dict, threshold: float = SCENE_DEFAULT,
               min_len: float = MIN_PIECE, duration: float = 0.0) -> list[float]:
    """Leikkauskohdat sekunteina: kynnyksen ylittävät, vähintään ``min_len`` välein.

    Kahdesta liian lähekkäisestä jää vahvempi. Loppuun ei jää alle ``min_len``
    mittaista palaa.
    """
    times = np.asarray(table["times"], dtype=np.float64)
    score = np.asarray(table["score"], dtype=np.float64)
    keep: list[tuple[float, float]] = []
    for t, s in sorted(zip(times.tolist(), score.tolist(), strict=True)):
        if s < threshold or t < min_len:
            continue
        if keep and t - keep[-1][0] < min_len:
            if s > keep[-1][1]:
                keep[-1] = (t, s)
            continue
        keep.append((t, s))
    cuts = [t for t, _ in keep]
    if duration > 0:
        cuts = [t for t in cuts if duration - t >= min_len]
    return cuts


def pieces(cuts: list[float], duration: float) -> list[tuple[float, float]]:
    """Palat ``(alku, loppu)`` ilman aukkoja koko pituudelta."""
    edges = [0.0, *[c for c in cuts if 0.0 < c < duration], float(duration)]
    return [(a, b) for a, b in pairwise(edges) if b > a]


def fixed_pieces(duration: float, every: float) -> list[tuple[float, float]]:
    """Tasavälinen pilkonta. Loppuun jäävä alle puolen välin pätkä liitetään edelliseen."""
    every = max(0.5, float(every))
    cuts: list[float] = []
    t = every
    while duration - t >= every / 2:
        cuts.append(t)
        t += every
    return pieces(cuts, duration)


# -------------------------------------------------------------------- kohde


def subject_of(gray: np.ndarray) -> tuple[float, float]:
    """Kohteen paikka ``(x, y)`` suhteena kuvaan, spektrijäännös-saliencystä.

    Hou & Zhang 2007: kuvan log-amplitudispektristä vähennetään sen
    paikallinen keskiarvo, jäännös on se mikä erottuu. Tulos pehmennetään,
    ja kohteen paikka on pinta-alapainotettu keskipiste. Heikko keskipainotus
    estää tarttumisen reunan kohinaan; täysin tasainen kuva antaa keskustan.
    """
    img = np.asarray(gray, dtype=np.float64)
    if img.ndim != 2 or img.size == 0:
        return 0.5, 0.5
    spec = np.fft.fft2(img)
    log_amp = np.log(np.abs(spec) + 1e-6)
    phase = np.angle(spec)
    k = 3
    pad = np.pad(log_amp, k, mode="edge")
    box = np.zeros_like(log_amp)
    for dy in range(-k, k + 1):
        for dx in range(-k, k + 1):
            box += pad[k + dy:k + dy + log_amp.shape[0],
                       k + dx:k + dx + log_amp.shape[1]]
    box /= (2 * k + 1) ** 2
    sal = np.abs(np.fft.ifft2(np.exp(log_amp - box + 1j * phase))) ** 2
    sal = _blur(sal)
    h, w = sal.shape
    ys, xs = (np.arange(h) + 0.5) / h, (np.arange(w) + 0.5) / w
    prior = np.exp(-(((xs[None, :] - 0.5) / 0.9) ** 2
                     + ((ys[:, None] - 0.5) / 0.9) ** 2))
    sal = sal * prior
    sal = np.clip(sal - sal.mean(), 0.0, None)
    total = sal.sum()
    if total <= 1e-12:
        return 0.5, 0.5
    return float((sal.sum(axis=0) * xs).sum() / total), \
        float((sal.sum(axis=1) * ys).sum() / total)


def _blur(img: np.ndarray, r: int = 3) -> np.ndarray:
    out = np.pad(img, r, mode="edge")
    acc = np.zeros_like(img)
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            acc += out[r + dy:r + dy + img.shape[0], r + dx:r + dx + img.shape[1]]
    return acc / (2 * r + 1) ** 2


def saliency_table(path: str) -> dict:
    """``{"times", "x", "y"}``: kohteen paikka ruudusta kahden ruudun sekuntinopeudella."""
    return measure._cached(path, _Kind("subject", 1), lambda: _measure_subject(path))


def _measure_subject(path: str) -> dict:
    meta = (info(path) or {}).get("video") or {}
    width, height = int(meta.get("width") or 0), int(meta.get("height") or 0)
    if not width or not height:
        raise TrailerError(f"{os.path.basename(path)}: ei kuvaa")
    sh = max(2, int(round(SAL_W * height / width / 2)) * 2)
    ffmpeg = get_binary_path("ffmpeg")
    cmd = [
        ffmpeg, "-nostdin", "-v", "error", "-i", path,
        "-vf", f"fps={SAMPLE_FPS},scale={SAL_W}:{sh},format=gray",
        "-an", "-frames:v", str(MAX_SAMPLES),
        "-f", "rawvideo", "-pix_fmt", "gray", "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, stdin=subprocess.DEVNULL,
                          timeout=TIMEOUT)
    if proc.returncode != 0:
        raise TrailerError(f"{os.path.basename(path)}: ruutujen purku epäonnistui")
    frame = SAL_W * sh
    count = len(proc.stdout) // frame
    data = np.frombuffer(proc.stdout[:count * frame], dtype=np.uint8)
    xs = np.zeros(count, dtype=np.float32)
    ys = np.zeros(count, dtype=np.float32)
    for i in range(count):
        x, y = subject_of(data[i * frame:(i + 1) * frame].reshape(sh, SAL_W))
        xs[i], ys[i] = x, y
    return {"times": (np.arange(count) / SAMPLE_FPS).astype(np.float32),
            "x": xs, "y": ys}


def piece_x(table: dict, start: float, end: float) -> float:
    """Palan kohteen vaakapaikka: näytteiden mediaani, tai 0,5 kun näytteitä ei ole.

    Ei arvausta: mittaamaton pala jää keskelle, kuten kasvokehystyksessäkin.
    """
    times = np.asarray(table["times"], dtype=np.float64)
    inside = (times >= start) & (times < end)
    if not inside.any():
        return 0.5
    return float(np.median(np.asarray(table["x"], dtype=np.float64)[inside]))


# ------------------------------------------------------------------- ikkuna


def window(src_w: int, src_h: int, frame_w: int, frame_h: int,
           x: float) -> tuple[float, float, float, float]:
    """Lähteen ikkuna ``(x, y, leveys, korkeus)`` pikseleinä kaistan kehykselle.

    Ikkuna on kehyksen kuvasuhde ja täyttää lähteen korkeuden; kun lähde on
    sitä kapeampi, täyttää leveyden. Keskipiste on kohteessa ``x`` ja ikkuna
    pysyy lähteen sisällä. Sama täyttö kuin ``layout.window_of``issa.
    """
    fill = max(frame_w / src_w, frame_h / src_h)
    ww, wh = frame_w / fill, frame_h / fill
    wx = min(max(x * src_w - ww / 2, 0.0), max(0.0, src_w - ww))
    wy = max(0.0, (src_h - wh) / 2)
    return wx, wy, ww, wh
