"""Työtilan jäsenten on oltava samaa mieltä, ja tämä sanoo milloin ne eivät ole.

Tämä repositorio on olemassa siksi, että kolme kopiota samasta ketjusta
ajautui erilleen eikä kukaan huomannut ennen kuin joku mittasi. Sama ajautuminen
tapahtuu työkaluille yhtä hiljaa: eri ruff näkee eri virheet, eri numpy-alaraja
on lupaus jota ei aja mikään, ja kolmessa paikassa oleva versionumero on kolme
versionumeroa. Mikään näistä ei kaada mitään — ne vain tekevät portista
sellaisen, joka päästää läpi eri asioita eri koneilla.

Kirjoitettu punaisena: jokainen alla oleva väite kaatui tätä kirjoitettaessa
ainakin yhdellä jäsenellä.

Nämä testit lukevat `pyproject.toml`ia tekstinä eivätkä tuo yhtään pakettia.
Ne ajetaan juuresta: `uv run pytest tests -q`.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Jäsen on hakemisto jossa on `pyproject.toml`. Luettelo johdetaan levyltä
# eikä kirjoiteta tähän: uusi sovellus ei saa livahtaa mukaan ilman että
# nämä väitteet koskevat sitä. Ylätason `*/pyproject.toml` ottaa mukaan
# juuressa asuvat jäsenet — tällä hetkellä `colab-transcribe`, joka ei seiso
# `apps/`issa koska sen ketju ajaa Colabissa eikä se voi tuoda `speechmix`ia
# työtilasta (juuren `pyproject.toml` selittää miksi).
MEMBERS = sorted(
    {
        p.parent
        for p in [
            *ROOT.glob("apps/*/pyproject.toml"),
            *ROOT.glob("packages/*/pyproject.toml"),
            *ROOT.glob("*/pyproject.toml"),
        ]
    },
    key=lambda p: p.name,
)
# Sovellukset ovat kaikki muut paitsi jaettu paketti. Juuressa asuvan
# jäsenen vanhempi on työtilahakemisto itse, joten nimeen vetoaminen olisi
# parsittava koneeltta eikä sääntö.
APPS = [m for m in MEMBERS if m.parent.name != "packages"]

CALVER = re.compile(r"^\d{4}\.\d{1,2}\.\d{1,2}\.\d+$")


def toml(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def manifest(member: Path) -> dict:
    return toml(member / "pyproject.toml")


def name(member: Path) -> str:
    return member.name


@pytest.fixture(scope="module")
def root() -> dict:
    return toml(ROOT / "pyproject.toml")


def test_the_members_are_the_five_we_think_they_are():
    """Sattumalta tyhjä luettelo tekisi jokaisesta alla olevasta testin joka ei testaa mitään.

    colab-transcribe on jäsen vaikka ei ole `apps/`issa — se on juuressa
    `viewer/`in tapaan, mutta pyproject.tomlilla, ja listattu eksplisiittisesti
    juuren `[tool.uv.workspace]`iin.
    """
    assert [name(m) for m in MEMBERS] == [
        "automixer",
        "autoraffkat",
        "colab-transcribe",
        "podcast-magic",
        "speechmix",
    ]


# --------------------------------------------------------------------------
# Python
# --------------------------------------------------------------------------


def test_every_member_wants_the_same_python():
    """Yksi lukitustiedosto ja yksi ympäristö: eri alaraja ei ole eri tuki.

    Ennen tätä automixer vaati `>=3.13` ja kolme muuta `>=3.11`. Mikään ei
    ajanut 3.11:tä — ei CI, ei kehityskone, ei paketointi — joten se oli
    väite jota ei voinut rikkoa eikä pitää.
    """
    wanted = {name(m): manifest(m)["project"]["requires-python"] for m in MEMBERS}
    assert len(set(wanted.values())) == 1, wanted


def test_the_python_they_want_is_the_python_the_workspace_pins(root):
    """`.python-version` ratkaisee lukituksen, joten se on se numero jota testataan."""
    pinned = (ROOT / ".python-version").read_text(encoding="utf-8").strip()
    wanted = manifest(MEMBERS[0])["project"]["requires-python"]
    assert wanted == f">={pinned}", (wanted, pinned)

    # ruffin target-version on sama luku ilman pistettä: py313.
    target = root["tool"]["ruff"]["target-version"]
    assert target == "py" + pinned.replace(".", ""), (target, pinned)


# --------------------------------------------------------------------------
# Kirjastot
# --------------------------------------------------------------------------


def requirements(member: Path) -> dict[str, str]:
    """Riippuvuudet nimestä koko määreeseen, ilman lisiä."""
    out = {}
    for spec in manifest(member)["project"].get("dependencies", []):
        pkg = re.split(r"[<>=!~\[; ]", spec, maxsplit=1)[0]
        out[pkg] = spec
    return out


def test_a_shared_library_has_one_floor():
    """Kahden jäsenen jakama kirjasto ei saa olla kahta eri kirjastoa.

    Työtila asentaa yhden version joka tapauksessa, joten eri alaraja ei
    tuota eri kirjastoa — se tuottaa väärän käsityksen siitä, mikä on
    testattu. Ennen tätä numpy oli `>=1.26` kolmessa ja `>=2.4.2` yhdessä,
    ja lukitus ratkaisi 2.5.2:n kaikille.
    """
    seen: dict[str, dict[str, str]] = {}
    for member in MEMBERS:
        for pkg, spec in requirements(member).items():
            seen.setdefault(pkg, {})[name(member)] = spec

    disagreeing = {
        pkg: who for pkg, who in seen.items() if len(who) > 1 and len(set(who.values())) > 1
    }
    assert not disagreeing, disagreeing


# --------------------------------------------------------------------------
# Työkalut
# --------------------------------------------------------------------------


def test_only_the_workspace_root_configures_ruff():
    """ruff lukee lähintä lohkoa, joten jäsenen oma lohko korvaa juuren.

    Kaksi melkein samanlaista sääntölistaa on kaksi eri porttia. Poikkeus
    kirjoitetaan juuren `per-file-ignores`iin polkuna.
    """
    offenders = [name(m) for m in MEMBERS if "ruff" in manifest(m).get("tool", {})]
    assert not offenders, offenders


def test_the_toolchain_is_declared_once(root):
    """Lintti ja testiajuri ovat työtilan työkaluja, eivät sovellusten.

    pytest oli ennen tätä automixerin **ajonaikainen** riippuvuus,
    autoraffkatin `dev`-lisä ja podcast-magicin `dev`-ryhmä — kolmella eri
    alarajalla, joista mikään ei ollut se joka asennettiin.
    """
    shared = {"ruff", "pytest"}
    in_root = {
        re.split(r"[<>=!~ ]", spec, maxsplit=1)[0]
        for spec in root["dependency-groups"]["dev"]
    }
    assert shared <= in_root, in_root

    for member in MEMBERS:
        data = manifest(member)
        declared = set(requirements(member))
        for group in data.get("dependency-groups", {}).values():
            declared |= {re.split(r"[<>=!~ ]", s, maxsplit=1)[0] for s in group}
        for extra in data["project"].get("optional-dependencies", {}).values():
            declared |= {re.split(r"[<>=!~\[ ]", s, maxsplit=1)[0] for s in extra}
        assert not (shared & declared), (name(member), shared & declared)


def test_the_workspace_has_one_lockfile():
    """`apps/*/uv.lock` ei vaikuta mihinkään, ja juuri siksi se on vaarallinen.

    uv lukee vain juuren lukitusta. Jäsenen oma näyttää auktoritatiiviselta
    ja kertoo eri version kuin se joka oikeasti asennetaan.
    """
    strays = [str(p.relative_to(ROOT)) for m in MEMBERS if (p := m / "uv.lock").exists()]
    assert not strays, strays
    assert (ROOT / "uv.lock").exists()


def test_the_python_version_is_pinned_once():
    strays = [
        str(p.relative_to(ROOT)) for m in MEMBERS if (p := m / ".python-version").exists()
    ]
    assert not strays, strays


def test_every_member_configures_pytest_the_same_way():
    """Ilman `testpaths` pytest kerää koko hakemiston.

    speechmixiltä lohko puuttui, ja `uv run --directory packages/speechmix
    pytest` — se muoto jota CONTRIBUTING opettaa — keräsi kaiken mitä
    hakemistossa sattui olemaan ja kaatui kokoamiseen. Rajaus on se, mikä
    tekee ajosta saman riippumatta siitä mistä se käynnistetään.
    """
    for member in MEMBERS:
        options = manifest(member).get("tool", {}).get("pytest", {}).get("ini_options")
        assert options is not None, name(member)
        assert options.get("testpaths") == ["tests"], (name(member), options)
        assert options.get("pythonpath") == ["src"], (name(member), options)


# --------------------------------------------------------------------------
# Jaettu paketti
# --------------------------------------------------------------------------


def imports_in(path: Path) -> set[str]:
    """Jokainen `import`illa mainittu nimi, `ast`illa eikä grepillä.

    Kommentissa tai merkkijonossa mainittu moduulin nimi ei ole kuluttaja,
    ja juuri se ero on tässä koko kysymys. Ottaa tiedoston tai hakemiston.
    """
    import ast

    sources = [path] if path.is_file() else sorted(path.rglob("*.py"))
    found: set[str] = set()
    for source in sources:
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    found.update(alias.name.split("."))
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    found.update(node.module.split("."))
                found.update(alias.name for alias in node.names)
    return found


def test_every_shared_module_has_a_consumer():
    """Kirjasto johon kirjoitetaan koodia jota mikään ei kutsu ei ole kirjasto.

    Se on sama kolme kopiota ketjusta, vain yhden hakemiston sisällä — ja se
    on tarkalleen se vika jonka takia tämä repositorio on olemassa. Viisi
    moduulia kertyi tänne ilman yhtäkään tuojaa (`ceiling`, `loudness`,
    `fingerprint`, `timeline`, `verify`), ja kaksi niistä oli toisinto
    koodista joka oli yhä autoraffkatin `mix.py`:ssä. `fingerprint` oli oman
    sisarensa `freshness` toisinto, eri `FINGERPRINT_VERSION`illa (1 vastaan
    8) ja yhteensopimattomilla kenttänimillä — kaksi eri vastausta siihen
    mikä tekee välimuistista vanhentuneen.

    Mikään niistä ei kaatanut mitään. Ne vain olivat.

    `__init__.py` ei kelpaa kuluttajaksi: se tuo kaiken julkisen, joten sen
    laskeminen tekisi tästä testin joka ei voi koskaan kaatua.
    """
    package = ROOT / "packages" / "speechmix" / "src" / "speechmix"
    modules = {p.stem for p in package.glob("*.py")} - {"__init__"}

    from_apps = imports_in(ROOT / "apps")
    siblings = {
        sibling.stem: imports_in(sibling)
        for sibling in package.glob("*.py")
        if sibling.stem != "__init__"
    }

    orphans = sorted(
        module
        for module in modules
        if module not in from_apps
        and not any(module in names for stem, names in siblings.items() if stem != module)
    )
    assert not orphans, orphans


    assert not orphans, orphans





def declared_version(member: Path) -> str:
    return manifest(member)["project"]["version"]


@pytest.mark.parametrize("member", MEMBERS, ids=name)
def test_the_version_is_calver(member: Path):
    """CalVer, `YYYY.M.D.N`, kuten työskentelysäännöt sanovat."""
    assert CALVER.match(declared_version(member)), (name(member), declared_version(member))


def package_dir(member: Path) -> Path:
    (found,) = (member / "src").iterdir()
    return found


@pytest.mark.parametrize("app", APPS, ids=name)
def test_the_running_program_reports_the_version_that_was_built(app: Path):
    """`__version__` on se numero jonka käyttäjä näkee, ja sen pitää olla sama.

    autoraffkatilla oli tätä kirjoitettaessa kolme: `pyproject.toml`
    2026.8.27.113, `__version__` 2026.8.26.95 ja `.spec` 2026.8.22.49.
    Yksikään niistä ei kaada mitään.
    """
    init = (package_dir(app) / "__init__.py").read_text(encoding="utf-8")
    literal = re.search(r'^__version__ = "(.+)"$', init, re.M)
    if literal is None:
        # Johdettu asennuksesta (`importlib.metadata`) — ei voi ajautua.
        assert "importlib.metadata.version" in init, name(app)
        return
    assert literal.group(1) == declared_version(app), name(app)


def bundle_specs(app: Path) -> list[Path]:
    """`.spec`it, jotka kokoavat `.app`-paketin.

    Sovelluksella voi olla useampi `.spec`: `podcast-magic` paketoi sekä
    ikkunallisen sovelluksen että `nhsx-render`in yhtenä binäärinä. Vain
    edellisellä on `Info.plist` ja siten `CFBundleVersion`, ja alla oleva
    sääntö koskee juuri sitä.

    `BUNDLE(` on ero, koska se on se PyInstallerin kutsu joka `.app`in
    tekee — ei tiedoston nimi, joka voi olla mitä tahansa.
    """
    return [
        spec for spec in sorted(app.glob("*.spec"))
        if "BUNDLE(" in spec.read_text(encoding="utf-8")
    ]


@pytest.mark.parametrize("app", [a for a in APPS if bundle_specs(a)], ids=name)
def test_the_bundle_reports_the_version_that_was_built(app: Path):
    """macOS tarjoaa päivitystä `CFBundleVersion`in perusteella.

    Jos se jää jälkeen, Finderin tiedot ja käyttöliittymä kertovat eri
    versiota eikä kumpikaan kaada mitään.

    Väite oli aiemmin `(spec,) = app.glob("*.spec")`, eli «sovelluksella on
    täsmälleen yksi `.spec`». Se lakkasi pitämästä paikkaansa kun
    `podcast-magic` sai toisen: `nhsx-render.spec` paketoi komentorivi-
    työkalun yhtenä binäärinä. Sääntö itse ei muuttunut — se on
    `CFBundleVersion`ista eikä `.spec`ien lukumäärästä — joten se rajattiin
    sinne minne se kuuluu.
    """
    for spec in bundle_specs(app):
        text = spec.read_text(encoding="utf-8")
        found = re.search(r'os\.environ\.get\("[A-Z_]+VERSION", "(.+?)"\)', text)
        assert found, f"{name(app)}/{spec.name}: ei lue versiota ympäristöstä oletuksineen"
        assert found.group(1) == declared_version(app), f"{name(app)}/{spec.name}"


@pytest.mark.parametrize("app", APPS, ids=name)
def test_a_plain_binary_spec_carries_no_version_of_its_own(app: Path):
    """Neljäs paikka samalle numerolle olisi neljäs paikka joka jää jälkeen.

    Paketoitu komentorivityökalu kertoo versionsa paketista
    (`podcastmagic.__version__`, `--version`), eikä sillä ole `Info.plist`ia
    johon numero kirjoitettaisiin. Jos sellaiseen `.spec`iin joskus
    ilmestyy oma versio, se on kopio jota kukaan ei nosta.
    """
    for spec in sorted(app.glob("*.spec")):
        if spec in bundle_specs(app):
            continue
        text = spec.read_text(encoding="utf-8")
        assert not re.search(r'os\.environ\.get\("[A-Z_]+VERSION"', text), (
            f"{name(app)}/{spec.name}: ei-paketoiva .spec ei saa kantaa omaa versiotaan"
        )


@pytest.mark.parametrize("app", [a for a in APPS if list(a.glob("*.spec"))], ids=name)
def test_a_packaged_app_has_a_release_workflow(app: Path):
    """Paketoitavalla sovelluksella on putki, ja se on juuressa.

    GitHub ajaa vain ylätason `.github/workflows`. Sovelluksen sisällä
    oleva työnkulku on inertti tiedosto joka näyttää toimivalta putkelta.
    Tagi kantaa sovelluksen nimen, koska kolme sovellusta jakaa yhden
    tagiavaruuden ja pelkkä `v*` osuisi mihin tahansa niistä.
    """
    workflow = ROOT / ".github" / "workflows" / f"build-{name(app)}.yml"
    assert workflow.exists(), str(workflow.relative_to(ROOT))
    text = workflow.read_text(encoding="utf-8")
    assert f'"{name(app)}-v*"' in text, name(app)


@pytest.mark.parametrize("app", [a for a in APPS if list(a.glob("*.spec"))], ids=name)
def test_a_release_workflow_syncs_the_whole_workspace(app: Path):
    """Paketointi asentaa työtilan, ei yhtä jäsentä.

    `uv sync` jäsenen hakemistossa asentaa vain sen jäsenen — jaettu
    työkalusto (pytest, ruff) on juuren `dependency-groups`issa, joten
    testiaskel kaatuu «Failed to spawn: pytest» eikä pakettia synny. Sama
    komento poistaa muiden jäsenten riippuvuudet samasta ympäristöstä.

    Molemmat paketointiputket kaatuivat tähän ensimmäisellä ajollaan, eli
    kumpikaan ei ollut koskaan ajanut loppuun.
    """
    text = (ROOT / ".github" / "workflows" / f"build-{name(app)}.yml").read_text(encoding="utf-8")
    syncs = [line.strip() for line in text.splitlines()
             if "uv sync" in line and line.lstrip().startswith("run:")]
    assert syncs, name(app)
    for line in syncs:
        assert "--all-packages" in line, f"{name(app)}: {line}"


def test_no_workflow_is_hidden_inside_an_app():
    strays = [str(p.relative_to(ROOT)) for p in ROOT.glob("apps/*/.github/workflows/*")]
    assert not strays, strays
