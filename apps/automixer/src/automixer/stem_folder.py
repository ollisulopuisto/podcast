"""Kansio stemejä ja ``tracks.json``: kuulaksen vienti automixerin raitoina.

kuulas vie jokaisen raidan omaksi WAViksi ja kirjoittaa viereen luettelon.
Tämä lukee luettelon ja antaa raidat samassa muodossa kuin ``session.load``
antaa Hindenburgin istunnosta, joten ``stems_mix.mix`` ajaa kumpaakin samalla
putkella levyltä. Aiemmin kansio meni ``Mixer``ille, joka pitää koko jakson
muistissa; 47 minuutin jakso ei mahtunut 32 GB:n koneeseen.

Luettelo luetaan, ei arvata: raidan rooli on sen ``kind``, ei nimen osa.
Mikään tässä ei korjaa luetteloa hiljaa. Jos jokin ei täsmää (versio,
näytetaajuus, kehysten määrä, kanavat, puuttuva tiedosto), kieltäydytään ja
sanotaan mikä raita ja mikä kenttä.

``gain_db`` on raidan fader. Se jätetään pois kuten istunnossakin
(``session.load``: ``clip.gain / clip.track_gain``): puhe tasataan joka
tapauksessa ja musiikki sovitetaan puheeseen, joten faderi ei kerro mitään
mitä miksaus ei päättäisi itse. ``pan`` jätetään pois samasta syystä:
puhujat levitetään automaattisesti.
"""

from __future__ import annotations

import json
from pathlib import Path

import soundfile as sf

from speechmix.stems import StemError

from .session import Loaded

MANIFEST = "tracks.json"

#: Ainoa tuettu luettelon versio.
VERSION = 1

#: Näytetaajuus, jolla miksaus toimii (``session.load``: ``rate=48000``).
RATE = 48000

KINDS = ("speech", "music")


def manifest_path(path: str | Path) -> Path | None:
    """``tracks.json`` kansiosta tai itse tiedosto; ``None`` jos kumpikaan."""
    p = Path(path)
    if p.is_dir() and (p / MANIFEST).is_file():
        return p / MANIFEST
    if p.is_file() and p.name == MANIFEST:
        return p
    return None


def _read(manifest: Path) -> dict:
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise StemError(f"{manifest}: cannot be read as JSON ({exc})") from exc
    if not isinstance(data, dict):
        raise StemError(f'{manifest}: expected an object with a "tracks" list')
    return data


def edit_name(path: str | Path) -> str:
    """Muokkauksen nimi tulostiedoston nimeä varten; kansion nimi jos puuttuu."""
    manifest = manifest_path(path)
    name = ""
    if manifest is not None:
        try:
            name = str(_read(manifest).get("edit") or "")
        except StemError:
            name = ""
        if not name:
            name = manifest.parent.name
    return name or "automixer"


def default_output(path: str | Path) -> str:
    manifest = manifest_path(path)
    folder = manifest.parent if manifest is not None else Path(path)
    return str(folder / f"{edit_name(path)} automixer.wav")


def load(path, _workdir=None, rate: int = RATE) -> Loaded:
    """Luettelon raidat ``Loaded``ina; työhakemisto (``_workdir``) on tässä käyttämättä.

    Stemit ovat jo aikajanan mittaisia ja alkavat nollasta (kuulas vie ne
    niin), joten mitään ei kirjoiteta uudelleen.
    """
    manifest = manifest_path(path)
    if manifest is None:
        raise StemError(f"{path}: no {MANIFEST} here")
    data = _read(manifest)

    if data.get("version") != VERSION:
        raise StemError(
            f"{manifest}: version {data.get('version')!r}, only version {VERSION} is supported"
        )
    if data.get("rate") != rate:
        raise StemError(
            f"{manifest}: rate {data.get('rate')!r}, the mix works at {rate} Hz"
        )
    if data.get("start_frame", 0) != 0:
        raise StemError(
            f"{manifest}: start_frame {data.get('start_frame')!r}, stems must start at 0"
        )
    if data.get("processing") != "dry":
        raise StemError(
            f"{manifest}: processing {data.get('processing')!r}, the mix needs "
            '"dry" stems (it measures the raw microphones)'
        )
    frames = data.get("frames")
    if not isinstance(frames, int) or frames <= 0:
        raise StemError(f'{manifest}: "frames" must be a positive integer')
    entries = data.get("tracks")
    if not isinstance(entries, list) or not entries:
        raise StemError(f'{manifest}: no "tracks"')

    loaded = Loaded(duration=frames / rate)
    seen: set[str] = set()
    for number, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise StemError(f"{manifest}: track {number} is not an object")
        for field in ("name", "kind", "file"):
            if not isinstance(entry.get(field), str) or not entry[field]:
                raise StemError(f'{manifest}: track {number} has no "{field}"')
        name, kind = entry["name"], entry["kind"]
        if name in seen:
            raise StemError(f'{manifest}: two tracks are named "{name}"')
        seen.add(name)
        if kind == "speech-mix":
            raise StemError(
                f'{name}: kind "speech-mix" is a bus of several speakers in one file; '
                "the speech chain needs one microphone per track (who speaks is decided "
                'by comparing microphones). Export the speakers as separate "speech" '
                "tracks, or leave the bus out."
            )
        if kind not in KINDS:
            raise StemError(f'{name}: kind "{kind}" is not one of {", ".join(KINDS)}')
        if entry.get("audible", True) is False:
            loaded.notes.append(f"{name}: not audible, left out")
            continue

        audio = manifest.parent / entry["file"]
        if not audio.is_file():
            raise StemError(f"{name}: {entry['file']} not found beside {MANIFEST}")
        try:
            info = sf.info(str(audio))
        except (OSError, RuntimeError) as exc:
            raise StemError(f"{name}: {entry['file']} cannot be read ({exc})") from exc
        if info.samplerate != rate:
            raise StemError(
                f"{name}: {entry['file']} is {info.samplerate} Hz, the mix works at {rate}"
            )
        if info.frames != frames:
            raise StemError(f"{name}: {info.frames} frames, the manifest says {frames}")
        if "channels" in entry and info.channels != entry["channels"]:
            raise StemError(
                f"{name}: the file has {info.channels} channels, "
                f"the manifest says {entry['channels']}"
            )
        if kind == "music" and info.channels != 2:
            raise StemError(
                f"{name}: a music stem must be stereo, the file has {info.channels} channel(s)"
            )
        gain = entry.get("gain_db") or 0.0
        if gain:
            loaded.notes.append(
                f"{name}: gain_db {gain:+.1f} is the track fader and is not applied "
                "(as in a session)"
            )
        loaded.tracks.append({"name": name, "path": str(audio), "type": kind})

    if not loaded.tracks:
        raise StemError(f"{manifest}: no audible tracks")
    return loaded
