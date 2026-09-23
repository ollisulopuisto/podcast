"""Kuuntelvertailun kokoaja: tiedostot numeroitu, mitattu ja piirretty.

Vertailusivu on se jolla ketjun muutokset hyväksytään korvalla, joten sen
luvut ovat päätöksen pohja. Kaksi asiaa on rikkoutunut kerran: numeron ja
näppäimen ero (tiedosto «0 …» napissa 1) ja pitkä tiedosto, jonka selain
purki kokonaan muistiin. Siksi numerot tulevat järjestyksestä 1:stä alkaen
ja aaltomuoto lasketaan täällä valmiiksi.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("ab_compare", ROOT / "scripts" / "ab" / "compare.py")
compare = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(compare)

RATE = 48000


def _wav(path, level, seconds=3.0):
    t = np.arange(int(seconds * RATE)) / RATE
    sf.write(path, (level * np.sin(2 * np.pi * 220 * t)).astype(np.float32), RATE)
    return path


def test_a_set_is_numbered_measured_and_drawn(tmp_path):
    a = _wav(tmp_path / "oma render.wav", 0.5)
    b = _wav(tmp_path / "automixer.wav", 0.1)
    folder = compare.build([a, b], tmp_path / "ab", "pikis")

    rows = json.loads((folder / "files.json").read_text(encoding="utf-8"))
    assert [r["name"] for r in rows] == ["1 oma render.wav", "2 automixer.wav"]
    assert all((folder / r["name"]).resolve() == p.resolve()
               for r, p in zip(rows, (a, b), strict=True))
    # Tasoero näkyy lukemissa, jotta tasattu kuuntelu on mahdollinen.
    assert abs((rows[0]["lufs"] - rows[1]["lufs"]) - 20 * np.log10(5)) < 0.1
    assert len(rows[0]["peaks"]) == compare.PEAKS
    # Lohkoittainen mittaus on sama luku kuin pyloudnormin koko tiedostosta.
    import pyloudnorm as pyln

    audio, _ = sf.read(a)
    assert abs(rows[0]["lufs"] - pyln.Meter(RATE).integrated_loudness(audio)) < 0.05
    assert (folder / "vertailu.html").exists()


def test_the_server_answers_a_byte_range(tmp_path):
    """Pitkä tiedosto soitetaan `<audio>`illa, ja se siirtyy pyytämällä
    tavuvälin. Pythonin oma palvelin vastaa koko tiedostolla, jolloin
    siirtyminen palaa alkuun eikä vertailu osu samaan kohtaan."""
    import functools
    import http.server
    import threading
    import urllib.request

    (tmp_path / "x.bin").write_bytes(bytes(range(256)))
    handler = functools.partial(compare.RangeHandler, directory=str(tmp_path))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/x.bin"
        request = urllib.request.Request(url, headers={"Range": "bytes=10-19"})
        with urllib.request.urlopen(request) as response:
            assert response.status == 206
            assert response.headers["Content-Range"] == "bytes 10-19/256"
            assert response.read() == bytes(range(10, 20))
    finally:
        server.shutdown()
