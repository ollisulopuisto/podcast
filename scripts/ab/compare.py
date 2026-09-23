"""Kuuntelvertailu: tiedostot sisään, synkattu A/B-sivu selaimeen.

    uv run --package speechmix python scripts/ab/compare.py A.wav B.wav [...] \\
        [--name pikis] [--port 8765]

Kokoaa ``temp/ab/<nimi>/``:iin linkit tiedostoihin numeroituina 1:stä
alkaen, mittaa jokaisen (LUFS, true peak, crest, PSR) ja laskee
aaltomuodon valmiiksi. Sivu (``vertailu.html``) soittaa tiedostot samasta
kohdasta ja vaihtaa niiden välillä näppäimellä; äänekkyyden voi tasata,
jotta kovempi ei voita pelkällä tasolla.

Aaltomuoto lasketaan täällä eikä selaimessa, koska selain purkaisi koko
tiedoston muistiin: puolen tunnin stereojakso on 690 Mt liukulukuina, ja
kaksi sellaista riittää kaatamaan välilehden.
"""

from __future__ import annotations

import argparse
import contextlib
import functools
import http.server
import json
import os
import shutil
import socket
import sys
import threading
import webbrowser
from pathlib import Path

import numpy as np
import soundfile as sf

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DEFAULT_DIR = ROOT / "temp" / "ab"

#: Aaltomuodon pisteitä tiedostoa kohden: näytön leveyden verran riittää.
PEAKS = 2000

#: Lohko jossa pitkä tiedosto luetaan, sekunteina. Mittaus ei pidä koko
#: tiedostoa muistissa.
BLOCK_S = 60.0


class _Loudness:
    """BS.1770 integroitu äänekkyys lohkoittain, ilman koko tiedostoa muistissa.

    K-painotus kulkee lohkosta toiseen suotimen tilan kanssa, ja tehot
    kerätään 100 ms:n paloihin, joista 400 ms:n ikkunat (75 % päällekkäin)
    ja portitus (-70 LUFS, sitten -10 LU) lasketaan lopuksi. Suotimet ovat
    pyloudnormin, jotta luku on sama kuin muualla repossa.
    """

    def __init__(self, rate: int, channels: int):
        import pyloudnorm as pyln

        self.rate = rate
        self.filters = [(f.b, f.a, f.passband_gain)
                        for f in pyln.Meter(rate)._filters.values()]
        self.state = [[None] * len(self.filters) for _ in range(channels)]
        self.bin = rate // 10
        self.carry = np.zeros((0, channels))
        self.bins: list[np.ndarray] = []

    def add(self, block: np.ndarray) -> None:
        from scipy import signal as sp

        out = np.empty(block.shape, dtype=np.float64)
        for ch in range(block.shape[1]):
            x = block[:, ch].astype(np.float64)
            for i, (b, a, g) in enumerate(self.filters):
                zi = self.state[ch][i]
                if zi is None:
                    zi = sp.lfilter_zi(b, a) * 0.0
                x, self.state[ch][i] = sp.lfilter(b, a, x, zi=zi)
                x = x * g
            out[:, ch] = x
        joined = np.concatenate([self.carry, out])
        usable = len(joined) // self.bin * self.bin
        self.bins.append((joined[:usable] ** 2).reshape(-1, self.bin, out.shape[1]).sum(axis=1))
        self.carry = joined[usable:]

    def value(self) -> float:
        if not self.bins:
            return float("nan")
        power = np.concatenate(self.bins)
        if len(power) < 4:
            return float("nan")
        windows = sum(power[i:len(power) - 3 + i] for i in range(4)) / (4 * self.bin)
        z = windows.sum(axis=1)
        level = -0.691 + 10 * np.log10(z + 1e-20)
        z = z[level > -70]
        if not len(z):
            return float("nan")
        relative = -0.691 + 10 * np.log10(z.mean()) - 10
        z = z[-0.691 + 10 * np.log10(z) > relative]
        return float(-0.691 + 10 * np.log10(z.mean()))


def measure(path: Path) -> dict:
    """LUFS, true peak, crest, PSR ja aaltomuoto, lohkoittain."""
    from scipy import signal as sp

    info = sf.info(str(path))
    rate, frames = info.samplerate, info.frames
    step = max(1, frames // PEAKS)
    peaks = np.zeros(PEAKS, dtype=np.float32)
    true_peak, sum_sq, count = 0.0, 0.0, 0
    loudness = _Loudness(rate, info.channels)
    # Lyhyen aikavälin (3 s) taso puolen sekunnin askelin, kuten
    # `chain.peak_to_short_term`: tehot 0,5 s:n paloina, ikkuna kuudesta.
    half = rate // 2
    halves: list[float] = []
    carry = np.zeros(0, dtype=np.float64)
    with sf.SoundFile(str(path)) as handle:
        position = 0
        while position < frames:
            block = handle.read(int(BLOCK_S * rate), dtype="float32", always_2d=True)
            if not len(block):
                break
            loudness.add(block)
            mono = block.mean(axis=1)
            true_peak = max(true_peak, float(np.abs(sp.resample_poly(mono, 4, 1)).max()))
            sum_sq += float(np.sum(mono.astype(np.float64) ** 2))
            count += len(mono)
            index = (position + np.arange(len(mono))) // step
            keep = index < PEAKS
            np.maximum.at(peaks, index[keep], np.abs(mono[keep]))
            carry = np.concatenate([carry, mono.astype(np.float64)])
            usable = len(carry) // half * half
            halves.extend((carry[:usable].reshape(-1, half) ** 2).mean(axis=1))
            carry = carry[usable:]
            position += len(block)
    lufs = loudness.value()
    windows = np.convolve(np.asarray(halves), np.ones(6) / 6, mode="valid")
    short = -0.691 + 10 * np.log10(windows.max() + 1e-20) if len(windows) else np.nan
    tp = 20 * np.log10(true_peak + 1e-12)
    peak_s = 20 * np.log10(float(peaks.max()) + 1e-12)
    rms = 10 * np.log10(sum_sq / max(1, count) + 1e-20)
    return {
        "lufs": round(lufs, 2) if np.isfinite(lufs) else None,
        "tp": round(tp, 2),
        "crest": round(peak_s - rms, 1),
        "psr": round(float(tp - short), 1) if np.isfinite(short) else None,
        "seconds": round(frames / rate, 2),
        "peaks": [round(float(p), 4) for p in peaks],
    }


def build(files, base: Path = DEFAULT_DIR, name: str = "") -> Path:
    """Kokoaa vertailun ``base/name``:en ja palauttaa hakemiston."""
    files = [Path(f).resolve() for f in files]
    name = name or files[0].stem
    folder = Path(base) / name
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    rows = []
    for number, source in enumerate(files, start=1):
        link = folder / f"{number} {source.name}"
        os.symlink(source, link)
        row = measure(source)
        row["name"] = link.name
        rows.append(row)
        print(f"  {link.name}: {row['lufs']} LUFS, {row['tp']} dBTP, "
              f"crest {row['crest']}, PSR {row['psr']}")
    (folder / "files.json").write_text(
        json.dumps(rows, ensure_ascii=False), encoding="utf-8"
    )
    shutil.copy(HERE / "vertailu.html", folder / "vertailu.html")
    return folder


class RangeHandler(http.server.SimpleHTTPRequestHandler):
    """Tiedostopalvelin joka osaa ``Range``-pyynnöt.

    Selaimen ``<audio>`` siirtyy pitkässä tiedostossa pyytämällä tavuvälin.
    Pythonin oma palvelin vastaa aina koko tiedostolla, jolloin siirtyminen
    palaa alkuun — pitkä vertailu ei silloin osu samaan kohtaan.
    """

    def send_head(self):
        spec = self.headers.get("Range", "")
        path = self.translate_path(self.path)
        if not spec.startswith("bytes=") or not os.path.isfile(path):
            return super().send_head()
        size = os.path.getsize(path)
        first, _, last = spec[6:].split(",")[0].partition("-")
        start = int(first) if first else max(0, size - int(last))
        end = min(size - 1, int(last)) if first and last else size - 1
        if start >= size:
            self.send_error(416)
            return None
        # `http.server` sulkee tiedoston kirjoitettuaan sen.
        handle = open(path, "rb")
        handle.seek(start)
        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        self._left = end - start + 1
        return handle

    def copyfile(self, source, outputfile):
        left = getattr(self, "_left", None)
        if left is None:
            return super().copyfile(source, outputfile)
        try:
            while left > 0:
                chunk = source.read(min(1 << 16, left))
                if not chunk:
                    break
                outputfile.write(chunk)
                left -= len(chunk)
        finally:
            self._left = None

    def log_message(self, *args):
        pass


def _serving(port: int) -> bool:
    with socket.socket() as probe:
        return probe.connect_ex(("127.0.0.1", port)) == 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Synkattu A/B-kuuntelu selaimessa")
    parser.add_argument("files", nargs="+", help="äänitiedostot vertailuun")
    parser.add_argument("--name", default="", help="vertailun nimi (oletus: 1. tiedosto)")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    missing = [f for f in args.files if not Path(f).exists()]
    if missing:
        print("Ei löydy: " + ", ".join(missing), file=sys.stderr)
        return 1
    folder = build(args.files, DEFAULT_DIR, args.name)
    url = f"http://127.0.0.1:{args.port}/{folder.name}/vertailu.html"
    if _serving(args.port):
        # Palvelin on jo käynnissä, oletettavasti tämän hakemiston.
        webbrowser.open(url)
        print(url)
        return 0
    handler = functools.partial(
        RangeHandler, directory=str(DEFAULT_DIR)
    )
    server = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    threading.Timer(0.5, webbrowser.open, (url,)).start()
    print(f"{url}  (Ctrl-C lopettaa)")
    with contextlib.suppress(KeyboardInterrupt):
        server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
