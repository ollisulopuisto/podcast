"""Paikallinen web-käyttöliittymä.

Kuori on ohut: se tuntee moduulit, työjonon ja tiedostoselaimen. Kaikki
muu on moduulien omissa reitittimissä, jotka liitetään ``/api/<avain>``
-polkuun. Selainpuoli tekee saman: ``app.js`` on kuori ja ``mod_*.js``
rekisteröi paneelin.
"""

from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__, pick
from ..binaries import has_binary
from ..jobs import RUNNER
from ..modules import MODULES, to_list
from ..paths import get_resource_path

STATIC_DIR = get_resource_path("server/static")


def create_app(start_dir: str = "", session: str = "") -> FastAPI:
    app = FastAPI(title="Podcast Magic", docs_url=None, redoc_url=None)

    @app.get("/")
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/state")
    def state():
        job = RUNNER.current()
        return {
            "version": __version__,
            "modules": to_list(),
            "ffmpeg": has_binary("ffmpeg"),
            # Selain avautuu sinne missä työ on: annetun istunnon kansioon,
            # ei siihen hakemistoon josta komento sattui lähtemään.
            "startDir": (os.path.dirname(session) if session else start_dir) or os.getcwd(),
            "session": session,
            "job": job.snapshot() if job else None,
        }

    @app.get("/api/job")
    def job_state():
        job = RUNNER.current()
        return job.snapshot() if job else JSONResponse({"running": False, "id": 0})

    @app.post("/api/job/cancel")
    def job_cancel():
        return {"cancelled": RUNNER.cancel()}

    @app.get("/api/browse")
    def browse(dir: str = ""):
        return pick.browse(dir or start_dir or os.getcwd())

    @app.get("/api/exists")
    def exists(path: str = ""):
        """Onko polku olemassa. Käytetään kun polku kirjoitetaan käsin."""
        target = os.path.abspath(os.path.expanduser(path))
        return {"path": target, "file": os.path.isfile(target), "dir": os.path.isdir(target)}

    @app.post("/api/reveal")
    def reveal(body: dict):
        """Näyttää tuloksen Finderissa.

        Viennin jälkeen seuraava käyttäjä on aina Hindenburg, ja polun
        etsiminen käsin on se kohta jossa työ katkeaa.
        """
        import subprocess
        import sys

        path = str(body.get("path") or "")
        if not os.path.exists(path):
            raise HTTPException(404, "Tiedostoa ei löydy.")
        if sys.platform == "darwin":
            subprocess.run(["open", "-R", path], check=False)
        elif sys.platform.startswith("win"):
            subprocess.run(["explorer", "/select,", path], check=False)
        else:
            subprocess.run(["xdg-open", os.path.dirname(path)], check=False)
        return {"ok": True}

    for module in MODULES:
        app.include_router(module.router, prefix=f"/api/{module.key}")

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    return app
