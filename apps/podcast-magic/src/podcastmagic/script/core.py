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


#: Tauko jonka kohdalla puhe jaetaan vuoroiksi, kun raidalla on yksi koko jakson
#: mittainen alue (istuntoa ei ole vaimennettu). Auto-Silencen oletustauko on 1 s.
#: Snapshot colab-transcriben ``_split_bursts``ista; testi pitää ne samoina.
TURN_GAP_S = 1.0


def _stamp(seconds: float) -> str:
    total = int(seconds)
    return f"[{total // 60:02d}:{total % 60:02d}]"


def script(session: Session) -> str:
    """Käsikirjoitus markdownina: yksi kappale per puheenvuoro.

    Puhujan nimi on raidan nimi. Peräkkäiset alueet samalta raidalta ovat
    yksi vuoro, koska Hindenburg pilkkoo raidan hiljaisuuksista ja joka
    palasta oma rivi toistaisi nimen. Vuoron aikaleima on sen ensimmäisen
    alueen; puhujan vaihtuessa väliin tulee tyhjä rivi.

    **Keskeytys katkaisee vuoron.** Alue ei katkea toisen puhujan kohdalla,
    joten pitkän vuoron keskellä voi olla toisen lyhyt huomautus. Jos toisen
    vuoro alkaa toisen sisällä ja päättyy ennen sen loppua, edellinen
    vuoro katkeaa huomautuksen alkuun ja jatkuu omalla aikaleimallaan
    (ensimmäisen sanan paikka). Pidempään jatkuva puhe ei ole keskeytys
    vaan vuoronvaihto, ja se jää järjestykseen alkuhetkensä mukaan.
    """
    # (alue alkaa, puhuja, [(sanan aika aikajanalla, loppu, teksti)])
    entries: list[tuple[float, str, list[tuple[float, float, str]]]] = []
    for track in session.tracks:
        for region in track.regions:
            info = session.file_by_id(region.ref)
            if info is None:
                continue
            inside = [
                (
                    region.start + w.start - region.offset,
                    region.start + w.end - region.offset,
                    w.text,
                )
                for w in info.words()
                if w.start < region.offset + region.length and w.end > region.offset
            ]
            if not inside:
                continue  # musiikkiraita ja tyhjä alue eivät ole käsikirjoitusta
            entries.append((region.start, track.name, inside))

    return _render(_split_bursts(entries))


def _split_bursts(entries):
    """Alueen sanat tauoista pätkiksi: ``(alku, nimi, sanat)`` per pätkä.

    Vaimentamattomalla raidalla alue on koko jakso, ja kaikki yhden puhujan puhe
    olisi yksi kappale aikaleimalla 00:00. Ensimmäinen pätkä pitää alueen alun,
    jos sana alkaa sekunnin sisällä siitä (näin vaimennetun istunnon aikaleimat
    eivät muutu); muut alkavat ensimmäisestä sanastaan.
    """
    out = []
    for start, name, words in entries:
        bursts = [[words[0]]]
        for word in words[1:]:
            if word[0] - bursts[-1][-1][1] >= TURN_GAP_S:
                bursts.append([word])
            else:
                bursts[-1].append(word)
        for k, burst in enumerate(bursts):
            first = burst[0][0]
            keeps_region_start = k == 0 and first - start <= 1.0
            out.append((start if keeps_region_start else first, name, burst))
    return out


def _render(entries: list[tuple[float, str, list[tuple[float, float, str]]]]) -> str:
    """Alueet markdowniksi: keskeytykset katkaisevat, saman puhujan palat yhtyvät."""
    entries = sorted(entries, key=lambda entry: entry[0])
    # Keskeytys katkaisee *alueen*: toisen puhujan alue joka alkaa tämän
    # sisällä ja päättyy ennen sen loppua. Vuoroiksi yhdistetään vasta
    # katkaisun jälkeen, koska muuten yhdistetty vuoro vei mukanaan myös
    # myöhemmät alueensa eikä sisäkkäisyyttä voinut arvioida.
    pieces: list[tuple[float, str, list[str]]] = []
    for start, name, words in entries:
        first, last = words[0][0], words[-1][1]
        cuts = sorted(
            other[0][0]
            for _, other_name, other in entries
            if other_name != name and first < other[0][0] and other[-1][1] <= last
        )
        position = 0
        for cut in [*cuts, float("inf")]:
            end = position
            while end < len(words) and words[end][0] < cut:
                end += 1
            bit = words[position:end]
            if bit:
                pieces.append((start if position == 0 else bit[0][0], name,
                               [w[2] for w in bit]))
            position = end
    pieces.sort(key=lambda piece: piece[0])

    lines: list[tuple[float, str, list[str]]] = []
    for start, name, texts in pieces:
        if lines and lines[-1][1] == name:
            lines[-1][2].extend(texts)  # peräkkäiset palat samalta puhujalta ovat yksi vuoro
        else:
            lines.append((start, name, list(texts)))
    out = [f"{_stamp(start)} **{name}:** {' '.join(texts)}" for start, name, texts in lines]
    return "\n\n".join(out) + ("\n" if out else "")
