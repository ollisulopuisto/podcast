"""Litteroinnin ajo: äänipoolista sanoiksi ja takaisin istuntoon.

Työ etenee **äänipoolin** mukaan, ei hakemistolistauksen. Colab-muistikirja
litteroi kaiken mitä syötehakemistosta löytyi ja yritti sitten sovittaa
tulokset istuntoon tiedostonimellä. Poolista lähtemällä litteroitavaksi
päätyy täsmälleen se mitä istunnossa on, ja tulos osuu ``Id``:hen eikä
nimeen — pooli voi sisältää kaksi eri kansiosta tullutta ``puhe.wav``ia.

Valmis litterointi tunnistetaan istunnosta eikä levyltä. Muistikirjan
tarkistus rakensi ``.nhsx``-nimen **äänitiedoston** nimestä, joten se osui
vain jos vieressä sattui olemaan samanniminen istunto; käytännössä se ei
ohittanut mitään.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from .. import audio as audio_io
from .. import nhsx
from ..jobs import Progress
from ..nhsx.read import locate as locate_audio
from ..nhsx.write import next_free_path, set_transcription
from .backends import resolve
from .backends.base import words_from_segments
from .options import Options

TRANSCRIPTS_DIRNAME = "transcripts"


@dataclass
class Plan:
    """Mitä ajo tekisi. Näytetään käyttöliittymässä ennen käynnistystä."""

    session: str
    output: str
    todo: list[dict]
    skipped: list[dict]
    missing: list[dict]

    def to_dict(self) -> dict:
        return {
            "session": self.session,
            "output": self.output,
            "todo": self.todo,
            "skipped": self.skipped,
            "missing": self.missing,
        }


def transcripts_dir(session_path: str, output_dir: str = "") -> Path:
    """Hakemisto JSON-litteroinneille.

    Näkyvässä paikassa työn vieressä, ei piilotettuna välimuistina: kun ajo
    ohittaa tiedoston «on jo litteroitu», sen todisteen pitää olla
    löydettävissä ilman että tietää mistä etsiä.
    """
    base = Path(output_dir) if output_dir else Path(session_path).parent
    return base / TRANSCRIPTS_DIRNAME


def cache_path(directory: Path, audio_path: str, options: Options) -> Path:
    """JSONin nimi: äänen nimi ja asetusten tunniste.

    Tunniste on nimessä, koska muuten mallin vaihtaminen ei tekisi mitään —
    vanha tulos löytyisi levyltä ja uusi malli jäisi ajamatta.
    """
    stem = Path(audio_path).stem
    return directory / f"{stem}.{options.fingerprint()}.json"


def plan(session_path: str, audio_dir: str = "", force: bool = False) -> Plan:
    """Kertoo mitä ajo tekisi, ilman että mitään ajetaan.

    Ei ota ``Options``ia, koska vastaus ei riipu niistä: ``run`` päättää
    tekemisen samalla ehdolla (``transcribed and not force``), ja
    asetustunnisteella nimetty välimuisti vaikuttaa vain nopeuteen — sen
    osuma ei poista tiedostoa työlistalta. Jos asetukset joskus muuttavat
    sitä *mitä* tehdään, ne palaavat tänne käyttönsä kanssa.
    """
    session = nhsx.read(session_path)
    todo, skipped, missing = [], [], []
    for info in session.files:
        found = locate_audio(session, info, audio_dir)
        entry = {"id": info.id, "name": info.name, "path": found}
        if not found:
            missing.append(entry)
            continue
        if info.transcribed and not force:
            entry["words"] = len(info.words())
            skipped.append(entry)
            continue
        todo.append(entry)
    return Plan(
        session=session_path,
        output=str(output_path(session_path)),
        todo=todo,
        skipped=skipped,
        missing=missing,
    )


def output_path(session_path: str) -> Path:
    """Viennin nimi. Lähdettä ei koskaan kirjoiteta yli."""
    source = Path(session_path)
    return source.with_name(f"{source.stem} litteroitu{source.suffix}")


def run(
    session_path: str,
    options: Options,
    progress: Progress,
    audio_dir: str = "",
    force: bool = False,
) -> dict:
    """Litteroi istunnon äänipoolin ja kirjoittaa uuden istuntotiedoston."""
    backend = resolve(options.backend)
    info = backend.info()
    progress.log(f"Moottori: {info.label} — {info.device}")

    session = nhsx.read(session_path)
    progress.log(f"Istunto: {Path(session_path).name} — {len(session.files)} tiedostoa poolissa")

    directory = transcripts_dir(session_path)
    directory.mkdir(parents=True, exist_ok=True)

    work = []
    for file_info in session.files:
        found = locate_audio(session, file_info, audio_dir)
        if not found:
            progress.log(f"Ei löydy levyltä: {file_info.name} — ohitetaan.")
            continue
        if file_info.transcribed and not force:
            progress.log(f"Jo litteroitu istunnossa: {file_info.name} — ohitetaan.")
            continue
        work.append((file_info, found))

    total = len(work)
    if total == 0:
        progress.log("Ei mitään litteroitavaa.")
        return {"written": "", "files": 0, "words": 0}

    written_words = 0
    changed = 0
    for index, (file_info, path) in enumerate(work):
        progress.check()
        progress.step(Path(path).name, done=index, total=total)
        progress.fraction(0.0)

        cache = cache_path(directory, path, options)
        result_raw = None
        if cache.is_file() and not force:
            try:
                result_raw = json.loads(cache.read_text(encoding="utf-8"))
                progress.log(f"Luetaan valmis litterointi: {cache.name}")
            except (OSError, ValueError):
                result_raw = None

        if result_raw is None:
            started = time.time()
            progress.log(f"Litteroidaan {Path(path).name}…")
            samples = audio_io.decode(path)
            seconds = audio_io.duration(samples)
            progress.log(f"  kesto {seconds / 60:.1f} min")
            result = backend.transcribe(samples, options, progress)
            elapsed = time.time() - started
            speed = seconds / elapsed if elapsed > 0 else 0.0
            progress.log(
                f"  valmis {elapsed / 60:.1f} min — {speed:.1f}× reaaliaika, "
                f"{len(result.words)} sanaa"
            )
            result_raw = result.raw
            try:
                cache.write_text(
                    json.dumps(result_raw, ensure_ascii=False, indent=1), encoding="utf-8"
                )
            except OSError as exc:
                progress.log(f"  litterointia ei saatu talteen: {exc}")
            words = result.words
        else:
            words = words_from_segments(list(result_raw.get("segments") or ()))

        if not words:
            # Tyhjä litterointi on kelvollinen <Transcription> ja täysin
            # väärä tulos: vaimennus vaientaisi koko raidan. Se selviäisi
            # vasta Hindenburgissa, joten se sanotaan tässä.
            progress.log(
                f"  VAROITUS: {Path(path).name} ei tuottanut yhtään sanaa. "
                "Onko tiedostossa puhetta, ja onko kieli oikein?"
            )

        report = set_transcription(file_info.elem, words, split=options.paragraphs)
        if report["reordered"] or report["shortened"]:
            # Whisper tuottaa toisinaan taaksepäin hyppääviä ja
            # nollapituisia sanoja. Aikajananäkymässä ne eivät näy, mutta
            # aikaindeksi olettaa kasvavan järjestyksen.
            progress.log(
                f"  siivottiin: {report['reordered']} sanaa järjestykseen, "
                f"{report['shortened']} lyhennettiin"
            )
        progress.log(f"  {report['words']} sanaa, {report['paragraphs']} kappaletta")
        written_words += report["words"]
        changed += 1
        progress.fraction(1.0)
        progress.step(Path(path).name, done=index + 1, total=total)

    if written_words == 0:
        raise RuntimeError(
            f"Litterointi ajettiin {changed} tiedostolle eikä yhtäkään sanaa "
            "tunnistettu. Istuntoa ei kirjoitettu. Tarkista kieli, malli ja se "
            "että tiedostoissa on puhetta."
        )

    target = next_free_path(output_path(session_path))
    nhsx.write(session.tree, target)
    progress.log(f"Kirjoitettiin {target.name} — {written_words} sanaa {changed} tiedostosta.")
    return {"written": str(target), "files": changed, "words": written_words}
