# Roadmap idea: transcript-driven removal suggester

**Status:** punted, not started. Written down so it isn't lost. Rules for
what counts as "removable" are TBD — need a conversation before this
becomes an execution plan in this directory's usual format.

## The idea

A new tool that:

1. Reads a transcript out of an XML session — `.nhsx`'s own
   `<Transcription>` word list (see
   [`docs/hindenburg-nhsx-format.md`](../hindenburg-nhsx-format.md) §4) is
   the reference shape; `colab-transcribe` is where transcription already
   happens in this repo and its output is the other thing to look at
   before settling on an input format.
2. Sends the transcript (words + timing) to an LLM API and asks it to
   suggest cuts — filler words, false starts, dead air, off-topic
   tangents, whatever the eventual rules say counts as removable.
3. Writes a **new** Hindenburg XML — non-destructive, same rule as
   podcast-magic and colab-transcribe (always a new session file next to
   the original, never overwrite) — with a `<Marker>` pair bounding each
   suggested removal: one marker at the start, one at the end, named so
   they read unambiguously in Hindenburg's marker list (e.g. "Poisto alkaa"
   / "Poisto loppuu" — needs a real naming convention, not a guess).

## Why markers and not `Region` edits

Markers are non-destructive and reviewable: the editor sees every
suggestion in Hindenburg's own timeline and accepts or rejects each one by
ear, rather than trusting the tool to cut. This matches the project's
general stance (`CLAUDE.md` posture across apps: suggest/expose,
don't silently commit to a destructive edit) and Hindenburg's
`<Markers>` element already exists for exactly this
(`docs/hindenburg-nhsx-format.md` §8) — no new session concept needed,
just a paired-marker convention.

## Open questions (the "rules TBD")

- What counts as a removal candidate? Filler words, repeated takes,
  silences, tangents — likely several categories with different LLM
  prompts/confidence, not one flat list.
- Confidence threshold / review workflow — does every suggestion get a
  marker, or only above some confidence, with the rest logged elsewhere?
- Marker naming/pairing convention so Hindenburg's flat marker list reads
  as clear begin/end pairs (ordering, ids, a shared suggestion-id in the
  name since `<Marker>` has no grouping attribute — confirm against
  §8/§9 of the nhsx doc, which lists marker fields as sparse).
- Where this lives: a fifth app under `apps/`, sharing
  `packages/speechmix`'s nhsx read/write (`podcast-magic` and
  `colab-transcribe` both already read/write `.nhsx` — check
  `packages/nhsx` before writing a new parser).
- Which LLM API, cost per episode, and whether transcript text needs any
  redaction/trimming before it leaves the machine.

## Next step

Have the rules conversation, then write a real plan in this directory
following the shape of
[`2026-08-30-vertical-reframe.md`](2026-08-30-vertical-reframe.md).
