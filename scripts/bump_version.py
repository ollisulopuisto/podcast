#!/usr/bin/env python3
"""Nostaa yhden jäsenen CalVer-version kaikkiin paikkoihin joissa se on.

    uv run python scripts/bump_version.py autoraffkat
    uv run python scripts/bump_version.py autoraffkat --set 2026.9.1.1

Tämä oli ennen `apps/automixer/scripts/bump_version.py`, vain automixerillä
ja monorepossa rikki kahdella tavalla. Se luki `pyproject.toml`in
työhakemistosta, joten se nosti sen sovelluksen version jonka hakemistossa
satuttiin olemaan. Ja `N` oli `git rev-list --count HEAD`, joka on nyt koko
työtilan committien määrä — 102 tätä kirjoitettaessa, kun autoraffkat on
jo versiossa `2026.8.27.113`. Se olisi kääntänyt numeron **taaksepäin**,
ja `CFBundleVersion` on ainoa asia jonka perusteella macOS päättää
tarjoaako se päivitystä.

`N` lasketaan siksi edellisestä versiosta eikä gitistä: sama päivä
kasvattaa `N`:ää, uusi päivä aloittaa ykkösestä. Silloin numero kasvaa aina,
myös silloin kun git-historia ei ole se mitä joku olettaa (subtree-tuonti,
siirretty hakemisto, uudelleenkirjoitettu haara).

Versio kirjoitetaan jokaiseen paikkaan josta joku sen lukee — muuten
`tests/test_workspace_agrees.py` kaatuu, ja se on tarkoitus:

* `pyproject.toml` — mitä uv asentaa ja julkaisee
* `src/<paketti>/__init__.py` — mitä käyttöliittymä näyttää, jos se on
  kirjoitettu auki (automixer johtaa sen asennuksesta eikä siis ole listalla)
* `<sovellus>.spec` — mitä Finder näyttää ja mistä macOS päättää päivityksen

Joko kaikki tai ei mitään: korvaukset lasketaan ensin ja kirjoitetaan vasta
kun jokainen tiedosto osui. Puolittain nostettu versio on täsmälleen se
vika jota vastaan tämä on.

Ei tee committia eikä tagia. Tagi on `<sovellus>-v<versio>`, ja se on se
mistä julkaisuputki lähtee liikkeelle.
"""

from __future__ import annotations

import argparse
import datetime
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

VERSION_IN_PYPROJECT = r'(?m)^version = "(.+)"$'
VERSION_IN_INIT = r'(?m)^__version__ = "(.+)"$'
VERSION_IN_SPEC = r'os\.environ\.get\("[A-Z_]+VERSION", "(.+?)"\)'

CALVER = re.compile(r"^(\d{4})\.(\d{1,2})\.(\d{1,2})\.(\d+)$")


def shown(path: Path) -> str:
    """Polku työtilan juuresta, tai sellaisenaan jos se on jossain muualla.

    Virheilmoitus ei saa kaatua omaan siisteyteensä: `relative_to` nostaa
    `ValueError`in työtilan ulkopuolisesta polusta, ja silloin lukija näkisi
    sen eikä sitä mitä oikeasti meni pieleen.
    """
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def members() -> dict[str, Path]:
    """Nimi hakemistoon. Luettelo levyltä, jotta uusi sovellus toimii heti.

    Sama johdannaisjoukko kuin `tests/test_workspace_agrees.py`ssä: jäsen
    on hakemisto jossa on `pyproject.toml`, myös juuressa — tällä hetkellä
    `colab-transcribe`, joka ei seiso `apps/`issa (syy juuren
    `pyproject.toml`issa).
    """
    found = [
        *ROOT.glob("apps/*/pyproject.toml"),
        *ROOT.glob("packages/*/pyproject.toml"),
        *ROOT.glob("*/pyproject.toml"),
    ]
    return {p.parent.name: p.parent for p in sorted(found)}


def current_version(member: Path) -> str:
    found = re.search(
        VERSION_IN_PYPROJECT, (member / "pyproject.toml").read_text(encoding="utf-8")
    )
    if not found:
        raise SystemExit(f"{member.name}: pyproject.toml ei kerro versiota")
    return found.group(1)


def next_version(previous: str, today: datetime.date | None = None) -> str:
    """Sama päivä kasvattaa juoksevaa numeroa, uusi päivä aloittaa ykkösestä.

    macOS vertaa `CFBundleVersion`ia osa kerrallaan, joten `N`:n nollaus on
    turvallista vain kun jokin sitä edeltävä osa kasvaa — ja se on tasan
    silloin kun päivä on vaihtunut.
    """
    day = today or datetime.date.today()
    was = CALVER.match(previous)
    if not was:
        raise SystemExit(f"edellinen versio ei ole CalVeriä: {previous}")
    same_day = (int(was[1]), int(was[2]), int(was[3])) == (day.year, day.month, day.day)
    serial = int(was[4]) + 1 if same_day else 1
    return f"{day.year}.{day.month}.{day.day}.{serial}"


def edits(member: Path, version: str) -> list[tuple[Path, str]]:
    """Kaikki kirjoitukset valmiina, tai poikkeus. Mitään ei ole vielä tallennettu."""
    planned: list[tuple[Path, str]] = []

    targets = [(member / "pyproject.toml", VERSION_IN_PYPROJECT, True)]

    (package,) = (member / "src").iterdir()
    init = package / "__init__.py"
    # automixer johtaa versionsa `importlib.metadata`sta, joten sillä ei ole
    # kirjoitettua numeroa nostettavaksi. Se ei ole virhe, se on toinen tapa.
    if init.exists() and re.search(VERSION_IN_INIT, init.read_text(encoding="utf-8")):
        targets.append((init, VERSION_IN_INIT, True))

    # Vain `.app`in kokoavat `.spec`it. Sovelluksella voi olla useampi:
    # `podcast-magic` paketoi sekä ikkunallisen sovelluksen että
    # `nhsx-render`in yhtenä binäärinä, ja vain edellisellä on `Info.plist`
    # ja siten `CFBundleVersion`. Binäärille numeron kirjoittaminen olisi
    # neljäs kopio samasta luvusta; se kertoo versionsa paketista.
    targets += [
        (spec, VERSION_IN_SPEC, True)
        for spec in sorted(member.glob("*.spec"))
        if "BUNDLE(" in spec.read_text(encoding="utf-8")
    ]

    for path, pattern, required in targets:
        text = path.read_text(encoding="utf-8")
        new, count = re.subn(
            pattern, lambda m: m.group(0).replace(m.group(1), version), text
        )
        if count != 1 and required:
            raise SystemExit(f"{shown(path)}: odotettiin yhtä osumaa, löytyi {count}")
        planned.append((path, new))

    return planned


def main() -> None:
    known = members()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("member", choices=sorted(known), help="jäsen jonka versio nousee")
    parser.add_argument(
        "--set", dest="version", help="kirjoita tämä versio laskemisen sijaan"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="kerro mitä tekisi, älä kirjoita"
    )
    args = parser.parse_args()

    member = known[args.member]
    was = current_version(member)
    version = args.version or next_version(was)
    planned = edits(member, version)

    print(f"{args.member} {was} → {version}")
    for path, _ in planned:
        print(f"  {shown(path) if member not in path.parents else path.relative_to(member)}")
    if args.dry_run:
        return

    for path, text in planned:
        path.write_text(text, encoding="utf-8")
    print(f"\n  git tag {args.member}-v{version}")


if __name__ == "__main__":
    sys.exit(main())
