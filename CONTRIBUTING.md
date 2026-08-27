# Where the work happens

**This repo is the source of truth.** All three apps live here, under
`apps/`, and so does the pipeline they share, under `packages/speechmix`.

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
uv run --directory apps/podcast-magic pytest -q
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

so a change to `packages/speechmix` is visible to all three apps in the
same commit. That is the whole point — there is no version to bump and no
window in which the apps disagree about what the chain does.

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

Tagi käynnistää `build-<sovellus>.yml`in. Paketoitavia sovelluksia on kaksi
(autoraffkat, podcast-magic); automixer on komentorivityökalu eikä sillä ole
`.spec`iä, joten sillä ei ole julkaisuputkeakaan.
