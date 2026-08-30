"""Litteroinnin siirto istunnosta toiseen.

Leikkaus tehdään käsin editoituun istuntoon, ja litterointi on
leikkaamattomassa. Tämä kopioi ``<Transcription>``-elementit nimellä
täsmäytettyjen tiedostojen välillä: lähde istunto, jossa litterointi on,
kohde istunto, johon se puuttuu.

Sanan aika on tiedostoa, ei aikajanaa, joten siirto on suora: sama
nauhoite sama sana sama kohta. Ehtona on että kummankin ``olli.wav``
on **sama nauhoite** — ja juuri siinä vanha versio luotti nimeen. Tässä
kesto mitataan WAV-otsikoista kun molemmat nauhoitteet ovat levyltä, ja
eri mittainen pari jätetään pois ja sanotaan. Ilman äänipoolia ei
mitata, mutta siitä kerrotaan eikä varmuutta esitetä.
"""

from __future__ import annotations

import contextlib
import copy
import wave
from pathlib import Path

from ..nhsx.read import NhsxError, localname, locate, read
from ..nhsx.write import next_free_path, write

# Kuinka monta sekuntia kahden nauhoitteen keot saavat erota. Sama vienti
# on näytetarkka; viiden sadasosan varalle jää pyöristys eikä mitään muuta.
DURATION_TOLERANCE = 0.05


def wav_duration(path: str | Path) -> float | None:
    """Nauhoitteen kesto WAV-otsikosta, tai None jos sitä ei voi lukea.

    Hindenburgin pooli on WAVeja, joten otsikko riittää eikä ääntä pureta.
    Pakattu tai puuttuva tiedosto on ``None`` — mittaamaton, ei nolla.
    """
    try:
        with contextlib.closing(wave.open(str(path))) as handle:
            rate = handle.getframerate()
            if not rate:
                return None
            return handle.getnframes() / rate
    except (wave.Error, OSError):
        return None


def _duration_of(session, file_info) -> float | None:
    found = locate(session, file_info)
    return wav_duration(found) if found else None


def merge(
    source: str | Path, target: str | Path, overwrite: bool = False, save: bool = True
) -> dict:
    """Siirtää litteroinnit. Palauttaa raportin siitä mitä teki ja mitä ei.

    Kohdetiedoston omaa litterointia ei korvata kysymättä: ``overwrite``
    on pois päältä oletuksena, ja olemassa oleva jää ja kertoo itsestään.
    Vienti on uusi tiedosto ``… v2`` — lähdettä eikä kohdetta kirjoiteta
    yli, koska leikkaus on käsin tehty eikä sitä voi rakentaa uudestaan.
    ``save=False`` laskee raportin kirjoittamatta mitään.
    """
    source, target = Path(source), Path(target)
    if source.resolve() == target.resolve():
        raise NhsxError(
            f"Lähde ja kohde ovat sama istunto: {source.name}. "
            "Litterointi kopioidaan leikkaamattomasta istunnosta leikattuun."
        )

    src = read(source)
    dst = read(target)

    report = {
        "copied": [],
        "overwritten": [],
        "kept": [],
        "mismatched": [],
        "unverified": [],
        "missing": [],
        "written": "",
    }

    for info in src.files:
        if not info.transcribed:
            continue  # ei ole mitään annettavaa; puute ei ole päätös
        match = dst.file_by_name(info.name)
        if match is None or match.elem is None:
            report["missing"].append(info.name)
            continue

        # Kesto on mitattavissa vain kun molemmat nauhoitteet ovat levyltä.
        # Puuttuva mitta ei ole osuma eikä hylkäys — se merkitään ja kerrotaan.
        mine, theirs = _duration_of(src, info), _duration_of(dst, match)
        if mine is not None and theirs is not None:
            if abs(mine - theirs) > DURATION_TOLERANCE:
                report["mismatched"].append(info.name)
                continue
        else:
            report["unverified"].append(info.name)

        existing = [c for c in match.elem if localname(c) == "Transcription"]
        if existing:
            if not overwrite:
                report["kept"].append(info.name)
                continue
            for old in existing:
                match.elem.remove(old)
            report["overwritten"].append(info.name)
        else:
            report["copied"].append(info.name)
        match.elem.append(copy.deepcopy(info.transcription))

    if save:
        out = next_free_path(target)
        write(dst.tree, out)
        report["written"] = str(out)
    return report
