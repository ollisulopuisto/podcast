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

## Working rules

Red-green, one pinned linter, CalVer per app, and numbers in the comments —
**`CLAUDE.md`** carries them, for people and agents alike, and `tests/`
asserts the ones a machine can check. `CONTRIBUTING.md` has the commands.
