# podcast

Three tools that share one speech-mixing pipeline.

| | what it reads | what it produces |
|---|---|---|
| `apps/autoraffkat` | Final Cut FCPXML | FCPXML, the picture cut to whoever is talking |
| `apps/automixer` | its own session config | a rendered podcast mix |
| `apps/podcast-magic` | Hindenburg `.nhsx` | transcription, and everything nobody says muted |

Three session formats, one pipeline. The thing they have in common is not
the file — it is **tracks placed on a programme timeline**, which `.fcpxml`,
`.nhsx` and automixer's config all describe in their own words.

`packages/speechmix` is the pipeline itself. It turns samples into other
samples and knows nothing about any session format — see its README for the
seam and `SHARED-AUDIO.md` for the measurements behind every stage.

## Running one of them

macOS, and [uv](https://docs.astral.sh/uv/). Install once from **this
directory** — the repository root — and then run whichever app you want:

```
brew install ffmpeg
uv sync --all-packages --extra mlx        # --extra faster on an Intel Mac

uv run podcast-magic ~/Podcast/episode8/  # Hindenburg: transcribe and mute
uv run autoraffkat                        # Final Cut: cut the picture
uv run automixer                          # render a mix
```

automixer is still mid-move into this repository — one test fails on the
workspace's mlx and CI carries it as declared debt — so treat that last line
as the one to check before relying on it.

**`uv sync` belongs at the root, with `--all-packages`.** The three apps and
the shared pipeline are members of one uv workspace over one environment, so:

* `uv sync` *inside* an app directory syncs that member and **uninstalls the
  other members'** dependencies from the shared environment;
* `uv sync --extra mlx` at the root installs **no engine** — the extra belongs
  to podcast-magic, not to the workspace, and nothing is said about it.

`uv run` does not care where you stand. Only `uv sync` does.

Each app's own README has the rest: `apps/podcast-magic/README.md`
([suomeksi](apps/podcast-magic/README.fi.md)), `apps/autoraffkat/README.md`,
`apps/automixer/README.md`.

## Working rules

* **Red-green.** The failing test comes first. When a fix is already written,
  restore the old behaviour and watch the test fail before believing it.
* **Lint is strict and passes.** `uv run ruff check .` before committing; CI
  runs it ahead of the tests. Rules that do not fit carry a written reason in
  `ignore`, never a bare `# noqa`.
* **CalVer**, `YYYY.M.D.N`, tagged per change.
* **Numbers in comments.** Every constant that came from a measurement says
  what was measured. This codebase's bugs are silent — valid output, clean
  import, no exception, wrong result — and the number is what makes the next
  reader able to tell.
