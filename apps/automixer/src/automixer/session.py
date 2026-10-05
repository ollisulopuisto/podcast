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
from scipy.ndimage import minimum_filter1d

from nhsx import read
from nhsx.mix import envelope, plan

#: Puheraitojen viitetaso, jolle ketju normalisoi ennen masterointia. Sama
#: luku kuin `cli_mix`in `SPEECH_REFERENCE_LUFS`; musiikki sovitetaan
#: siihen, jotta tunnari ja puhe ovat samalla tasolla ennen masterointia.
MUSIC_LUFS = -23.0

#: Häivytetyn musiikkipohjan tasanne puheen viitetason **yläpuolella**, dB.
#: vst s13e03: käyttäjän käsin tekemät tasanteet olivat INTRO +8,2, MID +7,1
#: ja END +7,0 dB puheen mediaanin yläpuolella (tasanne raidan faderin kanssa
#: −26,2…−25,1 LUFS, puhe faderin kanssa −33,3 LUFS). Koko raakapohjan
#: sovitus puheen tasoon pani tasanteen kuunnellussa renderissä 10,9 dB
#: *alle* puheen (−26,9 vs −16,0 LUFS), eli noin 18 dB väärään suuntaan.
MUSIC_PLATEAU_OVER_SPEECH_DB = 7.0

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

    Stereoarvaus on viimeinen keino: jos alue sanoo ``IsMusic="False"``,
    raita on puhetta vaikka mikki olisi tallennettu stereona (vst s13e03,
    Olli). Muuten se ohitti puheketjun ja sai musiikin tason.
    """
    flags = [(r.elem.get("IsMusic") or "").lower() for r in track.regions
             if r.elem is not None]
    if "true" in flags:
        return True
    if any(word in track.name.upper() for word in MUSIC_WORDS):
        return True
    if "false" in flags:
        return False
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


#: Tasanne = hetket joilla häivytyskäyrä on enintään tämän verran (dB) oman
#: huippunsa alapuolella. Sama 1 dB kuin tasanteen mittauksessa (vst s13e03).
PLATEAU_WINDOW_DB = 1.0
#: pyloudnormin lyhin mitattava pätkä on yksi 400 ms lohko.
_MIN_PLATEAU_S = 0.4


def _music_scale(audio: np.ndarray, env: np.ndarray, rate: int, meter) -> float:
    """Kerroin joka vie musiikkialueen sen viitetasolle.

    Häivytetty pohja (``automixer-beds`` tai käsin tehty) sovitetaan
    **tasanteestaan**: tasanne on ``MUSIC_LUFS + MUSIC_PLATEAU_OVER_SPEECH_DB``.
    Koko raakapohjan sovitus ei kelpaa, koska häivytys vie pohjan puheen
    alle ja tasanteen taso riippuisi siitä kuinka paljon pohjassa on hiljaista
    tai matalaa. Häivyttämätön pohja sovitetaan kokonaan puheen tasoon.
    """
    window = int(_MIN_PLATEAU_S * rate)
    if len(env) > window:
        # Vain pitkään kestänyt taso lasketaan huipuksi: automixer-beds kirjoittaa
        # alun 10 ms:n luiskan, ja ennen sitä käyrä on 1,0, joka ei ole tasanne.
        peak = float(minimum_filter1d(env, size=window).max())
        band = 10 ** (PLATEAU_WINDOW_DB / 20)
        if peak > 0.0 and float(env.min()) < peak / band:
            mask = (env >= peak / band) & (env <= peak * band)
            if mask.sum() >= window:
                heard = audio[mask] * env[mask, None]
                level = meter.integrated_loudness(heard)
                if np.isfinite(level):
                    target = MUSIC_LUFS + MUSIC_PLATEAU_OVER_SPEECH_DB
                    return 10 ** ((target - level) / 20)
    level = meter.integrated_loudness(audio) if len(audio) >= rate else None
    if level is not None and np.isfinite(level):
        return 10 ** ((MUSIC_LUFS - level) / 20)
    return 1.0


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
            env = envelope(len(audio) / rate, rate, clip.ramps, clip.fade_in,
                           clip.fade_out)[: len(audio)]
            if music:
                audio = audio if audio.shape[1] == 2 else np.repeat(audio[:, :1], 2, axis=1)
                audio = audio * np.float32(_music_scale(audio, env, rate, meter))
                gain = 1.0
            else:
                audio = audio.mean(axis=1, keepdims=True)
                # Alueen oma taso ilman raidan faderia.
                gain = clip.gain / clip.track_gain if clip.track_gain else clip.gain
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
