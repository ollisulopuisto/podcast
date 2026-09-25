"""Renderöinti: vienti videotiedostoksi ilman Final Cutia.

Käyttäjän työnkulku (2026-09-25): koko jakso pystyvideona, josta erillinen
sovellus poimii lupaavat kohdat shortseiksi ja ne leikataan tästä
tiedostosta — Final Cutia ei tarvitse avata uudestaan. Final Cut jää sitä
varten kun leikkausta muokataan käsin, joten tämän on näytettävä samalta
kuin Final Cutin vienti samasta XML:stä.

Siksi päätöksiä ei tehdä täällä uudestaan. XML:n kirjoittaja antaa
jokaisesta kuvasta ``Shot``in — kameratiedosto, kohta tiedostossa, skaala
ja sijainti, täsmälleen ne luvut jotka se kirjoittaa XML:ään — ja tämä
moduuli piirtää ne ffmpegillä. Ääni summataan samoista käsitellyistä
tiedostoista samoilla vaimennus- ja panorointikäyrillä kuin viennissä.

Geometria on Final Cutin: kuva skaalataan projektin keskipisteen ympäri
(täyttö × skaala) ja siirretään sitten, sijainti prosentteina projektin
korkeudesta, y ylöspäin. Johdettu ``reframe.py``ssä ja varmistettu käyttäjän
omasta pystypohjasta.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass


@dataclass
class Shot:
    """Yksi kuva ohjelmassa, ohjelman ruutuina ``[start, end)``.

    ``path`` tyhjä on musta (osien välinen aukko). ``lane`` 1 on reaktiokuva
    joka peittää alla olevan kuvan kestonsa ajan.
    """

    start: int
    end: int
    path: str = ""
    file_start: float = 0.0     # sekuntia tiedoston alusta
    width: int = 0
    height: int = 0
    scale0: float = 1.0         # skaala kuvan alussa (täytön tai sovituksen päälle)
    scale1: float = 1.0         # ja lopussa; eri kuin scale0 = mikroliike
    pos_x: float = 0.0          # Final Cutin yksiköissä: % projektin korkeudesta
    pos_y: float = 0.0
    fill: bool = False          # Spatial Conform «Fill» (pystyvienti), muuten «Fit»
    lane: int = 0


def base_factor(shot: Shot, pw: int, ph: int) -> float:
    """Lähteen kerroin projektiin ennen skaalaa: täyttö tai sovitus."""
    if not shot.width or not shot.height:
        return 1.0
    fits = (pw / shot.width, ph / shot.height)
    return max(fits) if shot.fill else min(fits)


def window(shot: Shot, pw: int, ph: int, scale: float) -> tuple[float, float, float, float]:
    """Skaalatun kuvan koko ja rajausikkunan vasen yläkulma siinä.

    Palauttaa ``(leveys, korkeus, x, y)`` pikseleinä: kuva skaalataan
    kertoimella ``täyttö × scale`` ja siitä rajataan projektin kokoinen
    ikkuna. Final Cut skaalaa keskipisteen ympäri ja siirtää sitten:
    sijainti ``pos_x`` siirtää kuvaa oikealle, joten ikkuna liikkuu
    vasemmalle; ``pos_y`` ylös, joten ikkuna liikkuu alas.
    """
    factor = base_factor(shot, pw, ph) * scale
    width, height = shot.width * factor, shot.height * factor
    unit = ph / 100.0
    x = width / 2 - pw / 2 - shot.pos_x * unit
    y = height / 2 - ph / 2 + shot.pos_y * unit
    return width, height, x, y


# ------------------------------------------------------------------ kuva

from fractions import Fraction  # noqa: E402  (yllä olevat ovat puhdasta dataa)


def _even(value: float) -> int:
    return max(2, int(round(value / 2)) * 2)


def _source_window(shot: Shot, pw: int, ph: int, scale: float) -> tuple[float, float, float, float]:
    """Rajausikkuna lähteen pikseleinä: ``(x, y, leveys, korkeus)``."""
    k = base_factor(shot, pw, ph) * scale
    width, height = shot.width * k, shot.height * k
    unit = ph / 100.0
    x = min(max(width / 2 - pw / 2 - shot.pos_x * unit, 0), width - pw)
    y = min(max(height / 2 - ph / 2 + shot.pos_y * unit, 0), height - ph)
    return x / k, y / k, pw / k, ph / k


def video_filter(shot: Shot, pw: int, ph: int, frames: int, fps: str) -> str:
    """ffmpeg-suodin yhdelle kuvalle: skaalaus ja rajaus Final Cutin tapaan.

    **Rajaus ensin lähteestä, skaalaus vasta sitten.** Ensimmäinen versio
    skaalasi koko kuvan täyttöön (3413×1920, zoomissa ~3750×2110) ja rajasi
    siitä 1080×1920 — nelinkertainen skaalaustyö, ja koko jakson renderöinti
    kulki reaaliajassa (video files, 46 min jakso ~40 min). Nyt lähteestä
    rajataan kokonaislukuikkuna joka kattaa tarvittavan alueen, skaalataan
    se, ja lopullinen rajaus on muutaman pikselin tarkennus.

    Mikroliike (``scale0 != scale1``): lähteestä rajataan alkuzoomin ja
    loppuzoomin ikkunoiden yhdiste — ikkuna liikkuu zoomin mukana
    yksisuuntaisesti, joten yhdiste kattaa välin — ja se skaalataan joka
    ruudulle. Ruudun numero aikaleimasta eikä ``n``istä: ``scale``n ``n``
    on yhden edellä ``crop``in ``n``ää (mitattu: ensimmäinen ruutu 3,5 px
    sivussa), ja ``crop`` ei konfiguroidu uudelleen kun kuvan koko muuttuu
    kesken virran, joten koko lasketaan lausekkeesta molempiin.
    Sovitus joka jää projektia pienemmäksi (ei pystyviennissä) käyttää
    vanhaa polkua: skaalaus, mustat reunat, rajaus.
    """
    factor = base_factor(shot, pw, ph)
    parts = [f"fps={fps}"]
    small = min(shot.scale0, shot.scale1)
    if shot.width * factor * small < pw or shot.height * factor * small < ph:
        return _padded_filter(shot, pw, ph, fps)
    windows = [_source_window(shot, pw, ph, shot.scale0),
               _source_window(shot, pw, ph, shot.scale1)]
    left = max(0, int(min(w[0] for w in windows)))
    top = max(0, int(min(w[1] for w in windows)))
    right = min(shot.width, int(-(-max(w[0] + w[2] for w in windows) // 1)) + 1)
    bottom = min(shot.height, int(-(-max(w[1] + w[3] for w in windows) // 1)) + 1)
    cw, ch = right - left, bottom - top
    parts.append(f"crop=w={cw}:h={ch}:x={left}:y={top}")
    unit = ph / 100.0
    px, py = shot.pos_x * unit, shot.pos_y * unit
    if abs(shot.scale1 - shot.scale0) < 1e-9:
        k = factor * shot.scale0
        sw, sh = _even(cw * k), _even(ch * k)
        x0, y0, _w, _h = windows[0]
        dx = min(max((x0 - left) * sw / cw, 0), sw - pw)
        dy = min(max((y0 - top) * sh / ch, 0), sh - ph)
        parts.append(f"scale={sw}:{sh}:flags=lanczos")
        parts.append(f"crop=w={pw}:h={ph}:x={dx:.3f}:y={dy:.3f}")
    else:
        step = (shot.scale1 - shot.scale0) / max(1, frames - 1)
        rate = 1 / Fraction(fps)
        index = f"round(t*{float(1 / rate)})"
        k = f"(({shot.scale0}+{step}*{index})*{factor})"
        sw = f"(2*trunc({cw}*{k}/2))"
        sh = f"(2*trunc({ch}*{k}/2))"
        # Ikkunan vasen yläkulma lähteessä tällä zoomilla, rajatun alueen
        # koordinaateissa, skaalattuna: sama kuin ``_source_window``.
        wx = (f"(clip({shot.width}*{k}/2-{pw}/2-({px}),0,{shot.width}*{k}-{pw})"
              f"/{k}-{left})*{sw}/{cw}")
        wy = (f"(clip({shot.height}*{k}/2-{ph}/2+({py}),0,{shot.height}*{k}-{ph})"
              f"/{k}-{top})*{sh}/{ch}")
        parts.append(f"scale=w='{sw}':h='{sh}':eval=frame:flags=lanczos")
        parts.append(f"crop=w={pw}:h={ph}"
                     f":x='clip({wx},0,{sw}-{pw})':y='clip({wy},0,{sh}-{ph})'")
    parts += ["setsar=1", "format=yuv420p"]
    return ",".join(parts)


def _padded_filter(shot: Shot, pw: int, ph: int, fps: str) -> str:
    """Sovitus joka jää projektia pienemmäksi: skaalaus, mustat reunat keskelle.

    Ei pystyviennissä (täyttö peittää aina) eikä vaakaviennissä (lähde on
    projektin kokoinen ja skaala vähintään 1), joten polku on varaventtiili:
    skaala on kuvan alun, eikä sijaintia sovelleta mustan reunan päälle.
    """
    factor = base_factor(shot, pw, ph) * shot.scale0
    sw = min(_even(shot.width * factor), pw)
    sh = min(_even(shot.height * factor), ph)
    return ",".join([
        f"fps={fps}", f"scale={sw}:{sh}:flags=lanczos",
        f"pad=w={pw}:h={ph}:x=(ow-iw)/2:y=(oh-ih)/2",
        "setsar=1", "format=yuv420p",
    ])


def _fps(frame_duration: Fraction) -> str:
    rate = 1 / Fraction(frame_duration)
    return f"{rate.numerator}/{rate.denominator}"


def flatten(shots: list[Shot], frame_duration: Fraction) -> list[Shot]:
    """Reaktiokuvat (lane 1) peittävät alla olevan: yksi kuvien jono.

    Peitetty kuva pilkotaan, ja pala jatkuu tiedostossa siitä kohdasta johon
    peitto päättyi; mikroliikkeen skaala interpoloidaan palan rajoille.
    """
    base = sorted((s for s in shots if s.lane == 0), key=lambda s: s.start)
    over = sorted((s for s in shots if s.lane != 0), key=lambda s: s.start)
    seconds = float(frame_duration)

    def piece(shot: Shot, a: int, b: int) -> Shot:
        span = max(1, shot.end - shot.start - 1)
        at = lambda k: shot.scale0 + (shot.scale1 - shot.scale0) * (k - shot.start) / span  # noqa: E731
        return Shot(a, b, shot.path, shot.file_start + (a - shot.start) * seconds,
                    shot.width, shot.height, at(a), at(b - 1) if b - a > 1 else at(a),
                    shot.pos_x, shot.pos_y, shot.fill, shot.lane)

    out: list[Shot] = []
    for shot in base:
        cursor = shot.start
        for cover in over:
            if cover.end <= cursor or cover.start >= shot.end:
                continue
            if cover.start > cursor:
                out.append(piece(shot, cursor, cover.start))
            low, high = max(cover.start, cursor), min(cover.end, shot.end)
            out.append(piece(cover, low, high))
            cursor = high
        if cursor < shot.end:
            out.append(piece(shot, cursor, shot.end))
    return [s for s in out if s.end > s.start]


def _ffmpeg() -> str:
    from speechmix.binaries import get_binary_path

    return get_binary_path("ffmpeg")


class Stopped(Exception):
    """Renderöinti pysäytettiin käyttöliittymästä."""


# Koodain. VideoToolbox (Applen laitteistokoodain) kun se toimii, muuten
# x264. Mitattuna 60 s:n 1080p-kuvalla pystyyn (skaalaus 3414×1920, rajaus):
# x264 veryfast 5,0 s ja 30,6 s suoritinaikaa, VideoToolbox 4,4 s ja 14,9 s,
# laitteistopurku lisäksi 6,1 s ja 12,0 s. Kello liikkuu vähän, koska
# skaalaus on hitain osa, mutta suoritin puolittuu, ja kuvia koodataan
# kolme rinnakkain; laitteistopurku oli hitaampi, joten purku jää
# ohjelmalliseksi. 8 Mb/s on pystyvedokselle väljä.
VIDEOTOOLBOX = ["-c:v", "h264_videotoolbox", "-b:v", "8M", "-allow_sw", "0"]
X264 = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18"]
_ENCODER: tuple[str, list[str]] | None = None


def _trial(args: list[str]) -> bool:
    """Koodaako tämä kone yhden ruudun näillä asetuksilla."""
    done = subprocess.run(
        [_ffmpeg(), "-nostdin", "-v", "error", "-f", "lavfi",
         "-i", "color=black:s=1080x1920:r=25", "-frames:v", "1", *args,
         "-f", "null", "-"],
        capture_output=True, stdin=subprocess.DEVNULL, check=False)
    return done.returncode == 0


def encoder() -> tuple[str, list[str]]:
    """``(nimi, ffmpeg-argumentit)``: laitteisto jos se toimii, kerran kysyttynä.

    Kokeillaan eikä päätellä: koodain voi olla ffmpegin listalla mutta
    puuttua koneesta (virtuaalikone, GitHubin ajurit), ja silloin ensimmäinen
    kuva kaatuisi keskellä ajoa.
    """
    global _ENCODER
    if _ENCODER is None:
        _ENCODER = (("h264_videotoolbox", VIDEOTOOLBOX) if _trial(VIDEOTOOLBOX)
                    else ("libx264", X264))
    return _ENCODER


def _run(command: list[str], stop=None) -> None:
    """ffmpeg, joka lopetetaan heti kun ``stop`` asetetaan."""
    child = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    while True:
        try:
            _out, err = child.communicate(timeout=0.2)
            break
        except subprocess.TimeoutExpired:
            if stop is not None and stop.is_set():
                child.kill()
                child.communicate()
                raise Stopped() from None
    if child.returncode != 0:
        raise subprocess.CalledProcessError(child.returncode, command, stderr=err)


def _encode(shot: Shot, pw: int, ph: int, fps: str, target: str, stop=None) -> None:
    frames = shot.end - shot.start
    if shot.path:
        inputs = ["-ss", f"{shot.file_start:.6f}", "-i", shot.path,
                  "-vf", video_filter(shot, pw, ph, frames, fps)]
    else:
        inputs = ["-f", "lavfi", "-i", f"color=black:s={pw}x{ph}:r={fps}",
                  "-vf", "format=yuv420p"]
    _run([_ffmpeg(), "-nostdin", "-v", "error", "-y", *inputs, "-frames:v", str(frames),
          "-an", *encoder()[1], "-r", fps, "-f", "mpegts", target], stop)


def draw_parts(shots: list[Shot], pw: int, ph: int, frame_duration: Fraction,
               _total_frames: int, work: str, progress=None, workers: int = 3,
               stop=None) -> list[str]:
    """Kuvat paloiksi hakemistoon ``work``: jokainen kuva omaksi palakseen.

    ``_total_frames`` on yhteisen rajapinnan vuoksi (AVFoundation tarvitsee
    sen); täällä kesto tulee kuvista ja ``join`` rajaa sen.

    Kuva kerrallaan eikä yhtenä suodinverkkona: satojen kuvien verkko on
    hauras ja yksi virhe kaataa kaiken. Palat koodataan samoilla asetuksilla,
    joten liitos (``join``) on pelkkä kopio. Ruutumäärät tulevat kuvista,
    joten kesto on täsmälleen ohjelman kesto.
    """
    import os
    from concurrent.futures import ThreadPoolExecutor

    flat = flatten(shots, frame_duration)
    fps = _fps(frame_duration)
    names = [os.path.join(work, f"{i:05d}.ts") for i in range(len(flat))]
    done = [0]

    def one(index: int) -> None:
        if stop is not None and stop.is_set():
            raise Stopped()
        _encode(flat[index], pw, ph, fps, names[index], stop)
        done[0] += 1
        if progress is not None:
            progress(done[0] / max(1, len(flat)))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one, range(len(flat))))
    return names


def join(parts: list[str], total_frames: int, out_path: str, stop=None,
         audio: str | None = None) -> None:
    """Palat peräkkäin ja ääni mukaan yhdellä kopiolla, koodaamatta.

    Ilman ``+faststart``ia: se kirjoittaa koko tiedoston vielä kerran
    siirtääkseen hakemiston alkuun, mitä tarvitaan vain verkkotoistoon —
    renderöinti menee paikalliselle leikkeenpoimijalle.
    """
    import os

    listing = os.path.join(os.path.dirname(parts[0]), "list.txt")
    with open(listing, "w", encoding="utf-8") as handle:
        handle.writelines(f"file '{name}'\n" for name in parts)
    command = [_ffmpeg(), "-nostdin", "-v", "error", "-y",
               "-f", "concat", "-safe", "0", "-i", listing]
    if audio:
        command += ["-i", audio, "-map", "0:v:0", "-map", "1:a:0"]
    _run([*command, "-frames:v", str(total_frames), "-c", "copy", out_path], stop)


def render_video(shots: list[Shot], pw: int, ph: int, frame_duration: Fraction,
                 total_frames: int, out_path: str, progress=None, workers: int = 3,
                 stop=None) -> None:
    """Kuvat videoksi ``out_path``iin: ``draw_parts`` ja ``join``."""
    import shutil
    import tempfile

    work = tempfile.mkdtemp(prefix="autoraffkat-render-")
    try:
        parts = draw_parts(shots, pw, ph, frame_duration, total_frames, work,
                           progress, workers, stop)
        join(parts, total_frames, out_path, stop)
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ------------------------------------------------------------------ ääni

import numpy as np  # noqa: E402


@dataclass
class AudioSource:
    """Yksi äänitiedosto ohjelmassa.

    ``placements`` on ``(aikajanan alku, aikajanan loppu, tiedoston alku)``
    sekunteina. ``duck`` on vaimennus- ja häivytyskäyrä aikajanan aikaa
    (``(t, dB)``, sama joka menee vientiin keyframeiksi), ``pan`` Final Cutin
    «Stereo Left/Right» -määrä -100…100 ja ``gain_db`` kiinteä taso.
    """

    path: str
    placements: list
    duck: list = None  # type: ignore[assignment]
    pan: float = 0.0
    gain_db: float = 0.0


def _pan_gains(pan: float) -> tuple[float, float]:
    """Monoraita stereoksi: keskellä täysi taso kumpaankin, sivussa toinen
    kanava hiljenee. Tasapaino eikä vakiotehon laki: Final Cutin monoklippi
    stereoprojektissa soi keskellä täydellä tasolla molemmista."""
    amount = max(-1.0, min(1.0, pan / 100.0))
    return min(1.0, 1.0 - amount), min(1.0, 1.0 + amount)


def render_audio(sources: list[AudioSource], program_start: float, seconds: float,
                 out_path: str, rate: int = 48000, block: float = 60.0,
                 progress=None, stop=None) -> None:
    """Äänilähteet stereoksi minuutin paloissa, ohjelman pituisena.

    Paloittain, koska tunnin jakso kahdella mikillä olisi muistissa
    gigatavuja. Vaimennuskäyrä luetaan aikajanan ajassa kuten vienti sen
    kirjoittaa; tiedostojen taso on jo käsittelyn, joten muuta tasoa ei
    tehdä.
    """
    from pedalboard.io import AudioFile

    total = int(round(seconds * rate))
    step = int(block * rate)
    opened: dict = {}
    try:
        with AudioFile(out_path, "w", samplerate=rate, num_channels=2) as out:
            for first in range(0, total, step):
                if stop is not None and stop.is_set():
                    raise Stopped()
                count = min(step, total - first)
                t0 = program_start + first / rate
                mix = np.zeros((2, count), dtype=np.float32)
                for source in sources:
                    left, right = _pan_gains(source.pan)
                    for start, end, file_start in source.placements:
                        low, high = max(start, t0), min(end, t0 + count / rate)
                        if high <= low:
                            continue
                        a = int(round((low - t0) * rate))
                        n = min(count - a, int(round((high - low) * rate)))
                        if n <= 0:
                            continue
                        handle = opened.get(source.path)
                        if handle is None:
                            handle = AudioFile(source.path).resampled_to(rate)
                            opened[source.path] = handle
                        handle.seek(int(round((file_start + low - start) * rate)))
                        chunk = handle.read(n)
                        mono = chunk.mean(axis=0) if chunk.ndim == 2 else chunk
                        mono = mono[:n].astype(np.float32)
                        if len(mono) < n:
                            mono = np.pad(mono, (0, n - len(mono)))
                        gain = 10 ** (source.gain_db / 20.0)
                        if source.duck:
                            times = low + np.arange(n) / rate
                            db = np.interp(times, [p[0] for p in source.duck],
                                           [p[1] for p in source.duck])
                            mono = mono * (10 ** (db / 20.0)).astype(np.float32)
                        mix[0, a:a + n] += mono * gain * left
                        mix[1, a:a + n] += mono * gain * right
                out.write(mix)
                if progress is not None:
                    progress(min(1.0, (first + count) / max(1, total)))
    finally:
        for handle in opened.values():
            handle.close()


# ------------------------------------------------------------------ kokonaisuus


def video_backend():
    """``(nimi, palat)``: AVFoundation macOS:llä, muuten ffmpeg.

    Palat-funktio piirtää kuvan hakemistoon ja palauttaa palatiedostot,
    jotka ``join`` liittää.

    AVFoundation tekee purun, muunnoksen ja koodauksen näytönohjaimella
    kuten Final Cut (``render_av.py``); ffmpeg on varapolku ja Windowsin
    polku. Sama ``Shot``-lista ja sama geometria kummassakin, ja samat
    merkkitestit ajetaan kummallekin.
    """
    import sys

    if sys.platform == "darwin":
        try:
            from . import render_av

            return "avfoundation", render_av.draw_parts
        except ImportError:
            pass
    return f"ffmpeg/{encoder()[0]}", draw_parts


def render_program(shots: list[Shot], sources: list[AudioSource], pw: int, ph: int,
                   frame_duration: Fraction, total_frames: int, program_start: float,
                   out_path: str, progress=None, stop=None) -> None:
    """Kuva, ääni ja yhdistäminen: valmis MP4 ``out_path``iin.

    ``stop`` (``threading.Event``) pysäyttää kesken: käynnissä olevat
    ffmpegit lopetetaan ja ``Stopped`` nostetaan. Puolikasta tiedostoa ei
    jää, koska lopullinen nimi annetaan vasta valmiille.

    Kirjoitetaan ensin viereen väliaikaisena ja nimetään lopuksi, jottei
    kesken jäänyt ajo jätä puolikasta tiedostoa joka näyttää valmiilta.

    Ääni ja sen AAC-koodaus tehdään omassa säikeessään kuvan aikana, ja
    lopuksi kuvan palat ja ääni liitetään yhdellä kopiolla. Mitattuna 46
    minuutin jaksolla M2:lla ennen tätä: kuvan jälkeen vielä 73 s, josta
    suurin osa äänen koodausta ja kaksi koko kuvan kopiota.
    """
    import os
    import shutil
    import tempfile
    import threading
    import time

    def stage(low: float, high: float):
        return (lambda f: progress(low + (high - low) * f)) if progress else None

    def log(message: str) -> None:
        """Kulku terminaaliin, kuten mittauksella ja äänellä: kun ajo on
        hidas, kysymys on mikä vaihe."""
        print(f"[video] {message}", flush=True)

    seconds = float(total_frames * frame_duration)
    began = time.monotonic()
    backend, draw = video_backend()
    log(f"alkaa: {len(shots)} kuvaa, {seconds / 60:.1f} min, {pw}×{ph}, "
        f"{backend} -> {out_path}")

    work = tempfile.mkdtemp(prefix="autoraffkat-render-")
    pictures = os.path.join(work, "kuva")
    os.makedirs(pictures)
    wav = os.path.join(work, "audio.wav")
    aac = os.path.join(work, "audio.m4a")
    partial = out_path + ".partial.mp4"
    halt = threading.Event()

    class _Either:
        """Pysäytys käyttöliittymästä tai kuvan kaatuessa."""

        def is_set(self) -> bool:
            return halt.is_set() or (stop is not None and stop.is_set())

    failures: list = []
    audio_time = [0.0]

    def make_audio() -> None:
        try:
            mark = time.monotonic()
            render_audio(sources, program_start, seconds, wav, stop=_Either())
            _run([_ffmpeg(), "-nostdin", "-v", "error", "-y", "-i", wav,
                  "-c:a", "aac", "-b:a", "256k", aac], _Either())
            audio_time[0] = time.monotonic() - mark
        except BaseException as exc:  # välitetään pääsäikeeseen
            failures.append(exc)

    sound = threading.Thread(target=make_audio, name="render-audio", daemon=True)
    try:
        sound.start()
        mark = time.monotonic()
        try:
            parts = draw(shots, pw, ph, frame_duration, total_frames, pictures,
                         progress=stage(0.0, 0.95), stop=stop)
        except BaseException:
            halt.set()
            raise
        finally:
            if halt.is_set():
                sound.join()
        log(f"kuva {time.monotonic() - mark:.0f} s")
        sound.join()
        if failures:
            raise next((e for e in failures if isinstance(e, Stopped)), failures[0])
        log(f"ääni {audio_time[0]:.0f} s (kuvan aikana)")
        mark = time.monotonic()
        join(parts, total_frames, partial, stop, audio=aac)
        os.replace(partial, out_path)
        total = time.monotonic() - began
        log(f"yhdistäminen {time.monotonic() - mark:.0f} s; valmis {total:.0f} s "
            f"({seconds / max(total, 1e-6):.1f}× reaaliaika) -> {out_path}")
        if progress is not None:
            progress(1.0)
    finally:
        shutil.rmtree(work, ignore_errors=True)
        if os.path.exists(partial):
            os.remove(partial)
