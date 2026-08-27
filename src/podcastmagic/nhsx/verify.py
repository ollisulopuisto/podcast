"""Litteroinnin tarkistus.

Tämä on olemassa yhtä vikaa varten. Hindenburgin aikajananäkymässä sanat
osuvat kohdalleen, mutta käsikirjoitusnäkymässä toistokohdistin jää alkuun:
kun soitin on 25 minuutin kohdalla, korostus on yhä dokumentin alussa.

Näkymät lukevat samaa dataa mutta eri tavalla. Aikajananäkymä piirtää sanat
alueen sisään, jolloin muunnosta ei tarvita: sana on siinä missä alue on.
Käsikirjoitusnäkymä on erillinen dokumentti, jonka pitää rakentaa
aikaindeksi — ja indeksi on juuri se asia joka voi epäonnistua hiljaa.
Epäonnistunut indeksi osoittaa alkuun, mikä on täsmälleen tämä oire.

Nämä tarkistukset ovat lista asioita, jotka voisivat indeksin rikkoa, eivät
tiedossa oleva syy. Formaattia ei ole dokumentoitu, joten mittaus on ainoa
tapa erottaa arvaus syystä: aja tämä tiedostolle joka oireilee, ja katso
mikä siitä löytyy.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .read import Session, Word, descendants, localname

# Kuinka monta esimerkkiä kustakin havainnosta kerätään. Tarkoitus on
# osoittaa kohta tiedostosta, ei tulostaa jokaista tuhannesta.
EXAMPLES = 5


# Havainnon laji. «vika» on jotain joka on mitattavasti väärin
# tiedostossa; «huomio» on rakenteellinen tosiasia tuotoksestamme, joka on
# epäilty muttei todistettu syy. Ero on tässä siksi, että ilman sitä
# tarkistus ei koskaan sanoisi «puhdas»: puhujatunnus on aina «UU», ja
# jokainen ajo näyttäisi yhtä epäilyttävältä.
DEFECT = "vika"
NOTE = "huomio"


@dataclass
class Finding:
    """Yksi havainto. ``kind`` on koneelle, ``detail`` ihmiselle."""

    kind: str
    count: int
    detail: str
    examples: list[str] = field(default_factory=list)
    severity: str = DEFECT

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "count": self.count,
            "detail": self.detail,
            "examples": self.examples,
            "severity": self.severity,
        }


@dataclass
class FileReport:
    name: str
    words: int = 0
    paragraphs: int = 0
    longest_paragraph: int = 0
    speakers: list[str] = field(default_factory=list)
    first_word: float = 0.0
    last_word: float = 0.0
    findings: list[Finding] = field(default_factory=list)
    # Alueet joissa tämä tiedosto on aikajanalla: (raita, start, offset, length)
    placements: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "words": self.words,
            "paragraphs": self.paragraphs,
            "longestParagraph": self.longest_paragraph,
            "speakers": self.speakers,
            "firstWord": round(self.first_word, 3),
            "lastWord": round(self.last_word, 3),
            "findings": [f.to_dict() for f in self.findings],
            "placements": self.placements,
        }


def _clock(seconds: float) -> str:
    minutes, secs = divmod(max(0.0, seconds), 60)
    hours, minutes = divmod(int(minutes), 60)
    return f"{hours:d}:{minutes:02d}:{secs:06.3f}"


def check_order(words: list[Word]) -> list[Finding]:
    """Sanojen järjestys ja päällekkäisyys.

    Hakupuu ajan yli olettaa kasvavan järjestyksen. Yksi taaksepäin hyppäävä
    sana rikkoo puolitushaun, ja rikkonainen puolitushaku ei palauta virhettä
    vaan väärän kohdan — usein ensimmäisen. Whisper tuottaa tällaisia:
    lämpötilan pudotus segmentin rajalla voi siirtää sanan taaksepäin, ja
    sanan loppu voi olla ennen sen alkua.
    """
    backwards = Finding("backwards", 0, "Sana alkaa ennen edellistä sanaa.")
    overlap = Finding("overlap", 0, "Sana alkaa ennen kuin edellinen loppuu.")
    empty = Finding("empty", 0, "Sanan pituus on nolla tai negatiivinen.")

    previous: Word | None = None
    for index, word in enumerate(words):
        if word.length <= 0:
            empty.count += 1
            if len(empty.examples) < EXAMPLES:
                empty.examples.append(f"#{index} «{word.text}» l={word.length:.3f}")
        if previous is not None:
            if word.start < previous.start:
                backwards.count += 1
                if len(backwards.examples) < EXAMPLES:
                    backwards.examples.append(
                        f"#{index} «{word.text}» {_clock(word.start)} "
                        f"< «{previous.text}» {_clock(previous.start)}"
                    )
            elif word.start < previous.end - 1e-6:
                overlap.count += 1
                if len(overlap.examples) < EXAMPLES:
                    overlap.examples.append(
                        f"#{index} «{word.text}» {_clock(word.start)} "
                        f"< «{previous.text}» loppuu {_clock(previous.end)}"
                    )
        previous = word

    return [f for f in (backwards, overlap, empty) if f.count]


def check_placement(session: Session, file_id: str, words: list[Word]) -> list[Finding]:
    """Sanat suhteessa siihen, mitä tiedostosta on aikajanalla.

    Litterointi kattaa koko tiedoston. Aikajanalla on vain se osa jonka
    alueet peittävät, ja alun trimmaus jättää sanoja alueen ulkopuolelle.
    Aikajananäkymä ei piirrä niitä lainkaan — se näyttää oikealta.
    Käsikirjoitusnäkymä näyttää koko tiedoston, jolloin dokumentissa on
    tekstiä jota aikajanalla ei ole, ja kohdistin ja teksti eivät voi olla
    samassa kohdassa.
    """
    spans = []
    for track in session.tracks:
        for region in track.regions:
            if region.ref == file_id:
                spans.append((region.offset, region.offset + region.length))
    if not spans:
        return []

    outside = Finding(
        "outside_regions",
        0,
        "Sana ei osu yhdellekään alueelle: se on litteroinnissa mutta ei aikajanalla.",
    )
    for index, word in enumerate(words):
        if not any(start <= word.start < end for start, end in spans):
            outside.count += 1
            if len(outside.examples) < EXAMPLES:
                outside.examples.append(f"#{index} «{word.text}» {_clock(word.start)}")
    return [outside] if outside.count else []


def check_shape(file_elem, words: list[Word]) -> list[Finding]:
    """Dokumentin rakenne.

    Yksi kappale, jossa on tuhansia sanoja, ei ole käsikirjoitus vaan
    tekstimuuri. Hindenburgin oma litterointi jakaa puheenvuoroihin, ja
    käsikirjoitusnäkymä on rakennettu sen ympärille — vierittäminen ja
    korostus toimivat kappaleittain. Yhdellä kappaleella ei ole mihin
    vierittää, ja dokumentti jää alkuun.
    """
    findings = []
    transcription = None
    for child in file_elem:
        if localname(child) == "Transcription":
            transcription = child
            break
    if transcription is None:
        return findings

    paragraphs = [p for p in transcription if localname(p) == "p"]
    if len(paragraphs) == 1 and len(words) > 200:
        findings.append(
            Finding(
                "one_paragraph",
                len(words),
                f"Koko litterointi on yhdessä <p>-kappaleessa ({len(words)} sanaa).",
                [f"kappaleita: {len(paragraphs)}"],
                severity=NOTE,
            )
        )

    speakers = {w.get("sp") for w in descendants(transcription, "w")}
    speakers.discard(None)
    if speakers == {"UU"}:
        findings.append(
            Finding(
                "no_speaker",
                len(words),
                "Kaikki sanat ovat puhujaa «UU» — puhujaa ei ole eroteltu.",
                ["sp=UU"],
                severity=NOTE,
            )
        )
    return findings


def inspect(session: Session) -> dict:
    """Käy istunnon litteroinnit läpi ja palauttaa havainnot."""
    reports: list[FileReport] = []
    for info in session.files:
        words = info.words()
        if not words and not info.transcribed:
            continue

        transcription = info.transcription
        paragraphs = (
            [p for p in transcription if localname(p) == "p"] if transcription is not None else []
        )
        speakers = sorted({w.get("sp") or "" for w in descendants(transcription, "w")}) if (
            transcription is not None
        ) else []

        report = FileReport(
            name=info.name,
            words=len(words),
            paragraphs=len(paragraphs),
            longest_paragraph=max(
                (len(descendants(p, "w")) for p in paragraphs), default=len(words)
            ),
            speakers=speakers,
            first_word=words[0].start if words else 0.0,
            last_word=words[-1].end if words else 0.0,
        )
        for track in session.tracks:
            for region in track.regions:
                if region.ref == info.id:
                    report.placements.append(
                        {
                            "track": track.name,
                            "start": round(region.start, 3),
                            "offset": round(region.offset, 3),
                            "length": round(region.length, 3),
                        }
                    )

        report.findings = (
            check_order(words)
            + check_placement(session, info.id, words)
            + check_shape(info.elem, words)
        )
        reports.append(report)

    return {
        "session": session.path,
        "files": [r.to_dict() for r in reports],
        "clean": all(
            f.severity != DEFECT for report in reports for f in report.findings
        ),
    }


def as_text(result: dict) -> str:
    """Sama raportti tekstinä, kopioitavaksi sellaisenaan."""
    lines = [f"Litteroinnin tarkistus: {result['session']}", ""]
    if not result["files"]:
        lines.append("Istunnossa ei ole litterointia.")
        return "\n".join(lines)

    for report in result["files"]:
        lines.append(f"  {report['name']}")
        lines.append(
            f"    {report['words']} sanaa, {report['paragraphs']} kappaletta "
            f"(pisin {report['longestParagraph']} sanaa), "
            f"puhujat {report['speakers'] or '—'}"
        )
        lines.append(
            f"    ensimmäinen sana {_clock(report['firstWord'])}, "
            f"viimeinen {_clock(report['lastWord'])}"
        )
        for placement in report["placements"]:
            lines.append(
                f"    alue raidalla «{placement['track']}»: "
                f"aikajanalla {_clock(placement['start'])}, "
                f"tiedostossa {_clock(placement['offset'])}–"
                f"{_clock(placement['offset'] + placement['length'])}"
            )
        if not report["findings"]:
            lines.append("    ei havaintoja")
        for finding in report["findings"]:
            lines.append(
                f"    [{finding['severity']}: {finding['kind']}] "
                f"{finding['count']}× — {finding['detail']}"
            )
            for example in finding["examples"]:
                lines.append(f"        {example}")
        lines.append("")
    return "\n".join(lines)
