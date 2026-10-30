"""Äänenkäsittelyn lapsiprosessi: puhujaruudukko on rakennettava kun mikä
tahansa sitä tarvitseva asetus on päällä, ei vain vaimennus."""

import io
import json

from conftest import needs_ffmpeg

from autoraffkat.audio import worker
from autoraffkat.model import ROLE_CLOSE, ROLE_MIC, ROLE_WIDE, AudioSettings, TrackConfig
from autoraffkat.project import ProjectSettings


def _tracks():
    return {
        "WIDE.mp4": TrackConfig(role=ROLE_WIDE),
        "CLOSE_A.mp4": TrackConfig(role=ROLE_CLOSE, speaker="Host"),
        "CLOSE_B.mp4": TrackConfig(role=ROLE_CLOSE, speaker="Guest"),
        "MIC_A.wav": TrackConfig(role=ROLE_MIC, speaker="Host"),
        "MIC_B.wav": TrackConfig(role=ROLE_MIC, speaker="Guest"),
    }


def test_worker_reconnects_missing_windowed_stdio_to_subprocess_pipes(monkeypatch):
    streams = {0: io.StringIO(), 1: io.StringIO(), 2: io.StringIO()}
    monkeypatch.setattr(worker.sys, "stdin", None)
    monkeypatch.setattr(worker.sys, "stdout", None)
    monkeypatch.setattr(worker.sys, "stderr", None)
    monkeypatch.setattr(worker.os, "fdopen", lambda fd, *args, **kwargs: streams[fd])

    worker._restore_stdio()

    assert worker.sys.stdin is streams[0]
    assert worker.sys.stdout is streams[1]
    assert worker.sys.stderr is streams[2]


@needs_ffmpeg
def test_debleed_alone_still_builds_the_grid(scratch_xml, monkeypatch):
    """Vaimennus pois, ristivuodon vähennys päällä: ruudukko on silti tehtävä.

    Ennen korjausta ``worker.py`` rakensi puhujaruudukon vain
    ``audio.duck``in ehdolla. Ristivuodon vähennys lukee samaa ruudukkoa
    riippumattomasti (``mix.py``: ``solos = solo_masks(grid) if
    settings.debleed else {}``), joten se jäi hiljaa tekemättä aina kun
    vaimennus oli pois päältä — «asetus päällä, tuloksessa ei mitään»,
    tämän projektin oma toistuva vikaluokka. Oikeassa jaksossa tämä johti
    parikymmentä desibeliä nostettuun, vuotoiseen mikkiin.
    """
    from autoraffkat.audio import mix as mix_module

    monkeypatch.setattr(mix_module.chain, "load_pool", lambda *a, **k: None)

    source = scratch_xml("sync.fcpxml")
    settings = ProjectSettings(
        tracks=_tracks(),
        audio=AudioSettings(enabled=True, plugin_path="", debleed=True, duck=False),
    )
    spec = {"xml_path": str(source), "settings": settings.to_json(), "force": True}

    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(spec)))
    out = io.StringIO()
    monkeypatch.setattr("sys.stdout", out)

    assert worker.main() == 0

    # ``mix._log`` kirjoittaa suoraan stdoutiin omia rivejään (ks.
    # server/app.py:n sama suvaitsevainen jäsennys); vain JSON-rivit
    # kiinnostavat tässä.
    messages = []
    for line in out.getvalue().splitlines():
        if not line.strip():
            continue
        try:
            messages.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    done = next(m for m in messages if m.get("kind") == "done")
    assert "debleed" not in done["errors"], done["errors"]
