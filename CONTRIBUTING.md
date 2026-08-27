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
uv run --directory apps/autoraffkat pytest -q
uv run --directory apps/automixer   pytest -q
uv run --directory apps/podcast-magic pytest -q
uv run pytest packages/speechmix/tests -q
uv run ruff check .
```

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

* **Red-green.** The failing test comes first. If the fix is already
  written, restore the old behaviour and watch the test fail before
  believing it.
* **Lint passes.** `uv run ruff check .` before committing. A rule that
  does not fit gets a written reason in `ignore`, never a bare `# noqa`.
* **CalVer**, `YYYY.M.D.N`, per app. Tags carry the app's name —
  `autoraffkat-v2026.8.28.1`, not `v2026.8.28.1` — because three apps now
  share one tag space and a bare `v*` would match any of them. The release
  workflow keys off that prefix.
* **Workflows live in the repo root.** GitHub only runs `.github/workflows`
  at the top level, so a workflow left inside `apps/<name>/.github/` is an
  inert file that looks like a working pipeline. autoraffkat's release build
  is `build-autoraffkat.yml`; podcast-magic still has a `build_app.py` and
  no workflow, which is a gap rather than a decision.
* **Numbers in comments.** A constant that came from a measurement says
  what was measured. The bugs here are silent — valid output, clean
  import, no exception, wrong result — and the number is what lets the
  next reader tell an improvement from a regression.
