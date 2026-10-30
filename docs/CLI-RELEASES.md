# Pinned CLI releases / Kiinnitetyt komentorivijulkaisut

## English

GitHub Actions builds **automixer** and **colab-transcribe** on pull requests,
on manual request, and on their version tags. Pull requests and manual runs
produce downloadable Actions artifacts. Tags publish GitHub Releases only after
both macOS and Linux builds pass. Existing desktop app workflows remain the
release route for Autoraffkat, Podcast Magic and NHSX Viewer.

Each archive contains the app wheel, its transitive workspace library wheels
from the **same source commit**, third party requirements pinned from `uv.lock`,
`manifest.json` with versions, commit and SHA-256 checksums, and `install.py`.
Shared libraries keep their own versions; rebuilding includes their current code
even when their version has not changed. Install each release in a new environment
so cached libraries from another release cannot be reused accidentally.

These are Python wheel bundles with an **online installer**. They require uv,
network access for third party packages, and Git for colab-transcribe's
commit-pinned Google CLI dependency. Python 3.13 is selected by the installer;
uv can download it. The archives do not include model weights or system tools.
The local Parakeet extra is not included in this initial Colab driver release.

### Install a specific release

Install prerequisites on macOS: `brew install uv ffmpeg portaudio`.
For Linux, install uv, Python/Git as needed, and the runtime tools:
`sudo apt-get install ffmpeg libportaudio2 libsndfile1`.
macOS uses Apple Silicon for the MLX routes; Linux supports automixer's stems
route. Choose the archive matching your OS and architecture (`uname -sm`).

Select an exact tag from the repository's Releases page. For example, after
`automixer-v2026.10.27.1` has been published, its macOS installation is:

```sh
tag=automixer-v2026.10.27.1
asset=automixer-2026.10.27.1-darwin-arm64.tar.gz
mkdir "$tag"
cd "$tag"
gh release download "$tag" --repo ollisulopuisto/podcast \
  --pattern "$asset" --pattern "$asset.sha256"
shasum -a 256 -c "$asset.sha256"
mkdir bundle
tar -xzf "$asset" -C bundle
python3 bundle/install.py --venv "$HOME/.local/share/podcast/$tag"
"$HOME/.local/share/podcast/$tag/bin/automixer" --help
```

The release assets can also be downloaded in a browser; `gh` is optional.
Linux assets end in `linux-x86_64.tar.gz`. Use `sha256sum -c` there.
For transcription choose a `colab-transcribe-v...` tag and corresponding archive,
then run that environment's `bin/colab-transcribe --login` once. The installer
verifies bundled files and platform before creating the environment, and refuses
to overwrite an existing environment.

### Kuulas integration

Kuulas should run the absolute path to the selected environment's
`bin/automixer` or `bin/colab-transcribe`. Preserve its existing arguments and
event parsing. Updating consists of installing another exact release in another
directory, checking it, then changing the configured command path. Rollback
selects the previous directory. The bundles provide stable commands for this
configuration; this change does not modify the separate Kuulas repository.

If Kuulas imports `speechmix` or `nhsx`, install both wheels from the **same
automixer bundle** in its own environment using its package manager, rather than
mixing wheels from different releases. The standalone installer owns its entire
environment (`uv pip sync`) and must not target Kuulas's existing environment.
`manifest.json` identifies exactly which source commit those libraries contain.

The existing `run.sh` and source-based `uvx` commands still default to `main`.
Use a release bundle for a pinned production installation.

### Make a release

After merging the implementation, the integrator bumps the selected app with
`uv run python scripts/bump_version.py automixer` (or `colab-transcribe`), commits
the version changes and updated lockfile, and merges that change. On the merged
commit, create and push **only that app's tag**, matching its project version:

```sh
git tag automixer-vYYYY.M.D.N
git push origin automixer-vYYYY.M.D.N
```

`build-cli.yml` checks tag/version agreement, runs lint and workspace/app/library
tests, builds the wheels, installs the archive into a fresh environment outside
the checkout, verifies imports and uploaded Colab resources, and runs `--help`.
The release job waits for every platform build. It publishes archives and their
checksums; it does not bump versions, create tags, or publish to PyPI. A manual
Actions run can check an upcoming release without publishing it.

Locally build an archive with:

```sh
uv run python scripts/build_cli_release.py automixer
uv run python scripts/build_cli_release.py colab-transcribe
```

Installation checks exercise packaging and startup. They do not run a Colab GPU
session or establish podcast accuracy, and require no Google credentials.

## Suomeksi

GitHub rakentaa automixerin ja colab-transcriben PR:stä, käsin käynnistettäessä
ja version tagista. PR ja käsiajo tuottavat ladattavat artefaktit. Vain tagi
(`automixer-vYYYY.M.D.N` tai `colab-transcribe-vYYYY.M.D.N`) julkaisee GitHub
Releasen, kun macOS- ja Linux-ajot ovat läpäisseet tarkistukset.

Paketti sisältää sovelluksen ja sen työtilakirjastot samasta commitista,
`uv.lock`ista kiinnitetyt riippuvuudet, tarkistussummat ja asentimen. Asennus
tarvitsee uv:n ja verkkoyhteyden; mallit ja järjestelmätyökalut eivät sisälly
pakettiin. Colab-ajuri tarvitsee myös Gitin. Asennin valitsee Python 3.13:n ja
tarkistaa alustan sekä tiedostot ennen asennusta.

Lataa täsmällisen tagin oman alustasi arkisto ja `.sha256`, tarkista summa,
pura arkisto ja aja `python3 bundle/install.py --venv /uusi/ymparisto`.
Yllä oleva esimerkki näyttää komennot. Kuulas käyttää uuden ympäristön
`bin/automixer`- tai `bin/colab-transcribe`-polkua. Päivitykselle tehdään uusi
ympäristö; paluu vanhaan tarkoittaa vanhan polun valitsemista. Asennin hallitsee
koko ympäristöään, joten sitä ei ajeta Kuulaksen olemassa olevaan ympäristöön.
Kuulaksen suoraan tuomat `speechmix` ja `nhsx` otetaan samasta automixer-paketista.

Integroija nostaa sovelluksen version olemassa olevalla nostoskriptillä ja
puskee vain kyseisen sovelluksen tagin. Työnkulku ei muuta versionumeroita eikä
julkaise PyPI:hin. Kuulaksen erillisen repositorion asetukset päivitetään siellä.
