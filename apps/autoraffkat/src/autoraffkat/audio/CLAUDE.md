Audio analysis and export. Moved from `apps/autoraffkat/CLAUDE.md`; it also governs `analysis.py` and `decide.py`.

## Audio: analyse raw, export processed

`audio/mix.py` is the third slow layer. Two things are not negotiable:

Never write over the original. The envelope cache is keyed on modification
time, so overwriting would recompute the curve — and the new computation would
land on processed audio. Analysis is always done on the raw file: a compressor
raises the noise floor between words and flattens the difference between
microphones, destroying exactly the two things sensitivity and the overlap rule
depend on.

The sample count must not change. The export references the processed file with
the same times as the original. The check exists in two places and anything
deviating is discarded. A shift is measured separately by cross-correlation,
because length alone cannot detect a plug-in that reports its latency wrongly.
That correlation must stay an FFT: `np.correlate(..., "full")` is O(n²) and
took 132 s on a 20-minute file — longer than the plug-in itself. A test fails
if the order of growth comes back.

The plug-in is 97 % of the run and uses **one** core: dxRevive measures 0.98
cores and 7.25× realtime. The only way to reach the other cores is to run
several instances at once, so `chain.apply_plugin` accepts a pool and cuts the
file into as many pieces. This is not the forbidden chunking above: each piece
is its own full `reset=True` run with a five-second margin that is processed
and thrown away, and the result is written into an array of the original
length, so the sample count cannot move. It is not free either — the pieces do
not see each other's context, so the plug-in's slow adaptation differs slightly
between them. Measured on a real 20-minute file: 168.4 s → 68.3 s, and the
difference from the whole-file result is 25.7 dB below the signal in speech and
−84 dBFS in the quiet parts. Because it is not zero, the piece count is
adjustable (`plugin_workers`, where 1 means one run over the whole file), and
because it changes the result it is in `FINGERPRINT_FIELDS`. The default is a
share of the machine's cores, not a number written into the source: an
eight-core laptop and a twenty-core workstation are different machines.

The ceiling is the **programme's** too, and that was missing for longer
than the loudness half. `chain` guarantees −1.5 dBTP per file, but Final Cut
plays the sum: two stems whose peaks are both pressed to the ceiling exceed
full scale whenever those peaks coincide — in theory +4.5 dB, and measured on
a real episode **+4.51 dBFS with 200 clipping bursts a minute**, median
0.23 ms. That is what the red peaks in Final Cut's waveform are, and it is
audible as intermittent crackle on loud syllables. The fix is not harder
per-stem limiting — then every stem pays six decibels of crest for what some
*other* file happens to do — but a **shared curve**: `mix.program_ceiling`
computes the limiter's gain from the summed stems and multiplies the same
curve into each one, so the sum obeys the ceiling and the balance between
speakers cannot move. Measured: sum +4.51 → −1.51 dBFS, cost 0.50 LU, 7 s for
a 20-minute pair. The pass is idempotent by construction — the curve is
`min(1, ceiling/peak)`, so a sum already at the ceiling gets 1 everywhere —
which is what makes it safe to run on every processing round, including one
where most files were skipped as up to date. It sums files sample by sample,
which is only correct when the stems line up, so `_geometry` makes that a
checked fact rather than an assumption and stems that do not match are left
alone.

The loudness target is the **program's**, not one stem's. Two microphones each
normalised to −14 LUFS sum above it — measured on real material, −12.2 — because
the speakers overlap and the microphones hear each other. `mix.program_trim`
measures the sum of the raw microphones over a bounded window and takes the
difference off every file. The window is anchored to the longest microphone
file rather than the middle of the timeline: in a multicam the parts are
consecutive, so the timeline's midpoint lands inside one part and the other
part's files would measure as silence.

Progress is weighted by file size, and the stage is the resolution: the plug-in
processes a file in one piece and cannot be asked how far along it is. Shares
in `chain.STAGES_*` are measured, not guessed. Processing also logs each file
and stage to the terminal — when it is slow or fails, the question is always
which file and which stage.

When an asset's `src` is redirected, the `uid` must be removed too. Final Cut
identifies media by `uid`, not by path: an asset that keeps the old `uid`
claims to be the old media, and since the raw twin is a copy carrying that
same `uid` *and* a bookmark, Final Cut collapses the pair and keeps the raw.
The export then sounds right and measures −43 LUFS. The twin keeps its `uid`,
because it really is the original media.

When an asset's `src` is redirected, the `<bookmark>` must be removed. It is a
macOS file reference that beats `src`, and leaving it would mean Final Cut
opens the unprocessed file without saying anything.

Redirection leaves no reference to the original, so every processed microphone
angle gets a muted twin angle carrying the raw file (`_raw_twins`). The twin is
a **copy** of the angle taken before the redirect: it inherits the times and
the `<bookmark>` and is therefore in sync to the sample, and the original `src`
never has to be reconstructed. Own subrole, so switching it on gives it its own
fader instead of summing with the processed track.

`srcEnable` beats `active`. Final Cut never writes `srcEnable="audio"` with
`active="0"`: audio on is `audio` + `active="1"`, audio off is `none` (or
`video`) + `active="0"`. The combination we wrote is a contradiction, and
Final Cut settles it in favour of `srcEnable` — the angle plays whatever the
role says, silently, and the raw twin sums under the processed track. The
twin's `mc-source` is `srcEnable="none"`, which still lists the angle in
Audio Configuration, unticked. When something imports but does not behave,
compare against a multicam Final Cut wrote itself; our reader accepts
combinations the application never produces.

A multicam angle's role comes from `<audio-channel-source>`, not from
`audioRole`. Final Cut ignores the attribute there and leaves the angle on
`dialogue.dialogue-1`; the channel source names the component and is honoured.
Both are written, because that is how it was tested. Established by importing
one version of each and reading the inspector — not from the DTD, which
permits both and predicts neither.

A subrole is only real if the angle carries it. The angles are copied from
the source, so their audio keeps Final Cut's default `dialogue.dialogue-1`;
writing a per-speaker subrole into `mc-source` alone points
`audio-role-source` at a role that is not there. That fails silently — valid
DTD, clean import, `active="0"` applied to nothing — and the raw twin plays
summed with the processed track. `_stamp_angle_roles` sets the role on the
angle, using the same construction as `_mc_sources` so the two cannot drift.

The flat export has no angles, so there the twin is a connected clip with
`enabled="0"`. Twins go on the **lowest** lanes, after the microphones and the
room tone: turning processing on must not move the microphone the editor is
looking at on lane −1. Only a processed track gets a twin.

"Up to date" is a fingerprint, not a modification time. A processed file
newer than its source proves nothing: the plug-in, its controls, the target
level and the ducking depth never touch the source. Comparing times alone made
the button skip every file, return before the first log line and leave the
panel unchanged — indistinguishable from a broken button. `mix.is_fresh`
compares `mix.fingerprint` against a stamp in `~/Library/Caches/autoraffkat/mix/`,
and `FINGERPRINT_FIELDS` is written out by hand so a new setting cannot slip in
or out unnoticed; a test fails if it does. An unknown stamp counts as stale.
`adopt` uses the same test as `process`, or the export would use a file that
processing has just decided to redo.

The processing button belongs in the header, next to Export. It is an
**action**, not an audio setting: the panel decides what processing does, the
header decides whether to do it — the same split as between the cut panel and
Export. The stronger reason is the state it carries. The button says how many
files were made with different settings, and that is exactly what you need to
know at the moment you press Export; at the bottom of the audio panel, in the
right-hand rail below the fold, it was invisible precisely when it mattered,
and an export that used raw audio looks successful until somebody listens.
The count goes on the button itself for the same reason — in the header the
panel's explanatory note is no longer beside it.

The button carries the state, because the work is minutes long and invisible.
`mix.freshness` counts how many files match the settings right now — `stat`
calls and stamp reads, cheap enough for the settings round, which is where it
runs so the button goes stale at the same moment the result does. All fresh
means the button says so and asks for confirmation before re-rendering
(`force`); some stale means it invites a run and the note says how many were
made with different settings. Only the button is swapped in place: redrawing
the audio panel would replace a slider mid-drag.

`target_lufs` is the **programme's** level, not a stem's. YouTube normalises
the finished video; `program_target` converts that to a stem target with the
measured trim, so −14 becomes −15.8 per stem and the sum lands near −13.
Applying −14 to a mono speech stem directly leaves about 14 dB of crest and
sounds crushed; the same figure as a programme target leaves 17.5.

Compression comes in small amounts several times. Every stage caps its own
gain reduction, and the first is multiband so a plosive cannot pull the
sibilance down with it — with one ratio and one limit across all bands,
because differing amounts per band move the tone with the programme. The
ceiling is true peak with headroom: limiting sample peaks to −1 dBFS measured
−0.42 dBTP, since the peaks that clip a converter fall between samples.

The program trim goes into the **target**, never into the gain. The chain
normalises to the target as its last act, so a trim added to the gain is
removed again exactly — measured, stems landed on −14.1 instead of −15.8 and
the reading looked correct.

The processed files stay on disk between sessions, but `MixResult` does not.
`mix.adopt` reads what is already there — `stat` only — and it runs on load and
again at export. Without it, exporting without pressing the button referenced
raw audio while the file name still said `audio`, and that difference is not
noticed until someone listens, by which time the cut has been edited in Final
Cut. Never make the export depend on which buttons were pressed this session.

The ceiling is a look-ahead limiter, never a static attenuation. A static cut
scales the whole file by what its single loudest sample demands, and after
normalisation the peaks are +8 to +11 dBFS — measured, that turned −14.00 LUFS
into −25.74. It also makes the balance between speakers depend on whose
loudest transient was loudest, which is to say random. The level is
re-measured after limiting so speakers land on the same number.

Every compressor stage must be shown to engage. The third stage's
threshold was written `leveler_threshold + 4.0` — four decibels *above* the
second — and it runs after the second, which has already pulled everything
under its own threshold. It therefore never fired: measured on three minutes
of real speech, its gain moved 0.00 dB at every target from −14 to −18. The
chain promised three bounded stages and ran two, and the slack landed on the
limiter. A dead stage crashes nothing, logs nothing and sounds like a working
chain, so `test_every_compressor_stage_actually_engages` runs each stage in
sequence and fails on any that leaves the signal untouched. Note what the
test's fixture had to learn: thresholds are absolute and applied after
normalisation, so a signal whose every burst is equally loud sits entirely
below them and the test passes while measuring nothing. The bursts must vary,
because in speech it is the loud passages that clear the threshold.

The crest that reaches the limiter is set by `PARALLEL_MIX`, not by any
threshold. The output is `0.4·dry + 0.6·compressed`, so 40 % of every
untouched transient survives whatever the compressors do: measured, waking the
third stage moved the pre-limiter peak from +7.55 to +7.16 dBFS, and raising
the multiband's gain-reduction ceiling from 5 to 8 dB moved it not at all —
it was never hitting 5. Peak control therefore belongs to the limiter by
construction, which is worth knowing before reaching for a compressor to
solve a peak problem.

Compression is parallel, and the peak attack is longer than a pitch period.
Two milliseconds modulates the waveform of a 110 Hz voice instead of its
level, which is harmonic distortion: measured −30.9 dB THD at 2 ms against
−36.1 dB at 40 ms. De-essing comes before the compressors, because the
restoration plug-in adds several dB above 3 kHz and one sibilant otherwise
drives the gain of a whole sentence.

The channel strip is in `audio/chain.py`, on pedalboard. Two places where the
library doesn't do what its name promises, both measured:

* `plugin.process(..., reset=False)` **shortens** the result by the plug-in's
  latency (4641 samples with dxRevive). Always use `reset=True`, and never
  feed one instance a file in chunks.
* `pedalboard.Limiter` applies makeup gain: it lifted −20 LUFS to −15.8 and
  peaks to zero. It was replaced by `peak_guard`, a static attenuation that
  never raises.

Ducking is an envelope in the export, not a burn into the file. It is a
level decision, and level decisions belong where the editor can still reach
them: baked in, it was the one setting in the whole chain that could not be
changed without a minutes-long run, and "the ducking is 3 dB too deep" meant
reprocessing every microphone. As `<adjust-volume>` keyframes on the angle it
is one drag. `mix.duck_envelopes` produces the same shape `chain.apply_duck`
burnt — fades **inside** the range, asymmetric, interpolated in decibels —
because the result must not depend on which way it was made.

Two consequences follow, and both are load-bearing. The duck settings left
`FINGERPRINT_FIELDS`, so changing the depth no longer makes a single file
stale: export again, do not process. A test asserts they are absent, since a
silent *re-*inclusion would put minutes back onto a free adjustment. And
`program_ceiling` must apply the envelope while it sums, because the stems on
disk are no longer what Final Cut plays — on this episode 8 and 30 minutes of
attenuation are missing from them, and a ceiling computed without it limits a
programme that does not exist.

The keyframes go on the **angle**, like the panning, and for the same reason:
volume on the `mc-clip` would duck both speakers at once, which is the
opposite of ducking. A shot the envelope does not touch gets no
`<adjust-volume>` at all — an empty one is a setting as far as Final Cut is
concerned. A shot the envelope crosses gets a keyframe on its edge carrying
the value there: without it Final Cut interpolates from the clip's start and
the attenuation restarts from zero at every cut, which is audible pumping
that nothing reports.
