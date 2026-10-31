# Where the work happens

**This repo is the source of truth.** The four apps live here — three under
`apps/`, and `colab-transcribe` at the root, because its chain runs on a
Colab GPU and cannot import the workspace (`colab-transcribe/CLAUDE.md`).
The pipeline the macOS apps share lives under `packages/speechmix`.

The three standalone repos — `ollisulopuisto/autoraffkat`, `automixer`,
`podcast-magic` — are where these projects came from. They are kept for
their history and for anyone holding an old clone. Do not commit to them:
a change made there does not reach the other two apps, and divergence
between the three copies of the same pipeline is the exact problem this
repo exists to end. automixer was four measured audio fixes behind when it
was merged, and nobody noticed until someone measured.

## Working in one app

```
uv sync --all-packages
uv run ruff check .
uv run pytest tests -q                              # jäsenet ovat samaa mieltä
uv run --directory packages/speechmix pytest -q
uv run --directory apps/autoraffkat   pytest -q
uv run --directory apps/automixer     pytest -q
uv run --directory apps/fcp-subs-whisper pytest -q
uv run --directory apps/podcast-magic pytest -q
uv run --directory colab-transcribe   pytest -q
```

Sama muoto jokaiselle jäsenelle, myös `packages/speechmix`ille: se sai
`testpaths`in jota siltä puuttui, ja ilman sitä tuo rivi keräsi
`reference/`-hakemiston ja kaatui kokoamiseen.

ruff ja pytest tulevat juuren `dev`-ryhmästä. Ne eivät ole yhdenkään
sovelluksen riippuvuuksia: kiinnittämätön lintti on portti joka päästää läpi
eri asioita eri koneilla, ja `uv run ruff` ilman asennusta hakee ohjelman
PATHista — kehityskoneelta se löytyy, CI-ajurilta ei.

An app depends on the pipeline through the workspace, not through a
release:

```toml
[tool.uv.sources]
speechmix = { workspace = true }
```

so a change to `packages/speechmix` is visible to every app that imports it
in the same commit. That is the whole point — there is no version to bump
and no window in which the apps disagree about what the chain does. The
exception proves the shape: colab-transcribe stands outside it, and its
Colab script picks up a change to the chain only when someone carries it
over by hand.

## Rules

Ne ovat **`CLAUDE.md`**:ssä, yhdessä paikassa: punavihreä, kiinnitetty
lintti, CalVer sovelluskohtaisesti, työnkulut juuressa, mittausluvut
kommenteissa. `tests/` väittää koneellisesti tarkistettavat niistä ja
kaatuu kun ne lakkaavat pitämästä paikkaansa.

Versionosto:

```
uv run python scripts/bump_version.py autoraffkat
git tag autoraffkat-v2026.8.28.1
```

Tagi käynnistää sovelluksen julkaisuputken. Autoraffkat ja podcast-magic
paketoidaan omilla `build-<sovellus>.yml`-työnkuluillaan; viewerillä on omansa.
`automixer-v*` ja `colab-transcribe-v*` käynnistävät `build-cli.yml`in, joka
pakkaa sovelluksen ja sen työtilakirjastot samasta commitista sekä kiinnittää
muut riippuvuudet lukosta. PR:t ja käsiajot tarkistavat paketoinnin julkaisematta.
Asennus, Kuulas-polut ja julkaisuohje: [CLI-RELEASES.md](docs/CLI-RELEASES.md).

`tests-linux.yml` runs the portable workspace and application suites. The
macOS `tests.yml` repeats only the suites that need Apple frameworks, Metal,
or macOS application behavior, alongside the workspace agreement check.
This avoids spending macOS minutes on the same portable tests twice.

Pull requests and pushes select member suites from changed paths. An app edit
runs that app's suite on its supported runners; a shared-library edit runs the
library suite and its consuming apps. The macOS job is skipped entirely when
no macOS suite is selected. Workspace contracts and lint still run for every
change. Documentation-only edits skip member suites. A manual test workflow
dispatch still runs every suite.

For an urgent installer check, `build-autoraffkat.yml` and
`build-podcast-magic.yml` can be dispatched manually with **hotfix artifact**
enabled. That skips only the build workflow's test suite and uploads an
artifact; it cannot publish a GitHub Release. Tag-triggered releases always
run tests.

## Feature Roadmaps & Ideas

Looking for a high-impact feature to contribute?
- **`autoraffkat`**: Adding multi-NLE support (DaVinci Resolve and Adobe Premiere Pro) — see [`apps/autoraffkat/ROADMAP.md`](apps/autoraffkat/ROADMAP.md).
- **New app idea**: LLM-suggested transcript cuts, written back as paired begin/end `<Marker>`s in a new Hindenburg XML — rules for what's removable still TBD, see [`docs/plans/2026-09-21-transcript-cut-suggester.md`](docs/plans/2026-09-21-transcript-cut-suggester.md).
