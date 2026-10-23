# podcast: instructions for any coding agent

A uv workspace: `packages/speechmix`, `packages/nhsx`, `packages/silencelearn`
and `packages/wordalign` are shared libraries; `apps/` and `colab-transcribe/`
are the programs that use them. `README.md` says what each one is. The kuulas
audio editor (a separate repo) imports `speechmix` and `nhsx` from here and
runs `automixer` as a command, so their interfaces are contracts.

Read, in this order:

1. `CLAUDE.md`: the rules for all work in this repo. It is binding for every
   agent, whatever its name. Do not work from a summary of it.
2. `CONTRIBUTING.md`: the commands, one per workspace member.
3. The `CLAUDE.md` of the app you touch (domain knowledge: time bases, the
   `.nhsx` word clock, the automixer chain, the Colab script's drift risk).

The short version, which does not replace the above:

- Red-green TDD. Write the failing test first, watch it fail for the right
  reason, then implement. Never weaken a test or a lint rule, never skip one.
- `uv run ruff check .` reports nothing, and the tests of the member you
  touched pass. Where a test cannot run in your sandbox (sockets, ffmpeg,
  Apple Silicon `mlx`), say which and why in the report; do not claim them.
- One task, one branch from `main`, preferably in its own worktree. Commit
  only your own paths (`git add <paths>`, never `git add -A` or `commit -a`).
  Do not stash, reset or discard anyone else's changes.
- Do not bump versions (`scripts/bump_version.py` is the integrator's job) and
  do not edit a `CHANGELOG.md` unless the task says to.
- Agents that cannot push commit on their branch and report: branch, files,
  tests run, and what could not be verified. The integrator pushes and opens
  the PR (squash merge).
- A constant that came from a measurement says what was measured. Numbers in
  a report say what they were measured on; synthetic audio is not an episode.

Interfaces other programs depend on (change them only with a note in the PR):

- The `automixer` command line: `automixer <stems-folder> -o <file>
  --target-lufs N --progress [flags]`, the flags listed by `--help`, the
  `PROGRESS <0-100> <message>` lines, the per-track stage lines, the `beds:`
  and `mastered:` log lines, the `<output> flags.txt` file and, with
  `--events`, the `@@kuulas <json>` lines (`schema` 1; fields are added, never
  renamed).
- `colab-transcribe --audio F --json DIR [--progress] [--align]`: the
  `<name>.words.json` files, the `PROGRESS` lines, the exit codes, SIGTERM
  and, with `--events`, the `@@kuulas <json>` lines (`schema` 1; fields are
  added, never renamed; `docs/KUULAS-COLAB.md`).
- `tracks.json` version 1 (48 kHz, `start_frame` 0, "dry") read by
  `speechmix.stems`.
- `<stem>.words.json` and its `timing` field, produced by `colab-transcribe`
  (`docs/KUULAS-COLAB.md`).
