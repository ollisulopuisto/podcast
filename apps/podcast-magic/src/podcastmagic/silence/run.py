"""Vaimennuksen ajo."""

from __future__ import annotations

from pathlib import Path

from .. import nhsx
from ..jobs import Progress
from ..nhsx.write import next_free_path
from .apply import audible_zones, has_region_children, split_track
from .detect import AudioCache, dominant_words, speech_intervals
from .presets import Settings


def output_path(session_path: str) -> Path:
    source = Path(session_path)
    return source.with_name(f"{source.stem} vaimennettu{source.suffix}")


def preview(session_path: str, settings: Settings, extra_dir: str = "") -> dict:
    """Laskee raitakohtaiset luvut kirjoittamatta mitään.

    Tasotarkistus puretaan tässäkin, joten esikatselu ei ole ilmainen kun
    ``rms`` on päällä — mutta se on silti nopeampi kuin ajo, koska mitään ei
    pilkota eikä kirjoiteta.
    """
    session = nhsx.read(session_path)
    cache = AudioCache()
    # Sama vertailu kuin ajossa. Ennakko joka ei tee sitä lupaisi eri
    # tuloksen kuin ajo antaa, ja ero näkyisi vasta valmiissa jaksossa.
    dominance = {}
    if settings.rms and settings.dominance > 0:
        dominance = dominant_words(session, settings, cache, extra_dir)
    rows = []
    for track in session.tracks:
        result = speech_intervals(
            session, track, settings, cache, extra_dir,
            dominance=dominance.get(track.name),
        )
        zones = audible_zones(result.intervals, settings.tail, settings.gap)
        rows.append(
            {
                "name": track.name,
                "regions": len(track.regions),
                "words": result.words_seen,
                "quiet": result.words_quiet,
                "bled": result.words_bled,
                "segments": len(result.intervals),
                "zones": len(zones),
                "audible": round(sum(b - a for a, b in zones), 1),
                "missing": result.missing_audio,
                # Sama sääntö kuin ajossa: ilman litterointia raitaan ei
                # kosketa. Ennakon pitää näyttää se, ei nollaa jaksoa.
                "skipped": result.words_seen == 0,
            }
        )
    return {
        "session": session_path,
        "output": str(output_path(session_path)),
        "words": session.word_count,
        "tracks": rows,
    }


def run(
    session_path: str, settings: Settings, progress: Progress, extra_dir: str = ""
) -> dict:
    """Pilkkoo raidat ja kirjoittaa uuden istuntotiedoston."""
    session = nhsx.read(session_path)
    progress.log(f"Istunto: {Path(session_path).name} — {len(session.tracks)} raitaa")

    if session.word_count == 0:
        raise RuntimeError(
            "Istunnossa ei ole litterointia. Aja ensin litterointi — "
            "vaimennus lukee puhejaksot sanojen aikaleimoista."
        )

    if settings.rms:
        progress.log(f"Tason tarkistus päällä, kynnys {settings.threshold:.0f} dB")
    else:
        progress.log("Tason tarkistus pois — pelkkä litterointi ratkaisee")

    cache = AudioCache()

    # Vuotovertailu ennen raitojen kierrosta, koska se on raitojen välinen
    # kysymys: sana kuuluu sille jonka mikillä se on kovimmillaan. Yhden
    # raidan silmukka ei voi vastata siihen, koska se ei näe muita.
    dominance = {}
    if settings.rms and settings.dominance > 0:
        dominance = dominant_words(session, settings, cache, extra_dir)
        if dominance:
            progress.log(
                f"Vuotovertailu päällä, kaista {settings.dominance:.0f} dB "
                "kovimpaan raitaan"
            )
        else:
            # Yksi raita: ei mitään mihin verrata. Sanotaan se, koska
            # käyttöliittymä näyttää säätimen ja tulos on ilman sitä sama.
            progress.log("Vuotovertailu ei koske yhtä raitaa — ohitettiin")
    rows = []
    total = max(1, len(session.tracks))
    dropped_children = False
    # Tason tarkistus voi olla päällä ja jäädä silti tekemättä, jos ääniä ei
    # löydy levyltä. Silloin tulos on «pelkkä litterointi ratkaisi» vaikka
    # käyttöliittymä lupasi muuta — ja ero näkyy vasta kuuntelemalla.
    levels_measured = 0
    levels_missing: set[str] = set()

    for index, track in enumerate(session.tracks):
        progress.check()
        progress.step(track.name or f"raita {index + 1}", done=index, total=total)
        progress.fraction(0.0)

        result = speech_intervals(
            session, track, settings, cache, extra_dir,
            dominance=dominance.get(track.name),
        )

        if result.words_seen == 0:
            # Raita, jolla ei ole litterointia lainkaan, jätetään rauhaan.
            # Se on musiikkia, tunnus tai muuta joka ei ole puhetta: siitä
            # ei ole tietoa, ja tiedon puute ei ole päätös vaientaa. Ilman
            # tätä koko raita vaimenisi, tiedosto avautuisi normaalisti ja
            # puuttuvan musiikin huomaisi vasta kuuntelemalla.
            progress.log(f"  {track.name}: ei litterointia — jätetään koskematta")
            rows.append({"name": track.name, "words": 0, "quiet": 0, "zones": 0,
                         "heard": len(track.regions), "muted": 0, "skipped": True})
            progress.step(track.name, done=index + 1, total=total)
            continue

        levels_measured += result.words_levelled
        levels_missing.update(result.missing_audio)
        if result.missing_audio:
            progress.log(
                f"  ääntä ei löytynyt: {', '.join(result.missing_audio)} — "
                "sanat päästetään läpi tasoa mittaamatta"
            )
        zones = audible_zones(result.intervals, settings.tail, settings.gap)
        progress.fraction(0.5)

        if has_region_children(track.elem):
            dropped_children = True

        heard, muted = split_track(track.elem, zones)
        quiet_note = f", {result.words_quiet} liian hiljaista" if settings.rms else ""
        bled_note = f", {result.words_bled} vuotoa" if result.words_bled else ""
        progress.log(
            f"  {track.name}: {result.words_seen} sanaa{quiet_note}{bled_note} → "
            f"{len(zones)} kuuluvaa jaksoa, {heard} palaa auki ja {muted} vaiti"
        )
        rows.append(
            {
                "name": track.name,
                "words": result.words_seen,
                "quiet": result.words_quiet,
                "bled": result.words_bled,
                "zones": len(zones),
                "heard": heard,
                "muted": muted,
            }
        )
        progress.step(track.name, done=index + 1, total=total)
        progress.fraction(1.0)

    if settings.rms and not levels_measured:
        raise RuntimeError(
            "Tason tarkistus on päällä, mutta yhdenkään raidan ääntä ei "
            f"löytynyt levyltä ({', '.join(sorted(levels_missing)) or 'ei tiedostoja'}). "
            "Tulos olisi sama kuin ilman tarkistusta, joten mitään ei "
            "kirjoitettu. Tarkista äänipoolin polut."
        )

    if dropped_children:
        progress.log(
            "Huom: joillain alueilla oli lapsielementtejä (esim. häivytyksiä). "
            "Ne eivät seuraa pilkkomisessa mukana."
        )

    target = next_free_path(output_path(session_path))
    nhsx.write(session.tree, target)
    progress.log(f"Kirjoitettiin {target.name}")
    return {"written": str(target), "tracks": rows}
