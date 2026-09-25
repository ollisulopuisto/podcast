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


def video_filter(shot: Shot, pw: int, ph: int, frames: int, fps: str) -> str:
    """ffmpeg-suodin yhdelle kuvalle: skaalaus ja rajaus Final Cutin tapaan.

    Paikallaan pysyvä kuva on kiinteä skaalaus ja rajaus. Mikroliike
    (``scale0 != scale1``) on lineaarinen skaala ruudusta toiseen, ja
    rajausikkuna lasketaan joka ruudulle skaalatun kuvan koosta: sijainti on
    kiinteä ja skaalaus keskipisteen ympäri, kuten Final Cutissa. Liian
    pieni kuva (sovitus) täytetään mustalla keskelle.
    """
    factor = base_factor(shot, pw, ph)
    unit = ph / 100.0
    px, py = shot.pos_x * unit, shot.pos_y * unit
    parts = [f"fps={fps}"]
    if abs(shot.scale1 - shot.scale0) < 1e-9:
        width = _even(shot.width * factor * shot.scale0)
        height = _even(shot.height * factor * shot.scale0)
        parts.append(f"scale={width}:{height}:flags=lanczos")
        parts.append(f"pad=w='max(iw,{pw})':h='max(ih,{ph})':x='(ow-iw)/2':y='(oh-ih)/2'")
        width, height = max(width, pw), max(height, ph)
        x = min(max(width / 2 - pw / 2 - px, 0), width - pw)
        y = min(max(height / 2 - ph / 2 + py, 0), height - ph)
        parts.append(f"crop=w={pw}:h={ph}:x={x:.3f}:y={y:.3f}")
    else:
        # Mikroliike: skaalatun kuvan koko lasketaan ruudun numerosta sekä
        # skaalaukseen että rajaukseen. ``crop`` ei konfiguroidu uudelleen
        # kun kuvan koko muuttuu kesken virran: sen ``in_w`` jäi ensimmäisen
        # ruudun leveydeksi, ja ikkuna jäi paikalleen kuvan kasvaessa —
        # testissä merkki liukui 185 px, kun oikea liuku on 48.
        #
        # Ruudun numero aikaleimasta eikä ``n``istä: ``scale``n ``n`` on
        # yhden edellä ``crop``in ``n``ää (mitattu: ensimmäinen ruutu 3,5 px
        # sivussa, viimeinen yhden askeleen liian pitkällä), aikaleima on
        # sama kummallekin.
        step = (shot.scale1 - shot.scale0) / max(1, frames - 1)
        rate = 1 / Fraction(fps)
        index = f"round(t*{float(1 / rate)})"
        size = f"({shot.scale0}+{step}*{index})*{factor}"
        wide = f"(2*trunc({shot.width}*{size}/2))"
        tall = f"(2*trunc({shot.height}*{size}/2))"
        parts.append(f"scale=w='{wide}':h='{tall}':eval=frame:flags=lanczos")
        parts.append(f"crop=w={pw}:h={ph}"
                     f":x='clip({wide}/2-{pw}/2-({px}),0,{wide}-{pw})'"
                     f":y='clip({tall}/2-{ph}/2+({py}),0,{tall}-{ph})'")
    parts += ["setsar=1", "format=yuv420p"]
    return ",".join(parts)


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


def _encode(shot: Shot, pw: int, ph: int, fps: str, target: str) -> None:
    frames = shot.end - shot.start
    ffmpeg = _ffmpeg()
    if shot.path:
        inputs = ["-ss", f"{shot.file_start:.6f}", "-i", shot.path,
                  "-vf", video_filter(shot, pw, ph, frames, fps)]
    else:
        inputs = ["-f", "lavfi", "-i", f"color=black:s={pw}x{ph}:r={fps}",
                  "-vf", "format=yuv420p"]
    subprocess.run(
        [ffmpeg, "-nostdin", "-v", "error", "-y", *inputs, "-frames:v", str(frames),
         "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
         "-r", fps, "-f", "mpegts", target],
        check=True, capture_output=True, stdin=subprocess.DEVNULL)


def render_video(shots: list[Shot], pw: int, ph: int, frame_duration: Fraction,
                 total_frames: int, out_path: str, progress=None, workers: int = 3) -> None:
    """Kuvat videoksi: jokainen kuva omaksi palakseen, palat peräkkäin.

    Kuva kerrallaan eikä yhtenä suodinverkkona: satojen kuvien verkko on
    hauras ja yksi virhe kaataa kaiken. Palat koodataan samoilla asetuksilla,
    joten liitos on pelkkä kopio. Ruutumäärät tulevat kuvista, joten kesto
    on täsmälleen ohjelman kesto.
    """
    import os
    import tempfile
    from concurrent.futures import ThreadPoolExecutor

    flat = flatten(shots, frame_duration)
    fps = _fps(frame_duration)
    work = tempfile.mkdtemp(prefix="autoraffkat-render-")
    names = [os.path.join(work, f"{i:05d}.ts") for i in range(len(flat))]
    done = [0]

    def one(index: int) -> None:
        _encode(flat[index], pw, ph, fps, names[index])
        done[0] += 1
        if progress is not None:
            progress(done[0] / max(1, len(flat)))

    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(one, range(len(flat))))
        listing = os.path.join(work, "list.txt")
        with open(listing, "w", encoding="utf-8") as handle:
            handle.writelines(f"file '{name}'\n" for name in names)
        subprocess.run(
            [_ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "concat", "-safe", "0",
             "-i", listing, "-frames:v", str(total_frames), "-c", "copy", out_path],
            check=True, capture_output=True, stdin=subprocess.DEVNULL)
    finally:
        import shutil

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
                 progress=None) -> None:
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


def render_program(shots: list[Shot], sources: list[AudioSource], pw: int, ph: int,
                   frame_duration: Fraction, total_frames: int, program_start: float,
                   out_path: str, progress=None) -> None:
    """Kuva, ääni ja yhdistäminen: valmis MP4 ``out_path``iin.

    Kirjoitetaan ensin viereen väliaikaisena ja nimetään lopuksi, jottei
    kesken jäänyt ajo jätä puolikasta tiedostoa joka näyttää valmiilta.
    Kuva on 85 % työstä, ääni 10 %, yhdistäminen loput.
    """
    import os
    import tempfile

    def stage(low: float, high: float):
        return (lambda f: progress(low + (high - low) * f)) if progress else None

    work = tempfile.mkdtemp(prefix="autoraffkat-render-")
    video = os.path.join(work, "video.mp4")
    audio = os.path.join(work, "audio.wav")
    partial = out_path + ".partial.mp4"
    try:
        render_video(shots, pw, ph, frame_duration, total_frames, video,
                     progress=stage(0.0, 0.85))
        render_audio(sources, program_start, float(total_frames * frame_duration),
                     audio, progress=stage(0.85, 0.95))
        subprocess.run(
            [_ffmpeg(), "-nostdin", "-v", "error", "-y", "-i", video, "-i", audio,
             "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac",
             "-b:a", "256k", "-movflags", "+faststart", partial],
            check=True, capture_output=True, stdin=subprocess.DEVNULL)
        os.replace(partial, out_path)
        if progress is not None:
            progress(1.0)
    finally:
        import shutil

        shutil.rmtree(work, ignore_errors=True)
        if os.path.exists(partial):
            os.remove(partial)
