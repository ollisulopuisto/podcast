"""Musiikkipohjien häivytykset Hindenburgin istuntoon.

    automixer-beds "jakso.nhsx"

Käyttäjä asettaa pohjat musiikkiraidalle; tämä kirjoittaa niille nousun,
tasanteen ja laskun puheen mukaan (``nhsx.musicbed``, mitattu käyttäjän
omista häivytyksistä) ja tallentaa **uuden** istunnon alkuperäisen viereen.
Hindenburgissa sitä voi hienosäätää kuten käsin tehtyä, ja automixer
miksaa sen sellaisenaan.

Käyrä kirjoitetaan lyhyinä `<Fade>`-luiskina (``nhsx.fades``), koska
käyttäjän häivytysmuoto ei ole Hindenburgin raised-cosine.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import soundfile as sf

from nhsx import activity, fades, musicbed, read
from nhsx.read import locate
from speechmix.meter import Meter

from .session import _is_music

#: Tasanteen voimakkuus. vst s13e03:n pohjat häivyttämättöminä ja käyttäjän
#: tasanteen vahvistuksella: INTRO −7,63 − 10,0 = −17,6, MID −10,42 − 8,28
#: = −18,7, END −10,66 − 8,17 = −18,8 LUFS. Mediaani. Raidan fader tulee
#: Hindenburgissa tämän päälle; automixer ei käytä faderia.
PLATEAU_LUFS = -18.7
#: Pohja jonka nimessä on jokin näistä soi kylmän alun alla ennen nousuaan.
COLD_OPEN_WORDS = ("INTRO", "ALKU")
#: Verhokäyrien välimuisti. Turvallista tyhjentää milloin tahansa.
CACHE_DIR: Path | None = Path.home() / "Library" / "Caches" / "automixer" / "envelopes"
#: Lyhin mitattava pätkä on yksi 400 ms lohko (BS.1770).
MIN_LOUDNESS_S = 0.4


def _free_path(path: Path) -> Path:
    """``nimi beds.nhsx``, ``nimi beds v2.nhsx``… Sama tapa kuin
    podcast-magicin ``next_free_path``: vanhaa ajoa ei ylikirjoiteta."""
    target = path.with_name(f"{path.stem} beds{path.suffix}")
    n = 2
    while target.exists():
        target = path.with_name(f"{path.stem} beds v{n}{path.suffix}")
        n += 1
    return target


def _plateau_gain(source: str, offset: float, curve) -> float:
    """Vahvistus joka vie pohjan tasanteen ``PLATEAU_LUFS``:iin."""
    flat = [t for t, db in curve if db == 0.0]
    info = sf.info(source)
    meter = Meter(info.samplerate)
    if flat and flat[-1] - flat[0] >= MIN_LOUDNESS_S:
        start, stop = offset + flat[0], offset + flat[-1]
    else:
        start, stop = offset, offset + curve[-1][0]
    audio, _ = sf.read(
        source,
        start=int(start * info.samplerate),
        stop=int(stop * info.samplerate),
        always_2d=True,
    )
    loudness = meter.integrated_loudness(audio)
    return PLATEAU_LUFS - loudness


def _envelope(path: str):
    from speechmix.rms import envelope_for

    return envelope_for(path, cache_dir=CACHE_DIR)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Write music-bed fades, timed to the speech, into a new .nhsx."
    )
    parser.add_argument("session", help="Hindenburg session (.nhsx)")
    args = parser.parse_args()

    source = Path(args.session)
    session = read(source)
    music = [t for t in session.tracks if _is_music(t, session)]
    speech = [t.name for t in session.tracks if t not in music]
    if not music:
        print("No music track found (name with MUSA/MUSIC/…, or IsMusic regions).")
        return
    print(f"Speech: {', '.join(speech)}. Music: {', '.join(t.name for t in music)}.")
    spans = activity.speech_intervals(session, speech, envelope=_envelope)

    for track in music:
        for region in track.regions:
            info = session.file_by_id(region.ref)
            name = info.name if info else region.ref
            cold = any(w in name.upper() for w in COLD_OPEN_WORDS)
            curve = musicbed.curve(region.start, region.end, spans, cold_open=cold)
            if curve is None:
                print(f"  {name}: no pause of {musicbed.MIN_GAP_S:g} s under it, left as is.")
                continue
            path = locate(session, info)
            gain = _plateau_gain(path, region.offset, curve)
            segs = fades.segments([(t, db + gain) for t, db in curve])
            for attr in ("FadeIn", "FadeOut"):
                region.elem.attrib.pop(attr, None)
            fades.write(region.elem, segs)
            flat = [t for t, db in curve if db == 0.0]
            when = (
                f"full {region.start + flat[0]:.1f}–{region.start + flat[-1]:.1f} s"
                if flat else "no plateau"
            )
            role = "under the cold open, then " if cold else ""
            print(f"  {name}: {role}{when}, plateau {gain:+.1f} dB, {len(segs)} fades.")

    target = _free_path(source)
    session.tree.write(str(target), encoding="UTF-8", xml_declaration=True)
    print(f"Wrote {target}")


if __name__ == "__main__":
    main()
