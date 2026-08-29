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
seam and `apps/autoraffkat/SHARED-AUDIO.md` for the measurements behind every
stage.

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

All three run the same chain. automixer was the last one in and the last to
get all of it: the shared pipeline reaches the timeline through *tracks with
spans*, that shape used to be buildable only from FCPXML, and so the four
stages that need it were locked to one app. They are not any more —
`packages/speechmix/README.md` describes the seam and
`apps/automixer/SPEECHMIX-INVENTORY.md` records what changed when automixer
crossed it.

`nhsx-render` is the odd member of the set: it is the only tool here that
does not run that chain at all, because it exists for the day the program it
reads for is gone. A `.nhsx` is XML and a folder of WAVs, so it turns one
back into audio — geometry, mute, level, fades and pan, no effects — with
nothing but `nhsx/`, numpy and ffmpeg. `--plan` and `--json` say what would
be heard without opening a single audio file, which is what makes a preview
fast enough to be worth having.

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

## The viewer

`viewer/` is **NHSX Viewer**, a small app that opens a `.nhsx` — tracks,
regions, and the mix played back — plus a Quick Look extension that shows the
same view in Finder — press space, see the tracks and
regions, hear the mix. It is Swift, because a macOS app extension cannot
be anything else, and it is at the repo root rather than under `apps/`
because a directory there without a `pyproject.toml` breaks `uv sync` for the
whole workspace.

It parses the session again in Swift rather than calling `nhsx-render`: a
preview extension is sandboxed and cannot spawn a subprocess. Two parsers of
one format is the drift this repo exists to prevent, so they share an
answer instead of code — one session in `viewer/Conformance/` whose plan
is written down, which both implementations test themselves against.
`viewer/README.md` has the rest.

## Working rules

Red-green, one pinned linter, CalVer per app, and numbers in the comments —
**`CLAUDE.md`** carries them, for people and agents alike, and `tests/`
asserts the ones a machine can check. `CONTRIBUTING.md` has the commands.
