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

uv run nhsx-render "episode 8.nhsx"       # a Hindenburg session → a WAV
```

That last one is the odd member of the set: it is the only tool here that
exists for the day the program it reads for is gone. A `.nhsx` is XML and a
folder of WAVs, so `nhsx-render` turns one back into audio — geometry,
mute, level, fades and pan, no effects — with nothing but `nhsx/`, numpy and
ffmpeg. `--plan` and `--json` say what would be heard without opening a
single audio file, which is what makes a preview fast enough to be worth
having.

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

Red-green, one pinned linter, CalVer per app, and numbers in the comments —
**`CLAUDE.md`** carries them, for people and agents alike, and `tests/`
asserts the ones a machine can check. `CONTRIBUTING.md` has the commands.
