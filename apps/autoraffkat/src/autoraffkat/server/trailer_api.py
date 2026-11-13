"""Trailer-sivun rajapinta: pilkonta, ruutu ja vienti.

Sivu ei käytä ``AppState``n projektia: trailer on yksi videotiedosto, ei
lähde-XML. Tila on selaimessa; palvelin laskee (``trailer.plan``), antaa
ruudun kehystysnäkymälle ja kirjoittaa viennin. Vienti kirjataan
``state.remember``illa, jotta «Näytä Finderissa» toimii samoin kuin muualla.
"""

from __future__ import annotations

import math
import os
import subprocess
from typing import TYPE_CHECKING

from fastapi import HTTPException
from fastapi.responses import Response

from speechmix.binaries import get_binary_path

from .. import pick, trailer
from ..finalcut.write import DIALECTS, WriteError, write_fcpxml
from ..finalcut.write_trailer import LANES, build_trailer_fcpxml
from ..i18n import t

if TYPE_CHECKING:  # vain tyypitystä varten
    from .app import AppState

MAX_PIECES = 5000
FRAME_WIDTH = 720


def _video_path(given: object) -> str:
    """Käyttäjän antama polku olemassa olevaksi tiedostoksi, tai HTTP-virhe."""
    path = str(given or "").strip()
    if not path or "\0" in path:
        raise HTTPException(400, t("trailer.no_file"))
    if ".." in path.replace("\\", "/").split("/"):
        raise HTTPException(400, t("trailer.no_file"))
    path = os.path.abspath(os.path.expanduser(path))
    if not os.path.isfile(path):
        raise HTTPException(404, t("export.file_missing"))
    return path


def _number(value: object, name: str, low: float, high: float) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, t("trailer.bad_number", name=name)) from exc
    if not math.isfinite(number):
        raise HTTPException(400, t("trailer.bad_number", name=name))
    return min(max(number, low), high)


def _unique_output(video: str) -> str:
    base = os.path.splitext(video)[0] + " trailer"
    for n in range(1, 100):
        candidate = f"{base}.fcpxml" if n == 1 else f"{base} {n}.fcpxml"
        if not os.path.exists(candidate):
            return candidate
    raise HTTPException(409, t("trailer.too_many_exports"))


def register(app, state: "AppState", _static_dir, versioned) -> None:
    """Lisää trailer-reitit sovellukseen."""

    # Vain käyttäjän valitsemista videoista annetaan ruutuja: muuten rajapinta
    # luovuttaisi minkä tahansa paikallisen videon kuvan.
    chosen: set[str] = set()

    @app.get("/trailer")
    def page():
        return Response(versioned("trailer.html"), media_type="text/html")

    @app.post("/api/trailer/pick")
    def pick_trailer():
        """Videon valinta natiivi-ikkunalla (sama kuin muussa sovelluksessa)."""
        if not pick.has_native_picker():
            return {"path": "", "unavailable": True}
        picked = pick.native_many("", force=True)
        return {"path": picked[0] if picked else ""}

    @app.post("/api/trailer/plan")
    def plan(payload: dict):
        payload = payload or {}
        path = _video_path(payload.get("path"))
        threshold = _number(payload.get("threshold", trailer.SCENE_DEFAULT),
                            "threshold", 0.05, 1.0)
        min_len = _number(payload.get("min_len", trailer.MIN_PIECE),
                          "min_len", 0.3, 30.0)
        every = payload.get("every")
        every = _number(every, "every", 0.5, 600.0) if every else None
        try:
            src, cuts, xs = trailer.plan(path, threshold, min_len, every)
        except trailer.TrailerError as exc:
            raise HTTPException(400, str(exc)) from exc
        except (OSError, subprocess.SubprocessError) as exc:
            raise HTTPException(400, t("trailer.plan_failed")) from exc
        chosen.add(path)
        return {
            "ok": True,
            "path": path,
            "name": src.name,
            "width": src.width,
            "height": src.height,
            "fps": float(1 / src.frame_duration),
            "duration": float(src.duration),
            "has_audio": src.has_audio,
            "pieces": [{"start": a, "end": b, "x": x}
                       for (a, b), x in zip(cuts, xs, strict=True)],
        }

    @app.get("/api/trailer/frame")
    def frame(path: str, t: float = 0.0):
        """Yksi ruutu kehystysnäkymälle (JPEG)."""
        video = _video_path(path)
        if video not in chosen:
            return Response(status_code=404)
        stamp = _number(t, "t", 0.0, 1e6)
        cmd = [get_binary_path("ffmpeg"), "-nostdin", "-v", "error",
               "-ss", f"{stamp:.3f}", "-i", video, "-frames:v", "1",
               "-vf", f"scale={FRAME_WIDTH}:-2", "-f", "image2pipe",
               "-c:v", "mjpeg", "-"]
        try:
            out = subprocess.run(cmd, capture_output=True, stdin=subprocess.DEVNULL,
                                 timeout=60)
        except (OSError, subprocess.SubprocessError):
            return Response(status_code=404)
        if out.returncode != 0 or not out.stdout:
            return Response(status_code=404)
        return Response(out.stdout, media_type="image/jpeg",
                        headers={"Cache-Control": "max-age=3600"})

    @app.post("/api/trailer/export")
    def export(payload: dict):
        payload = payload or {}
        video = _video_path(payload.get("path"))
        lane = payload.get("lane") or "top"
        dialect = payload.get("dialect") or "fcp"
        if lane not in LANES or dialect not in DIALECTS:
            raise HTTPException(400, t("trailer.bad_choice"))
        raw = payload.get("pieces")
        if not isinstance(raw, list) or not raw or len(raw) > MAX_PIECES:
            raise HTTPException(400, t("trailer.bad_pieces"))
        pieces: list[tuple[float, float]] = []
        xs: list[float] = []
        for item in raw:
            if not isinstance(item, dict) or "x" not in item:
                raise HTTPException(400, t("trailer.bad_pieces"))
            a = _number(item.get("start"), "start", 0.0, 1e6)
            b = _number(item.get("end"), "end", 0.0, 1e6)
            # Palat peittävät alun ja lopun aukotta: kirjoitin leikkaa
            # seuraavan palan alusta, joten aukko tai päällekkäisyys vaihtaisi
            # leikkauskohdat hiljaa.
            edge = pieces[-1][1] if pieces else 0.0
            if not b > a or abs(a - edge) > 1e-3:
                raise HTTPException(400, t("trailer.bad_pieces"))
            pieces.append((a, b))
            xs.append(_number(item.get("x"), "x", 0.0, 1.0))
        try:
            src = trailer.probe_source(video)
            if pieces[-1][1] > float(src.duration) + 1e-3:
                raise HTTPException(400, t("trailer.bad_pieces"))
            target = _unique_output(video)
            # Projektin nimi seuraa tiedoston nimeä, jotta numeroidut viennit
            # erottuvat Final Cutin selaimessa.
            xml = build_trailer_fcpxml(
                src, pieces, xs, os.path.splitext(os.path.basename(target))[0],
                enabled_lane=lane, dialect=dialect)
            out_path = write_fcpxml(target, xml)
        except (trailer.TrailerError, WriteError) as exc:
            raise HTTPException(400, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(400, t("trailer.plan_failed")) from exc
        state.remember(out_path)
        return {"ok": True, "path": out_path, "pieces": len(pieces)}
