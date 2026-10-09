"""Koko istunnon miksauksen litterointi ilman puhujia.

Raitojen litterointi antaa jokaiselle sanalle puhujan, mutta kahden mikin
päällekkäisestä puheesta syntyy silloin kaksi rinnakkaista tekstiä. Miksaus
litteroidaan kerran kokonaisena, jolloin teksti on se mitä kuunteluun tuleva
yleisö kuulee. Tulos kirjoitetaan omaan tiedostoonsa istunnon viereen eikä
istuntoon, joten raitojen litteroinnit eivät muutu.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .. import audio as audio_io
from .. import nhsx
from ..jobs import Progress
from ..nhsx import mix, render
from ..nhsx.write import next_free_path, paragraphs
from .backends import resolve
from .options import Options


def _stamp(seconds: float) -> str:
    """``[MM:SS]``. Sekunnit katkaistaan, ei pyöristetä: sana alkaa 2,2 s kohdalla
    kappaleen ``[00:02]``-kohdassa, ei ``[00:03]``-kohdassa."""
    total = int(seconds)
    return f"[{total // 60:02d}:{total % 60:02d}]"


def paragraph_lines(words) -> str:
    """Sanat kappaleiksi tauoista, yksi ``[MM:SS] teksti`` -rivi per kappale.

    Kappaleet erotetaan tyhjällä rivillä. Tyhjä lista antaa tyhjän tekstin,
    jotta tyhjä tulos ei kirjoita tiedostoon turhaa rivinvaihtoa.
    """
    groups = paragraphs(list(words))
    lines = [
        f"{_stamp(group[0].start)} " + " ".join(w.text.strip() for w in group)
        for group in groups
    ]
    if not lines:
        return ""
    return "\n\n".join(lines) + "\n"


def gain_mix(mixdown, sample_rate: int = audio_io.SAMPLE_RATE) -> np.ndarray:
    """Miksaus monona: jokaisen leikkeen näytteet kerrottuna sen gainilla ja summattuna.

    Ei häivytyksiä, ei ramppeja, ei EQ:ta eikä panorointia. Whisper ottaa
    monon, joten pan kumoutuisi kanavien keskiarvossa: se ei tuo mitään tähän.
    Leike puretaan kerran kokonaisena, ei lohkoittain, joten render ei maksa
    muuta kuin purkamisen.
    """
    total = int(round(mixdown.duration * sample_rate))
    out = np.zeros(total, dtype=np.float32)
    for clip in mixdown.clips:
        first = int(round(clip.start * sample_rate))
        count = int(round(clip.length * sample_rate))
        if count <= 0 or first >= total:
            continue
        samples = np.asarray(
            render.decode_slice(clip.path, clip.file_offset, clip.length, sample_rate),
            dtype=np.float32,
        )
        mono = samples.reshape(samples.shape[0], -1).mean(axis=1)
        # Lyhyt lähde täytetään hiljaisuudella, kuten render.py tekee.
        mono = mono[:count]
        mono = np.concatenate([mono, np.zeros(count - mono.shape[0], np.float32)])
        end = min(total, first + count)
        out[first:end] += mono[: end - first] * np.float32(clip.gain)
    return out


def run(
    session_path: str,
    options: Options,
    progress: Progress,
    audio_dir: str = "",
) -> dict:
    """Kokoaa miksauksen monoksi, litteroi sen ja kirjoittaa tekstin.

    Ei renderöi WAV:ia: gain-summaus riittää ASR:lle, ja väliaikaisen tiedoston
    kirjoitus olisi ollut koko jakson kokoinen turha välivaihe.
    """
    session = nhsx.read(session_path)
    planned = mix.plan(session, audio_dir)
    if planned.missing:
        names = ", ".join(str(name) for name in planned.missing)
        raise RuntimeError(
            f"Miksaukseen tarvittavia äänitiedostoja ei löydy levyltä: {names}. "
            "Anna äänipoolin hakemisto."
        )

    backend = resolve(options.backend)
    info = backend.info()
    progress.log(f"Moottori: {info.label} — {info.device}")
    progress.log(f"Miksaus: {planned.duration / 60:.1f} min")

    progress.log("Kootaan miksaus gaineilla…")
    samples = gain_mix(planned)

    progress.log("Litteroidaan miksaus…")
    result = backend.transcribe(samples, options, progress)
    if not result.words:
        # Sama varoitus kuin raidoille: tyhjä teksti voisi näyttää onnistumiselta.
        progress.log(
            "  VAROITUS: miksauksessa ei tunnistettu yhtään sanaa. "
            "Onko siinä puhetta, ja onko kieli oikein? Tiedostoa ei kirjoitettu."
        )
        return {"written": "", "files": 0, "words": 0}

    source = Path(session_path)
    target = next_free_path(source.with_name(f"{source.stem} downmix.md"))
    target.write_text(paragraph_lines(result.words), encoding="utf-8")
    progress.log(f"Kirjoitettiin {target.name} — {len(result.words)} sanaa.")
    return {"written": str(target), "files": 1, "words": len(result.words)}
