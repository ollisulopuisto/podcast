# Streaming mastering acceptance

PR119 is draft. Keeping the existing -16LUFS mastering is a release requirement,
not a tradeoff for lower RAM. The original `programme.master` remains the short
reference. Streaming keeps the same global target search, ceiling, boost bound,
limiter-cost budget and reached/not-reached result. It does not normalize chunks
independently. Some inputs already stop below target in the reference when these
constraints intervene; the streaming version must match that result too.

Run short reference/parity tests from packages/speechmix:

    uv run pytest tests/test_streaming_master.py tests/test_programme.py tests/test_programme_meter_chunks.py tests/test_meter.py -q

Resource harness (real meter/JIT,48kHz stereo, generated random-access source,
output discarded but counted; no full input/output allocation):

    uv run python benchmarks/master_stream_memory.py 10
    uv run python benchmarks/master_stream_memory.py 30
    uv run python benchmarks/master_stream_memory.py 90

The harness warms the JIT, then samples process RSS/scratch usage every50ms.
Reports baseline/peak/incremental RSS, elapsed time, exact written frames, output
peak/channel RMS, global result and leftover scratch. It is not a Mac/app export
benchmark. Long runs may take several minutes and require free disk. API scratch
preflight reserves no space atomically; other writers/quota can still cause ENOSPC.

## Measured locally,28October2026

Linux x86_64,Python3.13.17,NumPy2.5.4,SciPy1.18.1,Numba0.68.0.
Block262144frames, real integrated meter and CPU true-peak path.

|Fixture|Length/rate|Warm baseline RSS|Peak RSS|Increment|Peak scratch|Outcome|
|---|---|---:|---:|---:|---:|---|
|quiet periodic stereo|90min/48k|207.36MB|230.45MB|23.09MB|2.074GB|exact259200000frames,-16LUFS,reachedtrue,cleanupempty|
|active transient stereo|10min/48k|209.17MB|242.19MB|33.03MB|1.152GB|exact28800000frames,budgetcapped/reachedfalse,cleanupempty|

Quiet10/30minute runs also completed before the unity-stage optimization with
32.5/11.9MBincremental RSS, respectively. Different process allocator baselines
mean these are not precise cross-length savings ratios. The90minute quiet test
checks long duration but does not exercise the active limiter scratch path.
Active30/90minute48k runs have NOT completed within the local per-command120second
execution limit. Do not claim those acceptance gates passed. Keep draft until a
complete run produces its result and cleanup evidence.

Worst-case private API scratch=40bytes/frame,10.368GB at90min48k,excluding source
and output files. RAM also includes meter statistics proportional to duration,
though these are far smaller than sample arrays; this is bounded signal-working
memory, not a claim of mathematically constant total memory at arbitrary length.

## Remaining release gates

- Complete active30/90minute48k runs with measured process RSS/scratch and cleanup.
- Kuulas integration real file-output long runs and a measured replacement for
  its old whole-programme duration/RAM guard, not just API fixtures.
- macOSCPU and Metal-envelope reference parity: streaming currently explicitly
  uses CPU true-peak kernels. Existing Mac reference may use MLXfloat32 envelope.
  Linux numerical parity does not prove that native path bit-for-bit.
- Native Windows close/delete lifecycle test; source intentionally uses normal
  file handles, not whole-programme memmaps.
- Full repository CI, large-programme disk/quota failure behavior and product UX.

## Existing-CI route

`tests/test_streaming_master_long.py` invokes this actual harness for10,30,90minute
active48k stereo fixtures in separate processes. Existing standard public CI
already runs the speechmix suite, so no workflow/settings/artifact change is
needed. Expect several extra minutes; the overall jobs retain their existing
30minute timeout. Each child has a20minute timeout. Low disk is an explicit
failure, not a skip. Incremental RSS must remain below256MiB, complete frame
counts/scratch cleanup and peak ceiling are checked. The large active fixture
correctly reports target not reached when the existing limiting budget binds.

The separate native-MLX test records calls to the real GPU reference kernel and
checks short output against streaming at explicitfloat32-scale tolerances. It
skips with a clear unmet-GPU-parity note if MLXhardware/path is unavailable;
CPU-only fallback is not reported as nativeGPU acceptance.
