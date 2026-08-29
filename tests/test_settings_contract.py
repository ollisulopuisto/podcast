"""Mitä kirjasto lukee isännän asetusoliosta, ja antavatko isännät sen.

`chain.process`, `masks.duck_masks` ja `envelopes.duck_envelopes` ovat
ankkatyypitettyjä: ne lukevat nimiä oliosta jota ne eivät itse määrittele.
Sopimus on siis olemassa muttei kirjoitettuna mihinkään, ja jokainen isäntä
rakentaa oman luokkansa — `AudioSettings`, `SpeechSettings`, `DuckSettings`.

Sopimus rikkoutui kahdesti saman päivän aikana: kirjastoon lisättiin
`duck_min_gap`, ja se kaatui `AttributeError`iin isännissä joiden luokassa
kenttää ei ollut. Kumpikaan ei ollut kirjoitusvirhe — kumpikin oli se että
lisääjä ei nähnyt keitä muita sopimus koskee.

Vaatimuslista **luetaan lähteestä** eikä ylläpidetä käsin. Käsin ylläpidetty
lista ajautuisi juuri kuten sopimuskin, ja hiljaa: se näyttäisi vartioivan
jotain jota se ei enää vartioi.
"""

import ast
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
LIB = ROOT / "packages" / "speechmix" / "src" / "speechmix"

# Isännän luokka -> ne kirjaston moduulit joiden lukemat sen on täytettävä.
# Rekisteri on tahallisesti käsin kirjoitettu ja lyhyt: se on ainoa kohta
# joka tietää **kuka** sopimusta käyttää, eikä sitä voi lukea lähteestä.
# Väärä nimi kaatuu tuontiin, eli virhe ei jää hiljaiseksi.
CONSUMERS = [
    ("autoraffkat", "autoraffkat.model", "AudioSettings",
     ("chain", "masks", "envelopes")),
    ("automixer", "automixer.domain.processor", "SpeechSettings", ("chain",)),
    ("automixer", "automixer.domain.room", "DuckSettings", ("masks", "envelopes")),
]


def _reads(module: str) -> tuple[set[str], set[str]]:
    """``(pakolliset, valinnaiset)`` yhden kirjastomoduulin lähteestä."""
    text = (LIB / f"{module}.py").read_text(encoding="utf-8")
    optional = set(re.findall(r'getattr\(settings,\s*"([a-z_]+)"', text))
    direct = set(re.findall(r"settings\.([a-z_]+)", text))
    return direct - optional, optional


def _fields(module: str, name: str) -> set[str]:
    """Luokan kentät ilman tuontia: `model.py` vetäisi mukanaan koko sovelluksen."""
    for app in ("autoraffkat", "automixer", "podcast-magic"):
        base = ROOT / "apps" / app / "src"
        path = base / (module.replace(".", "/") + ".py")
        if path.exists():
            break
    else:
        pytest.fail(f"moduulia ei löydy: {module}")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == name:
            return {
                item.target.id
                for item in node.body
                if isinstance(item, ast.AnnAssign)
                and isinstance(item.target, ast.Name)
            }
    pytest.fail(f"luokkaa ei löydy: {module}.{name}")


def test_the_library_reads_something_from_the_settings():
    """Jos tämä tyhjenee, testi on lakannut vartioimasta mitään."""
    required = set()
    for module in ("chain", "masks", "envelopes"):
        required |= _reads(module)[0]
    assert len(required) >= 10, sorted(required)


@pytest.mark.parametrize(
    ("app", "module", "name", "groups"),
    CONSUMERS,
    ids=[f"{a}:{n}" for a, _, n, _ in CONSUMERS],
)
def test_every_consumer_provides_what_the_library_reads(app, module, name, groups):
    """Isännän luokassa on jokainen nimi jota kirjasto lukee suoraan."""
    required = set()
    for group in groups:
        required |= _reads(group)[0]
    missing = sorted(required - _fields(module, name))
    assert not missing, f"{module}.{name} puuttuu kirjastolle: {missing}"


@pytest.mark.parametrize(
    ("app", "module", "name", "groups"),
    CONSUMERS,
    ids=[f"{a}:{n}" for a, _, n, _ in CONSUMERS],
)
def test_optional_reads_are_the_ones_a_consumer_may_skip(app, module, name, groups):
    """`getattr`illa luettu saa puuttua — mutta vain se.

    Ero on koko sopimus: suoraan luettu kaataa isännän, `getattr`illa luettu
    ottaa kirjaston oletuksen. Tämä testi ei vaadi valinnaisia kenttiä, vaan
    varmistaa ettei niitä ole vahingossa **myös** suorassa listassa — silloin
    oletus olisi kirjoitettu mutta tavoittamattomissa.
    """
    for group in groups:
        direct, optional = _reads(group)
        both = direct & optional
        assert not both, f"{group}: sekä suoraan että getattrilla: {sorted(both)}"
