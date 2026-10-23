#!/usr/bin/env python3
"""Mittapenkki automixerin stemireitille: ``stems_mix.mix_folder``.

Sama reitti jonka kuulas ajaa (``automixer <kansio> -o <tiedosto>
--target-lufs N --progress``). Tämä tekee kolme asiaa:

1. **Luo synteettisen kuulas-kansion** (``tracks.json`` v1, 48 kHz): puhujia
   joilla on puheenvuorot vuorotellen, välillä päällekkäin, ja jokaisen
   mikissä muiden puhujien vuoto (viive 5–9 ms, −18 dB, lyhyt huonevaste);
   stereomusiikkipohja osissa häivytyksineen. Siemen on kiinteä, joten
   sama komento tuottaa saman kansion — ja saman miksauksen.
2. **Ajaa miksauksen** ja mittaa seinäkelloajan vaiheittain: lataus,
   ruudukko, lohkotaso, jokaisen raidan vaiheet (read, debleed, cleanup,
   measure, dynamics, lag, duck, write) sekä niiden sisäiset askeleet
   (``speechmix.log``), puhujien tasaus, pohjien mittaus, masterointi ja
   kirjoitus. Lopuksi RSS-huippu.
3. **Tiivistää tuloksen** SHA-256:ksi: miksattu WAV, ``flags.txt`` ja
   ``beds:``/``mastered:``/``balance:``-rivit. ``--hashes-out`` kirjoittaa ne
   JSONiksi, ``--check`` vertaa aiempaan ja kaatuu jos ne eroavat — jokaisen
   nopeutuksen on toistettava tulos bitilleen.

Käyttö (työtilan juuresta)::

    uv run python scripts/bench_stems_mix.py                  # 10 min × 3 + musiikki
    uv run python scripts/bench_stems_mix.py --minutes 25 --speakers 2
    uv run python scripts/bench_stems_mix.py --keep-music-level
    uv run python scripts/bench_stems_mix.py --hashes-out base.json
    uv run python scripts/bench_stems_mix.py --check base.json
    uv run python scripts/bench_stems_mix.py --profile out.prof   # cProfile

``--profile`` ajaa stemit yksi kerrallaan (``SPEECHMIX_PARALLEL_STEMS=1``),
koska cProfile näkee vain pääsäikeen. ``--parallel N`` pakottaa saman
muuttujan muuten.

Synteettinen ääni ei ole jakso: luvut kertovat vaiheiden suhteet ja sen,
skaalautuvatko ne pituuden mukana, eivät oikean puheen aikaa.
"""

from __future__ import annotations

import argparse
import cProfile
import hashlib
import json
import logging
import os
import pstats
import re
import resource
import shutil
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

RATE = 48000

#: Vuoto toisen puhujan mikkiin: taso ja viive. 1,8 m:n päässä olevat mikit
#: (ks. ``speechmix.debleed``) kuulevat toisensa noin 5–7 ms myöhässä ja
#: ~13 dB hiljempaa; tässä hieman syvemmällä, jotta vähennyksellä on työtä.
BLEED_DB = -18.0
BLEED_DELAY_MS = (5.0, 9.0)
#: Huonevasteen pituus ja taso vuodossa.
ROOM_MS = 40.0
ROOM_DB = -30.0
#: Pohjakohina mikissä.
NOISE_DB = -65.0


def _db(x: float) -> float:
    return 10.0 ** (x / 20.0)


def _turns(rng, seconds: float, speakers: int) -> list[list[tuple[float, float]]]:
    """Puheenvuorot puhujittain ``(alku, loppu)``: vuorotellen, välillä päällekkäin."""
    out: list[list[tuple[float, float]]] = [[] for _ in range(speakers)]
    t = 1.0
    who = 0
    while t < seconds - 1.0:
        length = float(rng.uniform(3.0, 15.0))
        end = min(seconds - 0.5, t + length)
        out[who].append((t, end))
        nxt = int((who + rng.integers(1, speakers)) % speakers) if speakers > 1 else 0
        if speakers > 1 and rng.random() < 0.2:
            # Päällepuhunta: seuraava alkaa ennen kuin edellinen lopettaa.
            t = max(t + 0.5, end - float(rng.uniform(0.3, 1.5)))
        else:
            t = end + float(rng.uniform(0.3, 1.2))
        who = nxt
    return out


def _voice(rng, seconds: float, turns, f0: float, level_db: float) -> np.ndarray:
    """Puheen kaltainen signaali: harmoninen ääni tavurytmissä ja s-äänteitä."""
    from scipy import signal as sp

    n = int(seconds * RATE)
    out = np.zeros(n, dtype=np.float32)
    for a, b in turns:
        i0, i1 = int(a * RATE), int(b * RATE)
        m = i1 - i0
        if m <= 0:
            continue
        t = np.arange(m) / RATE
        # Tavurytmi ~4 Hz satunnaisin painoin, lauseiden välissä tauko.
        syllable = 0.5 + 0.5 * np.sin(2 * np.pi * float(rng.uniform(3.5, 5.0)) * t)
        phrase = (np.sin(2 * np.pi * t / float(rng.uniform(2.0, 4.0))) > -0.6)
        weights = rng.uniform(0.4, 1.0, size=max(1, int((b - a) * 5) + 1))
        weight = np.repeat(weights, int(RATE / 5) + 1)[:m]
        env = (syllable ** 1.5) * phrase * weight
        # Sävelkorkeus liukuu lauseen mukana; harmoniset 1/k.
        pitch = f0 * (1.0 + 0.08 * np.sin(2 * np.pi * 0.7 * t + rng.uniform(0, 6.28)))
        phase = 2 * np.pi * np.cumsum(pitch) / RATE
        tone = np.zeros(m)
        for k in range(1, 12):
            tone += np.sin(k * phase) / k
        # Formanttimainen värittäminen: pari kaistanpäästöä.
        voiced = np.zeros(m)
        for hz, q in ((600.0, 2.0), (1500.0, 3.0), (2600.0, 4.0)):
            sos = sp.butter(2, [hz / (1 + 0.5 / q), hz * (1 + 0.5 / q)],
                            btype="bandpass", fs=RATE, output="sos")
            voiced += sp.sosfilt(sos, tone)
        voiced /= max(1e-9, np.abs(voiced).max())
        # Sihinä: korkeapäästetty kohina osaan tavuista.
        hiss = sp.sosfilt(sp.butter(4, 4500.0, "hp", fs=RATE, output="sos"),
                          rng.normal(0, 1, m))
        hiss /= max(1e-9, np.abs(hiss).max())
        gate = (np.sin(2 * np.pi * 1.3 * t + rng.uniform(0, 6.28)) > 0.85)
        burst = env * (voiced + 0.35 * hiss * gate)
        out[i0:i1] += (burst * _db(level_db)).astype(np.float32)
    return out


def _bleed(rng, source: np.ndarray) -> np.ndarray:
    """Toisen puhujan ääni tässä mikissä: viive, vaimennus ja lyhyt huone."""
    from scipy import signal as sp

    delay = int(RATE * float(rng.uniform(*BLEED_DELAY_MS)) / 1000.0)
    room_n = int(RATE * ROOM_MS / 1000.0)
    room = rng.normal(0, 1, room_n) * np.exp(-np.arange(room_n) / (room_n / 4))
    room *= _db(ROOM_DB) / max(1e-9, np.abs(room).max())
    kernel = np.zeros(delay + room_n)
    kernel[delay] = _db(BLEED_DB)
    kernel[delay:] += room * _db(BLEED_DB)
    return sp.oaconvolve(source.astype(np.float64), kernel)[: source.size].astype(
        np.float32
    )


def _music(rng, seconds: float) -> np.ndarray:
    """Stereopohja osissa: alku, pari pätkää puheen alla, loppu; 2 s häivytykset."""
    n = int(seconds * RATE)
    music = np.zeros((n, 2), dtype=np.float32)
    parts = [(0.0, min(20.0, seconds / 3))]
    if seconds > 90:
        parts.append((seconds * 0.4, seconds * 0.4 + 30.0))
        parts.append((seconds * 0.7, seconds * 0.7 + 30.0))
    parts.append((max(0.0, seconds - 20.0), seconds))
    for a, b in parts:
        i0, i1 = int(a * RATE), min(n, int(b * RATE))
        m = i1 - i0
        if m <= 0:
            continue
        t = np.arange(m) / RATE
        chord = np.zeros(m)
        for hz in (110.0, 165.0, 220.0, 277.0, 330.0):
            chord += np.sin(2 * np.pi * hz * t + rng.uniform(0, 6.28)) / 5
        tremolo = 0.7 + 0.3 * np.sin(2 * np.pi * 0.25 * t)
        beat = (np.sin(2 * np.pi * 2.0 * t) > 0.9) * rng.normal(0, 0.3, m)
        left = chord * tremolo + 0.3 * beat
        right = chord * (1.4 - tremolo) + 0.3 * np.roll(beat, 2000)
        pair = np.stack([left, right], axis=1)
        pair *= _db(-18.0) / max(1e-9, np.abs(pair).max())
        fade = int(min(2.0 * RATE, m // 2))
        ramp = np.linspace(0.0, 1.0, fade)
        pair[:fade] *= ramp[:, None]
        pair[m - fade:] *= ramp[::-1][:, None]
        music[i0:i1] = pair.astype(np.float32)
    return music


#: Kuinka kauan puheenvuoron jälkeen mikki vielä soi, kun hiljaisuus on nollattu.
ZERO_GAP_TAIL_S = 0.3


def make_folder(folder: Path, minutes: float, speakers: int, music: bool,
                seed: int, zero_gaps: bool = False) -> Path:
    """Kuulaksen vientikansio: yksi WAV raitaa kohti ja ``tracks.json``.

    ``zero_gaps``: puhujan oman vuoron ulkopuolella mikki on tarkkaa nollaa,
    kuten kuulaksen vaimennetuissa kohdissa. Ilman sitä hiljaisuudessa on
    pohjakohinaa (ja toisen puhujan vuotoa), ja ``-65 dB`` kohina pitää
    suotimien tilan kaukana denormaaleista: penkki ei näkisi niiden hintaa."""
    import soundfile as sf

    rng = np.random.default_rng(seed)
    seconds = minutes * 60.0
    n = int(seconds * RATE)
    folder.mkdir(parents=True, exist_ok=True)
    turns = _turns(rng, seconds, speakers)
    voices = [
        _voice(rng, seconds, turns[i], 105.0 + 45.0 * i, -20.0 + (i % 3) * 3.0 - 3.0)
        for i in range(speakers)
    ]
    tracks = []
    for i in range(speakers):
        mic = voices[i].copy()
        for j in range(speakers):
            if j != i:
                mic += _bleed(rng, voices[j])
        mic += rng.normal(0, _db(NOISE_DB), n).astype(np.float32)
        if zero_gaps:
            mask = np.zeros(n, dtype=bool)
            for a, b in turns[i]:
                mask[int(a * RATE):int((b + ZERO_GAP_TAIL_S) * RATE)] = True
            mic[~mask] = 0.0
        name = f"Jakso – P{i}.wav"
        sf.write(folder / name, mic, RATE, subtype="PCM_24")
        tracks.append({
            "id": f"t{i}", "name": f"P{i}", "kind": "speech", "speaker": "",
            "channels": 1, "file": name, "audible": True, "gain_db": 0.0,
            "pan": 0.0,
        })
    if music:
        name = "Jakso – musiikit.wav"
        sf.write(folder / name, _music(rng, seconds), RATE, subtype="PCM_24")
        tracks.append({
            "id": "tm", "name": "musiikit", "kind": "music", "speaker": "",
            "channels": 2, "file": name, "audible": True, "gain_db": 0.0,
            "pan": 0.0,
        })
    manifest = {
        "edit": "Jakso", "project": "bench", "version": 1, "rate": RATE,
        "start_frame": 0, "frames": n, "processing": "dry", "format": "wav",
        "bit_depth": 24, "tracks": tracks,
    }
    (folder / "tracks.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return folder


# ----------------------------------------------------------------- mittaus


class Clock:
    """Vaiheiden seinäkelloajat: ylätason vaiheet, raitojen vaiheet ja askeleet."""

    def __init__(self):
        self.t0 = time.perf_counter()
        self.phases: list[tuple[str, float]] = []
        self.track_stages: dict[str, list[tuple[str, float]]] = {}
        self._track_last: dict[str, float] = {}
        self.steps: dict[str, float] = {}
        self.lines: list[str] = []

    def now(self) -> float:
        return time.perf_counter() - self.t0

    def wrap(self, module, name: str, label: str | None = None):
        original = getattr(module, name)
        label = label or name

        def timed(*args, **kwargs):
            started = time.perf_counter()
            try:
                return original(*args, **kwargs)
            finally:
                self.phases.append((label, time.perf_counter() - started))

        setattr(module, name, timed)

    def log_line(self, message: str) -> None:
        """``stems_mix._log``: raidan vaiheet aikaleimoin, muut rivit talteen."""
        self.lines.append(message)
        now = time.perf_counter()
        m = re.match(r"^(.*): processing$", message)
        if m:
            self._track_last[m.group(1)] = now
            self.track_stages.setdefault(m.group(1), [])
            return
        m = re.match(r"^  (.*): (\w+)$", message)
        if m and m.group(1) in self._track_last:
            who, stage = m.group(1), m.group(2)
            self.track_stages[who].append((stage, now - self._track_last[who]))
            self._track_last[who] = now

    def step_record(self, record: logging.LogRecord) -> None:
        m = re.match(r"^(.*) (\d+\.\d)s$", record.getMessage())
        if m:
            self.steps[m.group(1)] = self.steps.get(m.group(1), 0.0) + float(m.group(2))


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as handle:
        for piece in iter(lambda: handle.read(1 << 20), b""):
            h.update(piece)
    return h.hexdigest()


def run(args) -> dict:
    from automixer import stems_mix
    from speechmix import log as smlog
    from speechmix import stems

    clock = Clock()
    # Raitojen vaiheet luetaan lokiriveistä; askeleet speechmixin omasta lokista.
    original_log = stems_mix._log

    def log(message: str) -> None:
        clock.log_line(message)
        if args.verbose:
            original_log(message)

    stems_mix._log = log
    smlog.LOGGER.setLevel(logging.DEBUG)
    handler = logging.Handler()
    handler.emit = clock.step_record
    smlog.LOGGER.addHandler(handler)
    if not args.verbose:
        stems._log = lambda _message: None

    clock.wrap(stems, "grid_from_files", "grid")
    clock.wrap(stems_mix, "review", "review")
    clock.wrap(stems_mix, "level_blocks", "level_blocks")
    clock.wrap(stems, "process_stem", "process_stem")
    clock.wrap(stems_mix, "scale_file", "balance scale_file")
    clock.wrap(stems_mix, "_loudness", "beds _loudness")
    clock.wrap(stems, "program_deliver", "mastering")
    clock.wrap(stems, "sum_to_file", "write mix")
    clock.wrap(stems.envelopes, "duck_envelopes", "duck_envelopes")

    from automixer import stem_folder

    def loader(path, workdir):
        started = time.perf_counter()
        try:
            return stem_folder.load(path, workdir)
        finally:
            clock.phases.append(("load", time.perf_counter() - started))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    options = {"target_lufs": args.target_lufs, "loader": loader}
    if args.keep_music_level:
        options["keep_music_level"] = True
    if args.bed_under_speech_db is not None:
        options["bed_under_speech_db"] = args.bed_under_speech_db

    started = time.perf_counter()
    profiler = cProfile.Profile() if args.profile else None
    if profiler:
        profiler.enable()
    result = stems_mix.mix(str(args.folder), str(out), **options)
    if profiler:
        profiler.disable()
        profiler.dump_stats(args.profile)
    total = time.perf_counter() - started
    smlog.LOGGER.removeHandler(handler)

    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    peak_rss_gb = rss / (1 << 20) if sys.platform != "darwin" else rss / (1 << 30)

    flags = Path(os.path.splitext(str(out))[0] + " flags.txt")
    # The mastered line ends in the output path, which is a fresh temp dir
    # every run; the numbers before it are what must not change.
    tagged = [re.sub(r"→ /.*$", "→ PATH", line) for line in clock.lines
              if line.startswith(("beds:", "mastered:", "balance:"))]
    hashes = {
        "mix.wav": _hash_file(out),
        "flags.txt": _hash_file(flags) if flags.exists() else "",
        "lines": hashlib.sha256("\n".join(tagged).encode("utf-8")).hexdigest(),
    }

    # ---- raportti
    print(f"\n== {args.folder}  ({args.minutes:g} min × {args.speakers} speakers"
          f"{' + music' if args.music else ''})")
    print(f"total {total:.1f} s   peak RSS {peak_rss_gb:.2f} GB")
    print("\nphases (wall, s):")
    for label in dict.fromkeys(label for label, _ in clock.phases):
        values = [v for lb, v in clock.phases if lb == label]
        print(f"  {label:<20} {sum(values):8.2f}  ×{len(values)}")
    print("\nper-track stages (wall, s):")
    for who, stages in clock.track_stages.items():
        row = "  ".join(f"{name} {sec:.1f}" for name, sec in stages)
        print(f"  {who:<10} {row}")
    if clock.steps:
        print("\nchain steps (speechmix.log, summed over tracks, s):")
        for name, sec in sorted(clock.steps.items(), key=lambda kv: -kv[1])[:24]:
            print(f"  {name:<40} {sec:7.1f}")
    print("\nlines:")
    for line in tagged:
        print(f"  {line}")
    print("\nsha256:")
    for key, value in hashes.items():
        print(f"  {key:<10} {value}")
    print(f"\nresult: {result.program_lufs:.2f} LUFS, lift {result.program_boost:+.2f}, "
          f"limit {result.program_limit_cost:.2f} LU")

    if profiler:
        stats = pstats.Stats(args.profile)
        for key in ("cumulative", "tottime"):
            print(f"\ncProfile top 25 by {key}:")
            stats.sort_stats(key).print_stats(25)

    return {"hashes": hashes, "total_s": total, "peak_rss_gb": peak_rss_gb,
            "phases": clock.phases, "track_stages": clock.track_stages,
            "steps": clock.steps, "lines": tagged}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--minutes", type=float, default=10.0)
    parser.add_argument("--speakers", type=int, default=3)
    parser.add_argument("--no-music", dest="music", action="store_false")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--zero-gaps", action="store_true",
                        help="hiljaisuus tarkkaa nollaa puhujan vuorojen ulkopuolella")
    parser.add_argument("--target-lufs", type=float, default=-16.0)
    parser.add_argument("--keep-music-level", action="store_true")
    parser.add_argument("--bed-under-speech-db", type=float, default=None)
    parser.add_argument("--folder", default=None,
                        help="käytä tätä kansiota (luodaan jos puuttuu)")
    parser.add_argument("--out", default=None, help="miksauksen polku")
    parser.add_argument("--keep", action="store_true",
                        help="jätä kansio ja miksaus levylle")
    parser.add_argument("--parallel", type=int, default=None,
                        help="SPEECHMIX_PARALLEL_STEMS")
    parser.add_argument("--profile", default=None, help="cProfile-tiedosto")
    parser.add_argument("--hashes-out", default=None)
    parser.add_argument("--check", default=None,
                        help="vertaa SHA-256:ia tähän JSONiin; eri → virhe")
    parser.add_argument("--verbose", action="store_true",
                        help="näytä miksauksen oma loki")
    args = parser.parse_args(argv)

    if args.profile and args.parallel is None:
        args.parallel = 1
    if args.parallel is not None:
        os.environ["SPEECHMIX_PARALLEL_STEMS"] = str(args.parallel)

    base = Path(tempfile.mkdtemp(prefix="bench-stems-")) if args.folder is None else None
    folder = Path(args.folder) if args.folder else base / "stems"
    if not (folder / "tracks.json").exists():
        started = time.perf_counter()
        make_folder(folder, args.minutes, args.speakers, args.music, args.seed,
                    args.zero_gaps)
        print(f"generated {folder} in {time.perf_counter() - started:.1f} s")
    else:
        print(f"using {folder}")
    args.folder = folder
    args.out = args.out or str((base or folder.parent) / "mix" / "Jakso automixer.wav")

    try:
        report = run(args)
    finally:
        if base is not None and not args.keep:
            shutil.rmtree(base, ignore_errors=True)

    if args.hashes_out:
        Path(args.hashes_out).write_text(json.dumps(report["hashes"], indent=1))
        print(f"hashes → {args.hashes_out}")
    if args.check:
        expected = json.loads(Path(args.check).read_text())
        bad = {k: (v, report["hashes"].get(k)) for k, v in expected.items()
               if report["hashes"].get(k) != v}
        if bad:
            print(f"MISMATCH against {args.check}: {bad}")
            return 1
        print(f"bit-identical to {args.check}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
