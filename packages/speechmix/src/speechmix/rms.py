"""RMS-verhokäyrä tiedostosta: hidas kerros.

Nimi on ``rms`` eikä ``envelope``, koska ``envelopes.py`` on jo olemassa ja
tarkoittaa aivan muuta — vaimennusta päätöksinä. Yhden kirjaimen päässä
toisistaan olevat moduulinimet, joilla ei ole mitään tekemistä keskenään,
ovat ansa jonka lukija astuu kerran ja korjaa väärin.

ffmpeg purkaa raidan monoksi, RMS lasketaan ``HOP``in välein desibeleinä.
Tämä ajetaan kerran tiedostoa kohden ja säilötään levylle, koska se maksaa
sekunteja minuuttia kohden. Päätöskerros lukee vain valmiin taulukon.

Verhokäyrä indeksoidaan **tiedoston alusta**, ei aikajanasta, jotta sama
säilö kelpaa vaikka klippi siirtyisi aikajanalla. Sijoitus aikajanalle on
isännän asia; ks. paketin README ja sen ``Track``.

Välimuistin **paikka** on isännän, ei tämän: kolme sovellusta säilövät
omiin hakemistoihinsa, ja kirjasto joka valitsee itse polun käyttäjän
kotihakemistosta kirjoittaa kutsumatta. ``cache_dir=None`` — oletus —
tarkoittaa «laske, älä säilö».
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

import numpy as np

from . import binaries
from .dsp import FLOOR_DB
from .errors import EnvelopeError
from .masks import HOP
from .messages import t

# 8 kHz riittää puheen energialle ja maksaa neljäsosan purkuajasta:
# RMS 20 ms:n ikkunassa ei erota enempää, ja mitattuna sama käyrä ±0,2 dB
# 48 kHz:n purkuun verrattuna.
SAMPLE_RATE = 8000

# Nostetaan kun laskenta muuttuu: vanhat säilötyt käyrät ovat silloin eri
# laskennan tulos, ja niiden käyttö olisi juuri se hiljainen väärä tulos.
CACHE_VERSION = 2



def require_ffmpeg() -> None:
    """Varmistaa työkalut ennen purkua, jotta virhe on luettava eikä OSError."""
    try:
        binaries.require_ffmpeg()
    except FileNotFoundError as err:
        raise EnvelopeError(str(err)) from err


def cache_key(path: str) -> str:
    """Säilöavain: polku, koko, muokkausaika ja laskennan parametrit.

    Koko ja muokkausaika mukana, jotta korvattu tiedosto ei osu vanhaan
    käyrään; ``CACHE_VERSION``, jotta laskennan muutos mitätöi vanhat.
    """
    st = os.stat(path)
    raw = (
        f"{os.path.abspath(path)}|{st.st_size}|{st.st_mtime_ns}"
        f"|{SAMPLE_RATE}|{HOP}|{CACHE_VERSION}"
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def probe_audio(path: str) -> bool:
    """Onko tiedostossa ääniraitaa."""
    try:
        ffprobe_bin = binaries.get_binary_path("ffprobe")
        out = subprocess.run(
            [
                ffprobe_bin,
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=index",
                "-of",
                "csv=p=0",
                path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return out.returncode == 0 and bool(out.stdout.strip())


def _decode_rms(path: str, progress=None) -> np.ndarray:
    """Purkaa äänen virtana ja palauttaa RMS-desibelit HOP-välein."""
    win = max(1, int(round(SAMPLE_RATE * HOP)))
    chunk_frames = 4096  # 4096 * 20 ms ≈ 82 s kerrallaan
    chunk_bytes = win * chunk_frames * 4

    ffmpeg_bin = binaries.get_binary_path("ffmpeg")
    cmd = [
        ffmpeg_bin,
        "-v",
        "error",
        "-nostdin",
        "-i",
        path,
        "-map",
        "0:a:0",
        "-ac",
        "1",
        "-ar",
        str(SAMPLE_RATE),
        "-f",
        "f32le",
        "-",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    blocks: list[np.ndarray] = []
    leftover = b""
    frames_done = 0
    try:
        while True:
            data = proc.stdout.read(chunk_bytes)
            if not data:
                break
            data = leftover + data
            usable = (len(data) // (win * 4)) * (win * 4)
            leftover = data[usable:]
            if usable == 0:
                continue
            samples = np.frombuffer(data[:usable], dtype="<f4")
            frames = samples.reshape(-1, win)
            mean_sq = np.mean(np.square(frames, dtype=np.float64), axis=1)
            blocks.append(mean_sq.astype(np.float32))
            frames_done += frames.shape[0]
            if progress is not None:
                progress(frames_done * HOP)
    finally:
        if proc.stdout:
            proc.stdout.close()
        stderr = proc.stderr.read() if proc.stderr else b""
        if proc.stderr:
            proc.stderr.close()
        proc.wait()

    if proc.returncode not in (0, None):
        raise EnvelopeError(
            t(
                "envelope.decode_failed",
                name=os.path.basename(path),
                error=stderr.decode(errors="replace").strip(),
            )
        )
    if not blocks:
        return np.zeros(0, dtype=np.float32)

    mean_sq = np.concatenate(blocks)
    db = 10.0 * np.log10(np.maximum(mean_sq, 1e-12))
    return np.maximum(db, FLOOR_DB).astype(np.float32)


def envelope_for(
    path: str, progress=None, cache_dir: str | Path | None = None
) -> np.ndarray:
    """RMS-verhokäyrä desibeleinä, yksi arvo per HOP tiedoston alusta.

    ``cache_dir`` on isännän hakemisto, tai ``None`` jos säilöä ei haluta.
    Se on turvallista tyhjentää milloin tahansa: hinta on yksi purku.
    """
    if not path or not os.path.exists(path):
        raise EnvelopeError(t("envelope.source_missing", path=path or "?"))
    require_ffmpeg()

    cache_path = Path(cache_dir) / f"{cache_key(path)}.npy" if cache_dir else None
    if cache_path is not None and cache_path.exists():
        try:
            return np.load(cache_path)
        except (OSError, ValueError):
            cache_path.unlink(missing_ok=True)

    db = _decode_rms(path, progress)
    if cache_path is not None:
        _store(cache_path, db)
    return db


def _store(cache_path: Path, db: np.ndarray) -> None:
    """Kirjoittaa käyrän atomisesti. Epäonnistuminen ei ole virhe, vain hidas."""
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache_path.with_suffix(".npy.tmp")
    try:
        # Kahva, ei polkua. ``np.save`` lisää polkuun ``.npy``:n jos se ei jo
        # pääty siihen, joten polulla annettuna tämä kirjoitti tiedostoon
        # ``<avain>.npy.tmp.npy`` ja nimesi sitten uudelleen tiedoston jota ei
        # ollut. Se nostaa FileNotFoundErrorin, joka on OSError, jonka tämä
        # except nielaisi — ja välimuisti ei toiminut kertaakaan. Levylle jäi
        # 1212 orpoa tiedostoa ja jokainen lataus purki äänen uudestaan.
        with open(tmp, "wb") as handle:
            np.save(handle, db)
        tmp.replace(cache_path)
    except OSError:
        tmp.unlink(missing_ok=True)
