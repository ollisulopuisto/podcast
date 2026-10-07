"""Kirjaston virheviestit, ja isännän mahdollisuus kääntää ne.

Kolmesta sovelluksesta vain autoraffkatilla on käännöskoneisto. Jos
kirjasto vaatisi sen, kaksi muuta joutuisivat rakentamaan tyhjän kuoren
pelkästään voidakseen tuoda paketin — joten oletuksena tässä on englanti
ja isäntä saa halutessaan tarjota oman ``translate``insa.

Viesti syntyy **aina virhepolulla**, ja siksi tämä ei saa itse kaatua:
tuntematon avain, puuttuva muotoiluarvo tai kaatuva isännän käännös
korvaisivat oikean syyn väärällä, ja se on vaikeampi vika kuin
alkuperäinen. Kaikki kolme päätyvät siihen että jotain luettavaa tulee
ulos.
"""

from __future__ import annotations

from collections.abc import Callable

# Englanti, koska se on ainoa jonka kaikki kolme sovellusta jakavat.
# Suomenkieliset vastineet ovat autoraffkatin ``i18n.py``:ssä, joka
# rekisteröi itsensä kääntäjäksi.
FALLBACK: dict[str, str] = {
    "binaries.missing": (
        "{name} was not found. Install it — brew install ffmpeg on macOS — "
        "or build the app, which bundles it."
    ),
    "envelope.source_missing": "File not found: {path}",
    "envelope.decode_failed": "Decoding the audio failed: {name}\n{error}",
    "audio.plugin_missing": "Plug-in not found: {path}",
    "audio.plugin_failed": "Could not load the plug-in: {name} — {error}",
    "audio.plugin_length": "The plug-in changed the length ({before} → {after}).",
    "audio.chain_length": "Processing changed the length ({before} → {after}).",
    "audio.editor_timeout": (
        "The plug-in's window was open too long. Close it and try again."
    ),
    "audio.editor_failed": "The plug-in's window could not be opened.",
    "audio.editor_behind": "The plug-in's window did not come to the front.",
    "audio.program_short": "Mastering fell short: target {target} LUFS, got {got}.",
    "audio.program_none": "Mastering was skipped: no processed stem could be measured.",
    "audio.empty_file": "Empty audio file: {name}",
    "audio.plugin_shifted": (
        "The plug-in shifted the audio by {samples} samples ({ms:.0f} ms): {name}. "
        "Picture and sound would drift apart, so the result is not used."
    ),
    "audio.would_overwrite": "Processing would have written over the original: {name}",
    "audio.written_length": (
        "The written file has a different length ({before} → {after}): {name}."
    ),
    "audio.debleed_too_little": (
        "{name}'s bleed was not removed: too little material where they speak alone."
    ),
    "audio.debleed_no_path": (
        "{name}'s bleed was not removed: the leakage path could not be solved."
    ),
    "audio.debleed_ate_speech": (
        "{name}'s bleed was not removed: the subtraction would have eaten this "
        "microphone's own speech."
    ),
    "audio.debleed_no_gain": "{name}'s bleed was not removed: there was nothing to remove.",
}

_translate: Callable[..., str] | None = None


def set_translator(fn: Callable[..., str] | None) -> None:
    """Antaa isännän kääntää kirjaston viestit. ``None`` palauttaa oletuksen.

    Prosessin laajuinen, kuten gettextissä. autoraffkatin oma valinta on
    ``ContextVar``issa, koska käsittely ajaa taustasäikeessä samalla kun
    käyttöliittymä kysyy tilaa — mutta se on isännän asia, ei tämän.
    """
    global _translate
    _translate = fn


def t(key: str, **values) -> str:
    """Viesti avaimella, isännän kääntämänä jos sellainen on."""
    if _translate is not None:
        try:
            return _translate(key, **values)
        except Exception:
            pass
    template = FALLBACK.get(key)
    if template is None:
        # Tuntematon avain: avain itse ja arvot, jotta viesti kertoo edes
        # jotain. Hiljainen tyhjä olisi tässä pahin mahdollinen.
        extra = ", ".join(f"{name}={value}" for name, value in values.items())
        return f"{key}{f' ({extra})' if extra else ''}"
    try:
        return template.format(**values)
    except (KeyError, IndexError):
        return f"{key} ({', '.join(f'{k}={v}' for k, v in values.items())})"
