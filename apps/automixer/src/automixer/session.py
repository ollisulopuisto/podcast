"""Hindenburgin istunto automixerin syötteeksi.

Editointi tehdään Hindenburgissa, miksaus täällä. Istunnosta otetaan se
mikä on editointia — leikkaukset, häivytykset ja alueiden keskinäinen taso
(``ClipGain``: yksittäisen huipun laskeminen on editointia) — ja jätetään
se mikä on miksausta: raidan fader ja panorointi. Ketju normalisoi jokaisen
puheraidan ja masteroi summan itse, joten fader olisi vain lähtötaso jonka
normalisointi pyyhkii — paitsi silloin kun se ei pyyhi, ja juuri sitä ei
haluta arvailla.

Musiikin häivytykset ovat tiedostossa tai istunnossa valmiina, joten ne
otetaan. Taso ei: jokainen musiikkialue mitataan ja sovitetaan puheen
tasoon (``MUSIC_LUFS``), koska istunnon fader on asetettu Hindenburgin
omaa, eri tasoista miksausta varten.

Aluesijoittelu tulee jaetusta ``nhsx``-paketista, sama joka soittaa
istunnon podcast-magicissa. Tästä syntyy yksi WAV raitaa kohden
ohjelma-aikajanalle, ja miksaus jatkuu niistä niin kuin mistä tahansa
raidoista.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pyloudnorm as pyln
import soundfile as sf

from nhsx import read
from nhsx.mix import envelope, plan

#: Puheraitojen viitetaso, jolle ketju normalisoi ennen masterointia. Sama
#: luku kuin `cli_mix`in `SPEECH_REFERENCE_LUFS`; musiikki sovitetaan
#: siihen, jotta tunnari ja puhe ovat samalla tasolla ennen masterointia.
MUSIC_LUFS = -23.0

#: Musiikkiraidan tunnistavat nimet, samat kuin tiedostonimien arvauksessa.
MUSIC_WORDS = ("MUSIC", "THEME", "TUNNARI", "MUSA", "MUSIIKKI", "TUNNUS", "JINGLE")


@dataclass
class Loaded:
    """Istunto raitoina: automixerin raitakonfiguraatio ja huomiot."""

    tracks: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    duration: float = 0.0


def _is_music(track, session) -> bool:
    """Musiikkiraita: Hindenburgin oma lippu, nimi tai pelkät stereolähteet.

    Puheraidan alueilla lippu on ``IsMusic="False"``, musiikkiraidalla sitä
    ei aina ole lainkaan (pikis 2026-09-11), joten lippu yksin ei riitä.
    Mikki on monolähde; raita jonka jokainen lähde on stereo on musiikkia.
    """
    flags = [(r.elem.get("IsMusic") or "").lower() for r in track.regions
             if r.elem is not None]
    if "true" in flags:
        return True
    if any(word in track.name.upper() for word in MUSIC_WORDS):
        return True
    channels = []
    for region in track.regions:
        info = session.file_by_id(region.ref)
        if info is not None and info.elem is not None:
            channels.append(info.elem.get("Channels") or "1")
    return bool(channels) and all(c == "2" for c in channels)


def _slice(path: str, offset: float, length: float, rate: int) -> np.ndarray:
    """Alueen ääni lähteestä, ``(näytteet, kanavat)``."""
    with sf.SoundFile(path) as handle:
        if handle.samplerate != rate:
            raise ValueError(
                f"{os.path.basename(path)} on {handle.samplerate} Hz, istunto {rate}"
            )
        handle.seek(max(0, int(round(offset * rate))))
        return handle.read(int(round(length * rate)), dtype="float32",
                           always_2d=True)


def load(path, workdir, rate: int = 48000) -> Loaded:
    """Kokoaa istunnon raidat WAVeiksi ``workdir``iin ohjelma-aikajanalle."""
    session = read(path)
    mixdown = plan(session)
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    loaded = Loaded(duration=mixdown.duration)
    if mixdown.missing:
        loaded.notes.append("puuttuu: " + ", ".join(mixdown.missing))
    n = int(round(mixdown.duration * rate))
    meter = pyln.Meter(rate)

    for number, track in enumerate(session.tracks):
        clips = [c for c in mixdown.clips if c.speaker == track.name]
        if not clips:
            continue
        music = _is_music(track, session)
        out = np.zeros((n, 2 if music else 1), dtype=np.float32)
        for clip in clips:
            try:
                audio = _slice(clip.path, clip.file_offset, clip.length, rate)
            except (OSError, ValueError, RuntimeError) as exc:
                loaded.notes.append(f"{track.name}: {exc}")
                continue
            if music:
                audio = audio if audio.shape[1] == 2 else np.repeat(audio[:, :1], 2, axis=1)
                level = meter.integrated_loudness(audio) if len(audio) >= rate else None
                if level is not None and np.isfinite(level):
                    audio = audio * np.float32(10 ** ((MUSIC_LUFS - level) / 20))
                gain = 1.0
            else:
                audio = audio.mean(axis=1, keepdims=True)
                # Alueen oma taso ilman raidan faderia.
                gain = clip.gain / clip.track_gain if clip.track_gain else clip.gain
            env = envelope(len(audio) / rate, rate, clip.ramps, clip.fade_in,
                           clip.fade_out)[: len(audio)]
            start = int(round(clip.start * rate))
            end = min(n, start + len(audio))
            out[start:end] += audio[: end - start] * (env[: end - start, None] * gain)
        target = workdir / f"{number:02d} {track.name}.wav"
        sf.write(target, out if music else out[:, 0], rate, subtype="FLOAT")
        loaded.tracks.append({
            "name": track.name,
            "path": str(target),
            "type": "music" if music else "speech",
        })
    return loaded
