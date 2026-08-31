# Working in this repo

Four apps. Three of them share one pipeline; the fourth drives the same job
on a Colab GPU, where the workspace cannot be imported — so its script is a
snapshot that does not follow changes to `packages/speechmix` automatically,
and `colab-transcribe/CLAUDE.md` is the place that risk is written down.
`README.md` says what each one is; this file says how work is done in all of
them, and it is the only place that says it. `CONTRIBUTING.md` covers the
commands and the migration story.

Each app has its own `CLAUDE.md` with what is true about *that* app — the
FCPXML time base, the `.nhsx` word clock, the mlx chain. Those are domain
knowledge. Nothing below is repeated in them, and nothing below may be
contradicted by them.

## The rules

* **Red-green.** The failing test comes first. When the fix is already
  written, restore the old behaviour and watch the test fail before believing
  it. A test that has never been red is a test that has never been checked.
  Nothing is committed or presented whose tests are not green; where an area
  has no tests, writing them is part of the change.
* **Lint is strict, pinned, and passes.** Every change runs `uv run ruff
  check .` and fixes *all* findings before it is considered done — green
  tests and clean lint together, or it is not finished. CI runs it ahead of
  the tests. One config, at the root — a `[tool.ruff]` block in an app
  *replaces* the root one rather than adding to it, which is how two
  nearly-identical rule lists start drifting apart. A rule that does not fit
  gets a written reason in `ignore` or `per-file-ignores`, never a bare
  `# noqa`.
* **The members agree.** One Python floor, one specifier per shared library,
  one lockfile, one dev toolchain, one pytest config shape. `tests/` asserts
  all of it and fails when it stops being true. If a change has to break one
  of those assertions, change the assertion in the same commit and say why.
* **CalVer**, `YYYY.M.D.N`, per app, bumped with
  `uv run python scripts/bump_version.py <app>`. The number lives in three
  places for a packaged app and all three must match — macOS decides whether
  to offer an update from `CFBundleVersion` alone, so a stale one fails by
  doing nothing. Tags carry the app's name (`autoraffkat-v2026.8.28.1`), and
  the release workflow keys off that prefix.
* **Workflows live in the repo root.** GitHub only runs `.github/workflows`
  at the top level. A workflow inside `apps/<name>/.github/` is an inert file
  that looks like a working pipeline; there were two of those, and neither had
  ever run.
* **Numbers in comments.** A constant that came from a measurement says what
  was measured. The bugs here are silent — valid output, clean import, no
  exception, wrong result — and the number is what lets the next reader tell
  an improvement from a regression. `SHARED-AUDIO.md` collects them.
* **CI does not skip.** No `continue-on-error`, and a skipped test is a green
  test: where a test can skip for a missing runner tool, CI checks separately
  that it actually ran.

## What the shape is for

The apps that process audio depend on `packages/speechmix` through the
workspace, not through a release, so a change to the pipeline reaches every
one of them in the same commit. There is no version to bump and no window in
which they disagree about what the chain does. That is the whole point:
three copies of this pipeline drifted apart once already, and automixer was
four measured audio fixes behind when it was merged.

colab-transcribe is the shape's standing demonstration of the cost of
standing outside it: its Colab script is a copy that no commit reaches, so
every measured fix lands there only when someone carries it over.

The same reasoning is why the toolchain is shared and asserted. An unpinned
linter, a per-app lockfile or a second ruff config is the same failure in a
different file — nothing breaks, the parts just quietly stop being the same
thing.
