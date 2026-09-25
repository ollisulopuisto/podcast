"""Renderöinti AVFoundationilla: kuva näytönohjaimella, kuten Final Cutissa.

ffmpeg-renderöinti (``render.py``) purkaa ja skaalaa suorittimella ja ajaa
jokaisen kuvan omana prosessinaan, joka hakee tiedostosta lähimmästä
avainruudusta. Final Cut ei tee mitään niistä: kehys puretaan laitteistolla
suoraan näytönohjaimen muistiin, skaala, sijainti ja rajaus ovat yksi
geometrinen muunnos jonka näytönohjain tekee piirtäessään, ja laitteisto-
koodain lukee valmiin ruudun samasta muistista. Tämä moduuli tekee saman
AVFoundationilla, jonka päällä Final Cut on:

* kuvat liitetään yhdelle aikajanalle (``AVMutableComposition``) suoraan
  kameratiedostoista, ilman välitiedostoja;
* jokaisella kuvalla on muunnos, mikroliikkeellä alusta loppuun liukuva
  (``setTransformRamp…``) — lineaarinen matriisien välillä on lineaarinen
  skaalassa, sama kuin ffmpeg-polussa;
* ``AVAssetExportSession`` purkaa, muuntaa ja koodaa yhdessä putkessa.

Sama ``Shot``-lista ja sama geometria kuin ``render.py``ssä: vain piirtäjä
vaihtuu. Ääni ja yhdistäminen ovat yhteiset.
"""

from __future__ import annotations

import time
from fractions import Fraction

from .render import Shot, Stopped, base_factor, flatten

# Montako vientiä rinnakkain. Mitattuna M1 Maxilla 60 s:n zoomikuvalla:
# yksi 5,3 s (11× reaaliaika), kaksi 7,6 s (16×), neljä 16,3 s (15×) —
# koneessa on kaksi laitteistokoodainta, eikä kolmas vienti saa omaansa.
HALVES = 2

# Tiedostoaikojen aikaskaala. 90 kHz on videon oma yleinen aikapohja, ja se
# jakautuu tasan kaikille tavallisille kuvanopeuksille.
TIMESCALE = 90000


def _time(seconds: float):
    import CoreMedia

    return CoreMedia.CMTimeMake(int(round(seconds * TIMESCALE)), TIMESCALE)


def _frames(count: int, frame_duration: Fraction):
    import CoreMedia

    step = Fraction(frame_duration)
    return CoreMedia.CMTimeMake(count * step.numerator, step.denominator)


def transform(shot: Shot, pw: int, ph: int, scale: float):
    """Lähteen pikselit projektiin: sama geometria kuin ``render.window``.

    Kuva skaalataan projektin keskipisteen ympäri kertoimella täyttö ×
    skaala ja siirretään sijainnin verran (prosentteina projektin
    korkeudesta, y ylöspäin). AVFoundationin koordinaatisto on ylhäältä
    alas, joten y:n merkki kääntyy.
    """
    import Quartz

    k = base_factor(shot, pw, ph) * scale
    unit = ph / 100.0
    tx = pw / 2 + shot.pos_x * unit - k * shot.width / 2
    ty = ph / 2 - shot.pos_y * unit - k * shot.height / 2
    return Quartz.CGAffineTransformMake(k, 0.0, 0.0, k, tx, ty)


def render_video(shots: list[Shot], pw: int, ph: int, frame_duration: Fraction,
                 total_frames: int, out_path: str, progress=None, stop=None) -> None:
    """Kuvat videoksi AVFoundationilla. Sama rajapinta kuin ``render.render_video``.

    Ohjelma jaetaan ``HALVES`` osaan kuvan rajalta, osat viedään rinnakkain
    ja liitetään kopiona: sama koodain ja samat asetukset, joten liitos ei
    koodaa mitään uudestaan.
    """
    import os
    import tempfile
    import threading
    from dataclasses import replace

    from .render import _ffmpeg, _run

    flat = flatten(shots, frame_duration)
    # Raja kuvan alkuun lähimpänä puoliväliä: kuvaa ei katkaista. Ei mustan
    # aukon viereen: AVFoundation jättää viennin lopusta tyhjän jakson pois
    # hiljaa, ja liitoksesta puuttui 9 ruutua.
    choices = [i for i in range(1, len(flat)) if flat[i - 1].path and flat[i].path]
    if HALVES < 2 or not choices:
        _render_part(flat, pw, ph, frame_duration, total_frames, out_path, progress, stop)
        return
    middle = min(choices, key=lambda i: abs(flat[i].start - total_frames / 2))
    split = flat[middle].start
    parts = [(flat[:middle], split),
             ([replace(s, start=s.start - split, end=s.end - split) for s in flat[middle:]],
              total_frames - split)]
    work = tempfile.mkdtemp(prefix="autoraffkat-av-")
    names = [os.path.join(work, f"osa{i}.mp4") for i in range(len(parts))]
    shares = [0.0] * len(parts)
    errors: list = []

    def one(index: int) -> None:
        def report(fraction: float) -> None:
            shares[index] = fraction
            if progress is not None:
                progress(sum(shares) / len(shares))

        try:
            part, frames = parts[index]
            _render_part(part, pw, ph, frame_duration, frames, names[index], report, stop)
        except BaseException as exc:  # välitetään pääsäikeeseen
            errors.append(exc)

    try:
        threads = [threading.Thread(target=one, args=(i,)) for i in range(len(parts))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        if errors:
            raise next((e for e in errors if isinstance(e, Stopped)), errors[0])
        listing = os.path.join(work, "list.txt")
        with open(listing, "w", encoding="utf-8") as handle:
            handle.writelines(f"file '{name}'\n" for name in names)
        _run([_ffmpeg(), "-nostdin", "-v", "error", "-y", "-f", "concat", "-safe", "0",
              "-i", listing, "-c", "copy", out_path], stop)
    finally:
        import shutil

        shutil.rmtree(work, ignore_errors=True)


def _render_part(flat: list[Shot], pw: int, ph: int, frame_duration: Fraction,
                 total_frames: int, out_path: str, progress=None, stop=None) -> None:
    """Yksi vienti: kuvat ruudusta 0 alkaen, ``total_frames`` pitkä."""
    import AVFoundation
    import CoreMedia
    import Foundation
    import Quartz

    composition = AVFoundation.AVMutableComposition.composition()
    track = composition.addMutableTrackWithMediaType_preferredTrackID_(
        AVFoundation.AVMediaTypeVideo, CoreMedia.kCMPersistentTrackID_Invalid)
    assets: dict = {}
    instructions = []
    for shot in flat:
        at = _frames(shot.start, frame_duration)
        frames = shot.end - shot.start
        span = CoreMedia.CMTimeRangeMake(at, _frames(frames, frame_duration))
        layer = AVFoundation.AVMutableVideoCompositionLayerInstruction \
            .videoCompositionLayerInstructionWithAssetTrack_(track)
        if shot.path:
            source = assets.get(shot.path)
            if source is None:
                asset = AVFoundation.AVURLAsset.URLAssetWithURL_options_(
                    Foundation.NSURL.fileURLWithPath_(shot.path),
                    {AVFoundation.AVURLAssetPreferPreciseDurationAndTimingKey: True})
                videos = asset.tracksWithMediaType_(AVFoundation.AVMediaTypeVideo)
                if not videos:
                    raise RuntimeError(f"{shot.path}: ei kuvaraitaa")
                source = videos[0]
                assets[shot.path] = source
            ok, error = track.insertTimeRange_ofTrack_atTime_error_(
                CoreMedia.CMTimeRangeMake(_time(shot.file_start),
                                          _frames(frames, frame_duration)),
                source, at, None)
            if not ok:
                raise RuntimeError(f"{shot.path}: {error}")
            # Liuku päättyy aikavälin loppuun, joka on viimeistä ruutua
            # seuraava hetki: skaala jatketaan sinne, jotta viimeinen ruutu
            # saa ``scale1``n kuten ffmpeg-polussa.
            reach = frames / max(1, frames - 1)
            end = shot.scale0 + (shot.scale1 - shot.scale0) * reach
            pref = source.preferredTransform()
            start_t = Quartz.CGAffineTransformConcat(pref, transform(shot, pw, ph, shot.scale0))
            end_t = Quartz.CGAffineTransformConcat(pref, transform(shot, pw, ph, end))
            layer.setTransformRampFromStartTransform_toEndTransform_timeRange_(
                start_t, end_t, span)
        else:
            track.insertEmptyTimeRange_(span)
            layer.setOpacity_atTime_(0.0, at)
        instruction = AVFoundation.AVMutableVideoCompositionInstruction \
            .videoCompositionInstruction()
        instruction.setTimeRange_(span)
        instruction.setLayerInstructions_([layer])
        instructions.append(instruction)

    video = AVFoundation.AVMutableVideoComposition.videoComposition()
    video.setRenderSize_((pw, ph))
    video.setFrameDuration_(_frames(1, frame_duration))
    video.setInstructions_(instructions)

    # AVFoundation ei kirjoita olemassa olevan päälle ("Cannot Save",
    # -11823), toisin kuin ffmpeg -y.
    import os

    if os.path.exists(out_path):
        os.remove(out_path)
    session = AVFoundation.AVAssetExportSession.alloc().initWithAsset_presetName_(
        composition, AVFoundation.AVAssetExportPresetHighestQuality)
    session.setOutputURL_(Foundation.NSURL.fileURLWithPath_(out_path))
    session.setOutputFileType_(AVFoundation.AVFileTypeMPEG4)
    session.setVideoComposition_(video)
    session.setTimeRange_(CoreMedia.CMTimeRangeMake(
        CoreMedia.kCMTimeZero, _frames(total_frames, frame_duration)))
    session.exportAsynchronouslyWithCompletionHandler_(lambda: None)
    waiting = (AVFoundation.AVAssetExportSessionStatusWaiting,
               AVFoundation.AVAssetExportSessionStatusExporting,
               AVFoundation.AVAssetExportSessionStatusUnknown)
    while session.status() in waiting:
        if stop is not None and stop.is_set():
            session.cancelExport()
            raise Stopped()
        if progress is not None:
            progress(float(session.progress()))
        time.sleep(0.2)
    if session.status() != AVFoundation.AVAssetExportSessionStatusCompleted:
        raise RuntimeError(f"AVFoundation-vienti epäonnistui: {session.error()}")
    if progress is not None:
        progress(1.0)
