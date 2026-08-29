"""Kaksi toteutusta, yksi vastaus.

`viewer/` on NHSX Viewer ja sen Quick Look -laajennus: Swiftiä, koska macOS-laajennus ei voi
olla muuta, eikä se jaa tämän kanssa riviäkään koodia. Se lukee saman
`.nhsx`:n ja päättelee saman miksauksen — omalla jäsentimellään, omalla
kielellään.

Kaksi toteutusta samasta formaatista on täsmälleen se tilanne, jota vastaan
tämä repositorio on olemassa. Erona on, että tätä ei voi ratkaista
jakamalla koodi: laajennus ei voi käynnistää Pythonia. Mitä voi jakaa, on
**vastaus**: yksi istunto, jonka suunnitelma on kirjoitettu muistiin, ja
jota molemmat toteutukset testaavat itseään vasten.

`viewer/Conformance/session.nhsx` on istunto ja `plan.json` sen vastaus.
Sama pari on `viewer/Tests`in luettavana. Jos nämä eroavat, esikatselu
näyttää eri jakson kuin `nhsx-render` renderöi — eikä kumpikaan kaadu.

Vastaus on **käsin tarkistettu**, ei koneen kirjaama. Uudelleenluonti on
tahallinen teko (`--conformance` uudestaan tiedostoon) ja sen diffi
luetaan: muuttunut luku on joko korjaus tai regressio, eikä sitä erota
muuten kuin katsomalla.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from podcastmagic import nhsx
from podcastmagic.nhsx import cli

CONFORMANCE = Path(__file__).resolve().parents[3] / "viewer" / "Conformance"
SESSION = CONFORMANCE / "session.nhsx"
PLAN = CONFORMANCE / "plan.json"

# Poolin tiedostot, jotka istunto mainitsee. Ne tehdään testissä eikä
# säilytetä levyllä: suunnitelma ei lue ääntä, se vain tarkistaa että
# tiedosto on olemassa. Tyhjä tiedosto riittää, ja repositorio pysyy
# tekstinä.
POOL = ("olli.wav", "panu.wav", "musiikki.wav")


@pytest.fixture
def staged(tmp_path):
    """Istunto ja sen pooli väliaikaishakemistoon."""
    shutil.copy(SESSION, tmp_path / "session.nhsx")
    for name in POOL:
        (tmp_path / name).write_bytes(b"")
    return tmp_path / "session.nhsx"


def expected() -> dict:
    return json.loads(PLAN.read_text(encoding="utf-8"))


def test_the_fixture_and_its_answer_are_both_here():
    """Puuttuva fikstuuri tekisi alla olevista testeistä tyhjiä."""
    assert SESSION.is_file()
    assert PLAN.is_file()


def test_this_implementation_produces_the_agreed_plan(staged):
    """Tämä on se testi. Swift-puolella on sen kaksonen."""
    got = cli.conformance_dict(nhsx.mix.plan(nhsx.read(str(staged))))
    assert got == expected()


def test_the_answer_covers_every_decision_the_session_was_built_to_test(staged):
    """Fikstuuri, joka ei erota mitään, on vihreä testi joka ei tarkista mitään.

    Jokainen väite tässä vastaa yhtä `session.nhsx`:n kommentoitua kohtaa.
    Ne ovat päällekkäisiä ylläolevan kanssa tarkoituksella: jos vastaus
    luodaan joskus uudestaan väärästä koodista, tämä kertoo *mikä* päätös
    muuttui eikä vain että tiedostot eroavat.
    """
    plan = expected()
    clips = plan["clips"]

    # Ohjelman pituus tulee kaikista alueista, myös vaimennetusta raidasta.
    assert plan["duration"] == 40.0
    # `Muted="True"`, `Muted="1"` ja vaimennettu raita — kolme eri tapaa.
    assert plan["muted"] == 3
    # Tuntematon attribuutti kerrotaan.
    # Tuntematon attribuutti kerrotaan — myös häivytyksen sisällä. Juuri
    # se puuttui, ja siksi «häivytyksiä ei lueta lainkaan» oli näkymätön.
    assert plan["unknown"] == {"Volyymi": 1, "Fade/Kayra": 1}
    # Nollan mittainen alue ei ole leike.
    assert len(clips) == 7
    # Leikkeet ohjelmajärjestyksessä.
    assert [c["start"] for c in clips] == sorted(c["start"] for c in clips)

    by_start = {c["start"]: c for c in clips}

    # Tiedostoaika ja ohjelma-aika ovat eri asia.
    assert by_start[2.0]["file_offset"] == 30.0
    # Sama tiedosto toisen kerran, eri kohdasta.
    assert by_start[12.0]["file_offset"] == 120.5
    assert by_start[2.0]["file"] == by_start[12.0]["file"]
    # Raidan ja alueen vahvistus kertautuvat: −6,02 dB × −6,02 dB = 0,25.
    assert by_start[1.0]["gain"] == 0.25
    # Raidan panorointi siirtää alueen omaa: 0,1 + 0,2.
    assert by_start[1.0]["pan"] == 0.3
    # Kaksoispistemuotoinen aika luetaan.
    assert by_start[14.0]["length"] == 2.5
    assert by_start[14.0]["file_offset"] == 5.25
    # Panorointi kanavakertoimina: laki on lineaarinen ja vakiosummainen,
    # ja **positiivinen on vasen**. Pelkkä `pan` ei erottaisi lakia.
    assert (by_start[1.0]["left"], by_start[1.0]["right"]) == (0.65, 0.35)
    assert (by_start[0.0]["left"], by_start[0.0]["right"]) == (0.25, 0.75)
    for clip in clips:
        assert clip["left"] + clip["right"] == 1.0
    # `ClipGain` voittaa `Gain`in eikä laske sen kanssa yhteen: −12,04 dB
    # antaa 0,25, kun summa −18,06 dB antaisi 0,125.
    assert by_start[20.0]["gain"] == 0.25
    # Luiska päätyy `Gain`iinsa eikä hiljaisuuteen, ja jää sinne.
    assert by_start[0.0]["ramps"] == [
        {"start": 0.0, "length": 1.5, "gain": 0.5},
        {"start": 7.0, "length": 3.0, "gain": 1.0},
    ]
    # Leikettä pidempi luiska katkeaa alueen loppuun, ei kutistu.
    assert by_start[30.0]["ramps"] == [{"start": 0.0, "length": 1.0, "gain": 0.0}]


def test_the_agreed_plan_carries_a_version(staged):
    """Esikatselu kieltäytyy muodosta jota se ei tunne, ei arvaa sitä."""
    del staged
    assert expected()["version"] == cli.PLAN_VERSION


def test_no_machine_specific_path_leaks_into_the_shared_answer(staged):
    """Absoluuttinen polku on sen koneen oma jolla testi ajettiin.

    Ennen tämä kielsi kauttaviivan koko tiedostosta, mikä on eri väite kuin
    se jota tarkoitettiin: `unknown` erottaa elementin ja attribuutin
    kauttaviivalla (`Fade/Kayra`), eikä sillä ole polkujen kanssa mitään
    tekemistä. Tarkistetaan siis se mitä tarkoitetaan.
    """
    got = cli.conformance_dict(nhsx.mix.plan(nhsx.read(str(staged))))
    blob = json.dumps(got)
    assert str(staged.parent) not in blob
    for clip in got["clips"]:
        assert "/" not in clip["file"]
        assert not clip["file"].startswith("/")


def test_every_clip_has_the_fields_the_previewer_reads(staged):
    """Käsin kirjoitettu kenttäluettelo, sama vartija kuin tunnisteella.

    Kenttä, joka katoaa huomaamatta, on esikatselu joka lakkaa panoroimasta
    ilman että kukaan huomaa.
    """
    got = cli.conformance_dict(nhsx.mix.plan(nhsx.read(str(staged))))
    for clip in got["clips"]:
        assert set(clip) == {
            "file", "speaker", "start", "length", "file_offset",
            "gain", "pan", "left", "right", "ramps",
        }
    assert set(got) == {"version", "duration", "muted", "unknown", "speakers", "clips"}
