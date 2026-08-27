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

## Quick start

macOS, and [uv](https://docs.astral.sh/uv/). Cold clone to a running window:

```
git clone https://github.com/ollisulopuisto/podcast
cd podcast
brew install ffmpeg
uv sync --all-packages --extra mlx
uv run podcast-magic ~/Podcast/episode8/
```

That opens `http://127.0.0.1:8741/` in your browser. Add `--gui` for a
native window instead.

Three ways to say which session:

```
uv run podcast-magic                     # newest .nhsx in the current folder
uv run podcast-magic "episode 8.nhsx"    # this one
uv run podcast-magic ~/Podcast/episode8/ # newest .nhsx in that folder
```

### Two things about `uv sync` here

**Run it from the repository root, and pass `--all-packages`.** This app is
one member of a uv workspace, next to autoraffkat, automixer and the shared
`packages/speechmix`. That has two consequences worth knowing before they
confuse you:

* `uv sync --extra mlx` at the root installs **no engine at all** — the extra
  belongs to a member, not to the workspace, so there is nothing for it to
  match and nothing is said about it.
* `uv sync` *inside* `apps/podcast-magic` syncs that one member and
  **uninstalls the other members'** dependencies from the shared environment.

`uv run podcast-magic` works from anywhere in the tree; only `uv sync` cares
where you are.

**Pick your engine with the extra.** `--extra mlx` on Apple Silicon,
`--extra faster` on an Intel Mac. Both together is fine —
`--extra mlx --extra faster` is what CI installs — and then the engine picker
in the window has something to pick between.

## Use

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

Four controls:

* **Tail** — how much speech is kept either side of a word. A word's timestamp
  is its edge, and speech cut exactly at the edge sounds cut.
* **Shortest gap** — pauses below this are not closed. Gaps between words are
  tenths of a second; muting each one makes the track click all episode.
* **Level check** — when microphones bleed, Whisper hears the other person on
  this track too and writes their words down as yours. Level tells own speech
  from bleed. Text cannot — the two transcriptions are not even the same
  string, so there is nothing to match.
* **Margin to loudest** — which track a word belongs to. See below.

The level check decodes every track, so it runs in the job, not in the
estimate under the sliders. The estimate says so.

### One room, and every microphone hears everyone

A threshold on its own cannot do this. In a quiet studio with good
microphones the bleed is not quiet — it is *quieter*, and only relative to
the microphone the speaker is sitting at. Measured on a real session:

* both microphones cross the threshold **41 % of the time**,
* but the bleed is a median **12.8 dB** below the same speech on its own
  microphone.

So the discriminator is not level, it is the **difference between tracks at
the same instant**. Absolute level moves with every microphone's preamp; the
gap between tracks does not. A word stays on the track where it is loudest,
and on any track within **Margin to loudest** of that.

It is a margin rather than winner-takes-all on purpose. 6 dB leaves about
6.8 dB of the measured 12.8 dB gap, so genuine overlap — interruptions,
laughter, the sounds that make a conversation a conversation — survives,
while bleed does not. A hard "one speaker at a time" rule would cut exactly
those. Set the margin to zero to turn the comparison off; that is off, not a
zero-decibel band.

A word whose level could not be measured on some track is never dropped on
that track's account: not knowing is not a decision to mute. Same rule as a
missing file. And with one track there is nothing to compare, so the
comparison does not run and says so in the log.

This is the same decision, from the same measurement, as `duck_dominance_db`
in autoraffkat — where it drives ducking rather than muting.

## When the script view's cursor sticks

Hindenburg has two views on the same transcription. The timeline draws the
words inside their region, so no mapping is needed — the word is where the
region is. The script view is a standalone document, and to follow the
playhead it has to build a time index. **An index that fails to build points
at the beginning**, which is exactly the symptom.

The format is not documented, so the tool measures rather than guesses:

```
uv run podcast-magic --inspect "episode 8 litteroitu.nhsx"
```

or the **Check the transcription** button in the transcribe panel. It reports,
per pool file, four things that could break a time index:

* **backwards** — a word starting before the previous one. Whisper emits
  these when a temperature fallback moves timestamps at a segment boundary.
  A binary search over a list that is not sorted does not return an error; it
  returns the wrong position, often the first.
* **overlap** — a word starting before the previous one ends.
* **empty** — zero or negative length.
* **outside_regions** — a word in the transcription that no region puts on
  the timeline. Trimming the head of a region in Hindenburg leaves the
  trimmed speech in the transcription: the timeline view does not draw it and
  looks right, the script view shows it and cannot agree with the transport.

Two more are reported as notes rather than defects, because they are suspects
and not measurements: everything in one `<p>`, and every word `sp="UU"`.

The writer now prevents the first three by construction — words are sorted,
overlaps are resolved by shortening the earlier word (never by moving the
later one, since the start time is what the cursor matches), and lengths have
a floor. **Split into paragraphs** is on by default and can be turned off, so
the same session can be run both ways and compared; the model fingerprint
includes the setting, so the second run really re-runs.

What would settle it: a `.nhsx` where Hindenburg's own transcription drives
the script view correctly. Its structure is the ground truth for `<p>` and
for what `sp` should contain.

## Reading a session without Hindenburg

A `.nhsx` is XML and its audio pool is WAV files on disk. As long as
something can read those two, the session is still listenable — with or
without the program it was made in, and with or without a licence for it.
`nhsx-render` is that something.

```
uv run nhsx-render "episode 8.nhsx"              # → episode 8.wav
uv run nhsx-render "episode 8.nhsx" --plan       # what would be heard
uv run nhsx-render "episode 8.nhsx" --json       # the same, for a program
uv run nhsx-render "episode 8.nhsx" --inspect    # what the format contains
```

It reads region geometry, mute, level, fades and pan — and nothing else. No
EQ, no compression, no Hindenburg voice profiles. That is a deliberate
floor, not a to-do: it means `--plan` never opens an audio file at all, so
an hour-long session is planned in milliseconds. A previewer that has to
render first is a previewer nobody presses space on.

The render itself never holds the programme in memory. It goes 30 seconds at
a time, straight to the file, and decodes only the piece of each source it
needs — so an hour of session costs about as much memory as a minute of it.
Nothing is overwritten: an existing `episode 8.wav` becomes `episode 8 v2.wav`.

### One caveat worth knowing

Region geometry and mute are certain — this tool has read and written them
from the beginning. **Level, pan and fades are not.** Their attribute names
are plausible guesses, because no session in this repository has ever had a
fader moved in it, and the format is not documented.

So the tool tells you when it meets something it cannot read, rather than
mixing on quietly at the wrong level:

```
Huom: istunnossa on attribuutteja joita tämä ei lue: Volume.
```

`--inspect` is how that gets settled. Point it at a real session where the
levels, pans and fades **have** been set, and it reports every attribute in
the file with example values — because "Gain" does not tell you whether it
is decibels or a factor, and the value does. One such file turns the guess
into a measurement.

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
    mix.py  render.py  cli.py       the session as sound: nhsx-render
    prospect.py                     what the format actually contains
  transcribe/  backends/            Whisper: one interface, several engines
  silence/                          speech intervals, region splitting
  modules.py                        the registry
```

Code, comments and docstrings are in Finnish; the interface and the
documentation are in Finnish and English.

## Licence

MIT.
