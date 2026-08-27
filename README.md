# Podcast Magic

Two Hindenburg chores, done on your own Mac instead of in Google Colab:
transcribing the session's audio pool, and muting everything nobody says.
One window, one session file, two tools — and room for a third.

*[Suomenkielinen README](README.fi.md)*

* **Transcription runs on the GPU.** Whisper through Apple's MLX, which means
  Metal. No upload, no runtime disconnecting halfway, no Drive mount.
* **The session is the format.** Both tools read and write the same `.nhsx`.
  Words go into the audio pool with their timings; the silencer reads them
  back out and cuts the tracks.
* **Nothing is overwritten.** Every run writes a new file next to the source,
  and an existing result becomes `… v2`, never a replacement.

## Install

```
uv sync --extra mlx        # Apple Silicon — the fast one
uv sync --extra faster     # Intel Mac, or a second opinion
brew install ffmpeg        # audio decoding; bundled in the built app
```

## Use

```
uv run podcast-magic                    # find the newest session here
uv run podcast-magic "episode 8.nhsx"
uv run podcast-magic ~/Podcast/episode8/
```

The browser opens at `http://127.0.0.1:8741/`. Built as an app it opens its
own window instead.

The loop:

1. Record and lay out the session in Hindenburg. Save.
2. **Transcribe** — writes `episode 8 litteroitu.nhsx`.
3. Open that in Hindenburg if you want to read it, or go straight on.
4. **Silence** — writes `episode 8 litteroitu vaimennettu.nhsx`.
5. Open it in Hindenburg. Every gap is a muted region you can un-mute.

## Which Whisper

| Engine | Where it runs | When |
|---|---|---|
| `mlx-whisper` | Apple GPU, via Metal | **default on Apple Silicon** |
| `faster-whisper` | CPU, int8 | Intel Macs, or a second opinion |

There is no third option worth having here. `faster-whisper` is what the
Colab notebook used, and CTranslate2 has no Metal backend at all — on a Mac
it runs on the processor, so `--compute_type auto` never finds a GPU to use.
MLX runs the same model on the GPU with no conversion step.

Both produce word-level timings, which is the only output that matters: a
`.nhsx` transcription is a list of `<w>` elements with a start and a length,
and the silencer's whole decision is built from them. The notebook's
`--max_line_width` and `--max_line_count` only ever shaped subtitle files and
are gone.

Model weights are not bundled. The first run downloads the model from Hugging
Face — about a gigabyte for `large-v3-turbo` — and it stays in your cache
after that.

### Filler words are on purpose

Whisper tidies speech up unless told not to. The notebook turned that off
with `--suppress_tokens "" --suppress_blank False`, and so does this, because
"um" and "you know" are speech: leave them out and the silencer mutes the
half-second where somebody was clearly talking.

## The silencer

Speech intervals come from the transcription, not from a level threshold. A
word's timestamp is **file** time; a region says where in the file it starts
(`Offset`) and where on the timeline it sits (`Start`), so the word lands at
`Start + (s - Offset)`. Each region is converted separately, because the same
file can appear on the timeline more than once.

Three controls:

* **Tail** — how much speech is kept either side of a word. A word's timestamp
  is its edge, and speech cut exactly at the edge sounds cut.
* **Shortest gap** — pauses below this are not closed. Gaps between words are
  tenths of a second; muting each one makes the track click all episode.
* **Level check** — when microphones bleed, Whisper hears the other person on
  this track too and writes their words down as yours. Level tells own speech
  from bleed. Text cannot.

The level check decodes every track, so it runs in the job, not in the
estimate under the sliders. The estimate says so.

## Building the app

```
uv run --extra mlx python scripts/build_app.py --dmg
```

PyInstaller bundles the code, a static `ffmpeg`, and whichever Whisper engine
is installed in the build environment — including MLX's Metal shaders, which
the app cannot transcribe without. The result is `dist/Podcast Magic.app`.

## Adding a module

A module is four things: a key, a name, an `APIRouter`, and one `mod_*.js`
that registers a panel. `modules.py` lists them; the shell and the server do
not change. The shell owns the session picker and the job queue, so a new
module inherits both.

The intended third is [automixer](https://github.com/ollisulopuisto/automixer)'s
speech chain. `nhsx/pipeline.py` already exposes the session in the shape that
chain expects — a track with a speaker and a list of spans on the programme
timeline — so the work left is the chain itself, not the plumbing.

## Layout

```
src/podcastmagic/
  __main__.py  gui.py  server/      the shell: window, server, static UI
  jobs.py                           one background job at a time, with progress
  nhsx/                             the session format — shared by every module
  transcribe/  backends/            Whisper: one interface, several engines
  silence/                          speech intervals, region splitting
  modules.py                        the registry
```

Code, comments and docstrings are in Finnish; the interface and the
documentation are in Finnish and English.

## Licence

MIT.
