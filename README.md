# podcast

Three tools that share one speech-mixing pipeline.

| | what it reads | what it produces |
|---|---|---|
| `apps/autoraffkat` | Final Cut FCPXML | FCPXML, the picture cut to whoever is talking |
| `apps/automixer` | its own session config | a rendered podcast mix |
| `apps/podcast-magic` | *(another session format)* | *(tbd)* |

`packages/speechmix` is the pipeline itself. It turns samples into other
samples and knows nothing about any session format — see its README for the
seam and `SHARED-AUDIO.md` for the measurements behind every stage.

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
