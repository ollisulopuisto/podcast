"""Versionnosto ei saa kääntyä taaksepäin eikä jäädä puolitiehen.

`CFBundleVersion` on ainoa asia jonka perusteella macOS päättää tarjoaako se
päivitystä. Pienempi numero ei kaada mitään — päivitys vain jää tarjoamatta,
ja se huomataan siitä että kukaan ei päivitä.

Edellinen skripti laski `N`:n git-committien määrästä. Monorepossa se olisi
kääntänyt autoraffkatin numeron 113:sta 102:een.
"""

from __future__ import annotations

import datetime
import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location("bump", ROOT / "scripts" / "bump_version.py")
bump = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bump)


def key(version: str) -> tuple[int, ...]:
    """Sama vertailu kuin macOS tekee: osa kerrallaan, numeroina."""
    return tuple(int(part) for part in version.split("."))


def test_the_same_day_carries_on_from_the_last_number():
    assert bump.next_version("2026.8.27.113", datetime.date(2026, 8, 27)) == "2026.8.27.114"


def test_a_new_day_starts_from_one():
    assert bump.next_version("2026.8.27.113", datetime.date(2026, 8, 28)) == "2026.8.28.1"


@pytest.mark.parametrize(
    ("previous", "day"),
    [
        ("2026.8.27.113", datetime.date(2026, 8, 27)),  # sama päivä, iso N
        ("2026.8.27.113", datetime.date(2026, 8, 28)),  # N nollautuu, päivä kasvaa
        ("2026.4.5.37", datetime.date(2026, 8, 27)),  # kuukausia väliä
        ("2026.12.31.9", datetime.date(2027, 1, 1)),  # vuodenvaihde
    ],
)
def test_the_number_never_goes_backwards(previous: str, day: datetime.date):
    assert key(bump.next_version(previous, day)) > key(previous)


def test_every_member_can_be_bumped_and_says_where():
    """Nostettavat paikat luetaan levyltä, joten neljäs jäsen toimii heti."""
    for name, member in bump.members().items():
        planned = bump.edits(member, "2099.1.1.1")
        assert planned, name
        assert any(p.name == "pyproject.toml" for p, _ in planned), name


def test_nothing_is_written_when_one_place_does_not_match(tmp_path):
    """Joko kaikki tai ei mitään.

    Puolittain nostettu versio on tarkalleen se vika jota vastaan skripti on:
    `pyproject.toml` sanoo yhtä ja paketti toista, eikä kumpikaan kaadu.
    """
    member = tmp_path / "esimerkki"
    (member / "src" / "esimerkki").mkdir(parents=True)
    (member / "pyproject.toml").write_text('version = "2026.1.1.1"\n', encoding="utf-8")
    (member / "src" / "esimerkki" / "__init__.py").write_text(
        '__version__ = "2026.1.1.1"\n', encoding="utf-8"
    )
    # Kaksi osumaa yhdessä tiedostossa: kumpi niistä on se oikea ei ole
    # skriptin pääteltävissä, joten se kieltäytyy.
    #
    # `BUNDLE(` on tässä, koska skripti kirjoittaa version vain `.app`in
    # kokoaviin `.spec`eihin — komentorivibinääri kertoo versionsa
    # paketista. Ilman tätä riviä fikstuuri ohitettaisiin kokonaan ja
    # tämä testi olisi vihreä tarkistamatta mitään.
    (member / "esimerkki.spec").write_text(
        'a = os.environ.get("EX_VERSION", "2026.1.1.1")\n'
        'b = os.environ.get("EX_VERSION", "2026.1.1.1")\n'
        "app = BUNDLE(exe, name='Esimerkki.app')\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit):
        bump.edits(member, "2026.1.1.2")

    assert '"2026.1.1.1"' in (member / "pyproject.toml").read_text(encoding="utf-8")
    assert '"2026.1.1.1"' in (
        member / "src" / "esimerkki" / "__init__.py"
    ).read_text(encoding="utf-8")


def test_the_places_it_writes_are_the_places_the_agreement_test_reads():
    """Nostoskripti ja väitetesti eivät saa etsiä versiota eri kaavalla."""
    agreement = (ROOT / "tests" / "test_workspace_agrees.py").read_text(encoding="utf-8")
    for pattern in (bump.VERSION_IN_INIT, bump.VERSION_IN_SPEC):
        bare = pattern.replace("(?m)", "")
        assert bare in agreement, bare


def test_the_script_only_offers_real_members(capsys):
    names = set(bump.members())
    assert names == {"automixer", "autoraffkat", "podcast-magic", "speechmix"}
    for member in bump.members().values():
        assert re.match(r"^\d{4}\.\d{1,2}\.\d{1,2}\.\d+$", bump.current_version(member))
