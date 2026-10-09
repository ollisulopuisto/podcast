"""Litteroinnista luettava käsikirjoitus.

Sanat ja niiden ajat tulevat ``nhsx/read.py``:ltä; jäljellä on sijoitus
aikajanalle ja markdown. Jokainen alue, jolla on sanoja, tuo tekstiä
puhujan vuoroon: aikaleima on regionin paikka **aikajanalla**, ja tekstin
antavat sanat joiden tiedostoaika osuu alueen ikkunaan
``[Offset, Offset + Length)``.
Sama tiedosto voi olla aikajanalla useammin kuin kerran, ja joka kerralla
samat sanat kuuluvat eri kohtaan jaksoa.
"""

from __future__ import annotations

from nhsx.read import Session, read

__all__ = ["read", "script"]


def _stamp(seconds: float) -> str:
    total = int(seconds)
    return f"[{total // 60:02d}:{total % 60:02d}]"


def script(session: Session) -> str:
    """Käsikirjoitus markdownina: yksi kappale per puheenvuoro.

    Puhujan nimi on raidan nimi. Peräkkäiset alueet samalta raidalta ovat
    yksi vuoro, koska Hindenburg pilkkoo raidan hiljaisuuksista ja joka
    palasta oma rivi toistaisi nimen. Vuoron aikaleima on sen ensimmäisen
    alueen; puhujan vaihtuessa väliin tulee tyhjä rivi.
    """
    entries: list[tuple[float, str, str]] = []
    for track in session.tracks:
        for region in track.regions:
            info = session.file_by_id(region.ref)
            if info is None:
                continue
            inside = [
                w
                for w in info.words()
                if w.start < region.offset + region.length and w.end > region.offset
            ]
            if not inside:
                continue  # musiikkiraita ja tyhjä alue eivät ole käsikirjoitusta
            entries.append(
                (region.start, track.name, " ".join(w.text for w in inside))
            )

    entries.sort(key=lambda entry: entry[0])
    turns: list[tuple[float, str, list[str]]] = []
    for start, name, text in entries:
        if turns and turns[-1][1] == name:
            turns[-1][2].append(text)
        else:
            turns.append((start, name, [text]))
    out = [f"{_stamp(start)} **{name}:** {' '.join(parts)}" for start, name, parts in turns]
    return "\n\n".join(out) + ("\n" if out else "")
