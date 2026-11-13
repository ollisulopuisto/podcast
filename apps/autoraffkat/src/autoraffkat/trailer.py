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

import functools
import os
import re
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from itertools import pairwise

import numpy as np

from speechmix.binaries import get_binary_path

from .i18n import t
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


@dataclass(frozen=True)
class TrailerSource:
    """Trailerin tiedot kirjoitusta varten: yksi kuvatiedosto."""

    path: str
    name: str
    width: int
    height: int
    frame_duration: Fraction
    duration: Fraction
    has_audio: bool = False
    audio_channels: int = 2
    audio_rate: int = 48000


#: Tasataajuuksien NTSC-versiot: ffprobe-liukuluku (29,97) ei ole 30000/1001.
_NTSC = (Fraction(24000, 1001), Fraction(30000, 1001), Fraction(48000, 1001),
         Fraction(60000, 1001), Fraction(120000, 1001))


def _frame_duration(fps: float) -> Fraction:
    """Ruudun kesto tarkkana murtolukuna; NTSC-taajuudet napataan täsmälleen."""
    for rate in _NTSC:
        if abs(fps - float(rate)) < 0.001:
            return 1 / rate
    return Fraction(1) / Fraction(str(fps)).limit_denominator(1000)


def probe_source(path: str) -> TrailerSource:
    """Lukee trailerin ffprobesta. Kuvaton tai pituudeton tiedosto on virhe."""
    data = info(path) or {}
    video = data.get("video") or {}
    audio = data.get("audio") or {}
    duration = data.get("duration")
    fps = video.get("fps")
    if not video or not duration or not fps or fps <= 0:
        raise TrailerError(t("trailer.err.no_picture", name=os.path.basename(path)))
    return TrailerSource(
        path=os.path.abspath(path),
        name=os.path.splitext(os.path.basename(path))[0],
        width=int(video.get("width") or 0),
        height=int(video.get("height") or 0),
        frame_duration=_frame_duration(float(fps)),
        duration=Fraction(str(duration)).limit_denominator(1_000_000),
        has_audio=bool(audio),
        audio_channels=int(audio.get("channels") or 2),
        audio_rate=int(audio.get("rate") or 48000),
    )


class _Kind:
    def __init__(self, name: str, version: int, columns: tuple[str, ...] = ()):
        self.name = name
        self.version = version
        self.columns = columns
        # Polkuindeksin rivi mittauslajia kohti: muuten kohtaus- ja kohdetaulu
        # korvaavat toisensa ja irrotetulta levyltä latautuu väärä taulu.
        self.tag = f"{name}{version}"


# ------------------------------------------------------------------ pilkonta


def scene_table(path: str) -> dict:
    """``{"times", "score"}`` kaikista ruuduista joiden kohtauspiste ≥ lattia."""
    return measure._cached(path, _Kind("scenes", 1, ("times", "score")), lambda: _measure_scenes(path))


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
        raise TrailerError(t("trailer.err.scenes", name=os.path.basename(path)))
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
        raise TrailerError(t("trailer.err.scene_pairs", name=os.path.basename(path),
                            times=len(times), scores=len(scores)))
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
    for at, s in sorted(zip(times.tolist(), score.tolist(), strict=True)):
        if s < threshold or at < min_len:
            continue
        if duration > 0 and duration - at < min_len:
            continue   # liian lähellä loppua: ei saa syrjäyttää käyttökelpoista
        if keep and at - keep[-1][0] < min_len:
            if s > keep[-1][1]:
                keep[-1] = (at, s)
            continue
        keep.append((at, s))
    return [at for at, _ in keep]


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
    return measure._cached(path, _Kind("subject", 2, ("times", "x", "y", "stamped")), lambda: _measure_subject(path))


@functools.lru_cache(maxsize=4)
def _passthrough(ffmpeg: str) -> tuple[str, str]:
    """Ei ruutujen kahdennusta ulostulossa: aikaleimoja ja ruutuja yksi yhteen.

    Uudessa ffmpegissä ``-fps_mode``, vanhassa ``-vsync``.
    """
    try:
        helptext = subprocess.run([ffmpeg, "-hide_banner", "-h", "full"],
                                  capture_output=True, text=True, timeout=60,
                                  stdin=subprocess.DEVNULL).stdout
    except (OSError, subprocess.SubprocessError):
        helptext = ""
    return ("-fps_mode", "passthrough") if "-fps_mode" in helptext else ("-vsync", "0")


def _measure_subject(path: str) -> dict:
    meta = (info(path) or {}).get("video") or {}
    width, height = int(meta.get("width") or 0), int(meta.get("height") or 0)
    if not width or not height:
        raise TrailerError(t("trailer.err.no_picture", name=os.path.basename(path)))
    sh = max(2, int(round(SAL_W * height / width / 2)) * 2)
    ffmpeg = get_binary_path("ffmpeg")
    cmd = [
        ffmpeg, "-nostdin", "-v", "info", "-i", path,
        "-vf", f"fps={SAMPLE_FPS},showinfo,scale={SAL_W}:{sh},format=gray",
        "-an", *_passthrough(ffmpeg), "-frames:v", str(MAX_SAMPLES),
        "-f", "rawvideo", "-pix_fmt", "gray", "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, stdin=subprocess.DEVNULL,
                          timeout=TIMEOUT)
    if proc.returncode != 0:
        raise TrailerError(t("trailer.err.decode", name=os.path.basename(path)))
    # Ruutujen todelliset ajat: video voi alkaa myöhemmin kuin säiliö.
    stamps = [float(m.group(1)) for line in proc.stderr.decode("utf-8", "replace").splitlines()
              if "Parsed_showinfo" in line
              for m in [re.search(r"pts_time:\s*([-\d.]+)", line)] if m]
    frame = SAL_W * sh
    count = len(proc.stdout) // frame
    if len(stamps) < count:
        raise TrailerError(t("trailer.err.stamps", name=os.path.basename(path),
                                frames=count, stamps=len(stamps)))
    data = np.frombuffer(proc.stdout[:count * frame], dtype=np.uint8)
    xs = np.zeros(count, dtype=np.float32)
    ys = np.zeros(count, dtype=np.float32)
    for i in range(count):
        x, y = subject_of(data[i * frame:(i + 1) * frame].reshape(sh, SAL_W))
        xs[i], ys[i] = x, y
    return {"times": np.asarray(stamps[:count], dtype=np.float32),
            "x": xs, "y": ys,
            # v2: ajat ovat ruutujen omia (v1:n taulussa tätä saraketta ei ole)
            "stamped": np.ones(1, dtype=np.uint8)}


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


def plan(path: str, threshold: float = SCENE_DEFAULT, min_len: float = MIN_PIECE,
         every: float | None = None) -> tuple[TrailerSource, list[tuple[float, float]], list[float]]:
    """Trailer → (tiedot, palat, kohteen paikka palaa kohden).

    ``every`` valitsee tasavälisen pilkonnan kohtausten sijaan. Kohde mitataan
    aina: kehys tarvitaan kummassakin tilassa.
    """
    src = probe_source(path)
    length = float(src.duration)
    if every:
        cuts = fixed_pieces(length, every)
    else:
        cuts = pieces(cut_points(scene_table(path), threshold, min_len, length), length)
    table = saliency_table(path)
    return src, cuts, [piece_x(table, a, b) for a, b in cuts]
