"""Sävymittari (suunnitelman osa C, tehtävä C0): onko sävyn tasaamisessa mitään tasattavaa.

    uv run --package speechmix python scripts/ab/tone_measure.py raidat.json

``raidat.json`` on lista ``{"episode": "s13e03", "speaker": "Olli",
"file": "polku.wav"}``. Sama puhuja kannattaa antaa useammasta jaksosta ja
jaksossa useampi puhuja, koska mittari vertaa kahta asiaa:

* **puhujien välinen hajonta** jaksossa, kaistoittain, ja
* **saman puhujan hajonta jaksosta toiseen**, kaistoittain.

Päätössäännöt on kirjoitettu ennen lukuja
(``docs/plans/2026-10-16-voice-presets.md``, C0) ja ``verdicts`` toteuttaa ne:
alle ``WORTH_DB`` ei kannata korjata; jos sama puhuja heiluu enemmän kuin
puhujat eroavat, ominaisuus on show-kohtainen profiili; muuten yhteinen
tavoitekäyrä. Sääntö on yksi tarkennus suunnitelmaan: 2 dB:n raja koskee
suurempaa kahdesta hajonnasta, koska kaista jossa puhujat ovat samanlaisia
mutta sama puhuja heiluu kolme desibeliä jaksosta toiseen on silti
korjaamisen arvoinen.

Mittaus on suhteellinen. Jokaisen kaistan taso on dB:nä suhteessa saman raidan
500–2000 Hz:n tasoon, joten äänenvoimakkuus ei vaikuta (se on jo tasattu
muualla) eikä sävyn mittaus voi sekoittua siihen. Spektri lasketaan **vain
puhekehyksistä**, ja kaista jonka puhe ei nouse ``MIN_CLEARANCE_DB`` kohinan
yläpuolelle on *mittaamaton* (``None``), ei nolla: kohinaista kaistaa ei saa
raportoida eikä myöhemmin nostaa (sama oppi kuin phone-presetissä).

Mittarin testit ajetaan tunnetuilla synteettisillä raidoilla
(``tests/test_tone_measure.py``). Oikeat jaksot kuuluvat vain tähän ajoon.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

#: Kaistat, joilla sävyä mitataan: leveitä, ei kapeita. Matala pää, runko
#: (läheisyysvaikutus), läsnäolo ja ilma. Rajat ovat suunnitelmasta.
BANDS: dict[str, tuple[float, float]] = {
    "low": (60.0, 150.0),
    "body": (150.0, 400.0),
    "presence": (2000.0, 5000.0),
    "air": (8000.0, 15000.0),
}

#: Vertailukaista, johon muut suhteutetaan. Puheen vakaa keskialue.
ANCHOR = (500.0, 2000.0)

#: Kuinka monta dB:n verran puheen pitää nousta kohinan yläpuolelle kaistalla,
#: jotta se mitataan. 10 dB: kohinan osuus kaistan tehosta on alle 10 %, joten
#: se vääristää tason alle 0,5 dB.
MIN_CLEARANCE_DB = 10.0

#: Alle tämän kokoinen puheaineisto ei kerro mitään: sekunti ja 50 kehystä.
MIN_SPEECH_FRAMES = 50

#: Kaista on korjaamisen arvoinen vasta tästä hajonnasta ylöspäin, dB.
WORTH_DB = 2.0

FRAME_SEC = 0.040
HOP_SEC = 0.020


def _mono(audio: np.ndarray) -> np.ndarray:
    audio = np.asarray(audio, dtype=np.float64)
    return audio[0] if audio.ndim == 2 else audio


def _frames(x: np.ndarray, size: int, hop: int) -> np.ndarray:
    count = 1 + (x.size - size) // hop
    if count <= 0:
        return np.zeros((0, size))
    index = np.arange(size)[None, :] + hop * np.arange(count)[:, None]
    return x[index]


def _level_curve(x: np.ndarray, rate: int) -> np.ndarray:
    """Kehyskohtainen taso dB:nä, sama kehys ja hyppy kuin ``speechmix.grid``issa."""
    size, hop = int(FRAME_SEC * rate), int(HOP_SEC * rate)
    frames = _frames(x, size, hop)
    rms = np.sqrt(np.mean(frames**2, axis=1))
    return 20.0 * np.log10(np.maximum(rms, 1e-9))


def speech_mask(audio: np.ndarray, rate: int) -> np.ndarray:
    """Puhekehykset: tason pitää nousta raidan omasta kohinalattiasta.

    Sama sääntö kuin gridissä (``grid.noise_floor`` ja ``FLOOR_MARGIN_DB``),
    ei omaa: sävymittarin puhe on sama puhe kuin muun ketjun.
    """
    from speechmix import grid

    db = grid.smooth(_level_curve(_mono(audio), rate))
    floor = grid.noise_floor(db)
    return db > floor + grid.FLOOR_MARGIN_DB


def band_levels(audio: np.ndarray, rate: int) -> dict[str, float | None]:
    """Kaistojen taso dB:nä suhteessa ``ANCHOR``-kaistaan, tai ``None``.

    Spektri on puhekehysten keskiarvo (Hann-ikkuna). Kohina on hiljaisimpien
    kehysten spektri: kaista mitataan vain jos puhe on siellä vähintään
    ``MIN_CLEARANCE_DB`` sen yläpuolella.
    """
    from speechmix import grid

    x = _mono(audio)
    size, hop = int(FRAME_SEC * rate), int(HOP_SEC * rate)
    frames = _frames(x, size, hop)
    none = dict.fromkeys(BANDS)
    if len(frames) < MIN_SPEECH_FRAMES:
        return none

    db = _level_curve(x, rate)
    smoothed = grid.smooth(db)
    floor = grid.noise_floor(smoothed)
    speech = smoothed > floor + grid.FLOOR_MARGIN_DB
    if int(speech.sum()) < MIN_SPEECH_FRAMES:
        return none
    quiet = smoothed <= floor + 3.0
    if not quiet.any():
        quiet = smoothed <= np.percentile(smoothed, 5.0)

    power = np.abs(np.fft.rfft(frames * np.hanning(size)[None, :], axis=1)) ** 2
    freqs = np.fft.rfftfreq(size, 1.0 / rate)
    speech_psd = power[speech].mean(axis=0)
    noise_psd = power[quiet].mean(axis=0)
    nyquist = 0.95 * rate / 2.0

    def band(lo: float, hi: float):
        hi = min(hi, nyquist)
        selected = (freqs >= lo) & (freqs < hi)
        if hi <= lo or not selected.any():
            return None
        s, n = speech_psd[selected].mean(), noise_psd[selected].mean()
        if s <= 0 or 10.0 * np.log10(s / max(n, 1e-30)) < MIN_CLEARANCE_DB:
            return None
        return 10.0 * np.log10(s)

    anchor = band(*ANCHOR)
    if anchor is None:
        return none
    out: dict[str, float | None] = {}
    for name, (lo, hi) in BANDS.items():
        level = band(lo, hi)
        out[name] = None if level is None else float(level - anchor)
    return out


def _spread(values: list) -> float | None:
    measured = [v for v in values if v is not None]
    return float(max(measured) - min(measured)) if len(measured) >= 2 else None


def _mean(values: list) -> float | None:
    measured = [v for v in values if v is not None]
    return float(np.mean(measured)) if measured else None


def between_speakers(episodes: dict) -> dict[str, float | None]:
    """Puhujien välinen hajonta jaksossa (max − min), kaistoittain, jaksojen keskiarvo.

    ``episodes`` on ``{jakso: {puhuja: {kaista: taso | None}}}``. Mittaamaton
    ohitetaan; kaista jolla ei missään jaksossa ole kahta mitattua on ``None``.
    """
    out: dict[str, float | None] = {}
    for name in BANDS:
        per_episode = [
            _spread([levels[name] for levels in speakers.values()])
            for speakers in episodes.values()
        ]
        out[name] = _mean(per_episode)
    return out


def same_speaker(episodes: dict) -> dict[str, float | None]:
    """Saman puhujan hajonta jaksosta toiseen, kaistoittain, puhujien keskiarvo."""
    by_speaker: dict[str, list[dict]] = {}
    for speakers in episodes.values():
        for speaker, levels in speakers.items():
            by_speaker.setdefault(speaker, []).append(levels)
    out: dict[str, float | None] = {}
    for name in BANDS:
        per_speaker = [_spread([lv[name] for lv in runs]) for runs in by_speaker.values()]
        out[name] = _mean(per_speaker)
    return out


def verdicts(between: dict, same: dict) -> dict[str, str]:
    """Suunnitelman päätössäännöt, kaistoittain. Kirjoitettu ennen lukuja."""
    out: dict[str, str] = {}
    for name in BANDS:
        b, s = between.get(name), same.get(name)
        if b is None or s is None:
            out[name] = "not enough data"
        elif max(b, s) < WORTH_DB:
            out[name] = (
                f"skip: speakers differ {b:.1f} dB and one speaker {s:.1f} dB, "
                f"under {WORTH_DB:g} dB"
            )
        elif s > b:
            out[name] = (
                f"per-show profile: the same speaker varies {s:.1f} dB across "
                f"episodes, more than speakers differ ({b:.1f} dB)"
            )
        else:
            out[name] = "correct toward a common target"
    return out


def _cell(value: float | None) -> str:
    return "unmeasured" if value is None else f"{value:+.1f} dB"


def report(manifest: Path) -> str:
    import soundfile as sf

    tracks = json.loads(Path(manifest).read_text(encoding="utf-8"))
    episodes: dict[str, dict[str, dict]] = {}
    for track in tracks:
        audio, rate = sf.read(track["file"], dtype="float32", always_2d=True)
        levels = band_levels(audio.T, rate)
        episodes.setdefault(track["episode"], {})[track["speaker"]] = levels

    lines = ["## Tone per track (dB relative to 500-2000 Hz)", ""]
    lines += ["| episode | speaker | " + " | ".join(BANDS) + " |"]
    lines += ["|---|---|" + "---|" * len(BANDS)]
    for episode, speakers in episodes.items():
        for speaker, levels in speakers.items():
            lines.append(
                f"| {episode} | {speaker} | "
                + " | ".join(_cell(levels[b]) for b in BANDS)
                + " |"
            )

    between, same = between_speakers(episodes), same_speaker(episodes)
    lines += ["", "## Spread (max - min, mean over episodes or speakers)", ""]
    lines += ["| band | between speakers | same speaker across episodes | verdict |"]
    lines += ["|---|---|---|---|"]
    decided = verdicts(between, same)
    for name in BANDS:
        b = "n/a" if between[name] is None else f"{between[name]:.1f} dB"
        s = "n/a" if same[name] is None else f"{same[name]:.1f} dB"
        lines.append(f"| {name} | {b} | {s} | {decided[name]} |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("manifest", help="JSON: lista {episode, speaker, file}")
    args = parser.parse_args(argv)
    print(report(Path(args.manifest)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
