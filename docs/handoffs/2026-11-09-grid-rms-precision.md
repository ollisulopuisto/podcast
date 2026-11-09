# PR #201: sampled RMS precision repair

Whole-track cumulative sums dropped quiet energy after a loud prefix. On a
synthetic 156.25-second, 48 kHz mono signal (5,000,000 samples at 0.5 followed
by 2,500,000 at 1e-5), the PR returned -240 dB for the quiet tail instead of
the analytical -100 dB. The dense baseline returned about -100.00038 dB.
The new regression failed on the PR head before the fix.

Sampled windows now use independent means, gathered in chunks of roughly
2 MiB. No prefix from an earlier passage enters a later window. Nearest-edge
padding and sample-center geometry are unchanged. This retains sampled RMS
without relying on subtraction of large cumulative totals.

Validation on Linux, Python 3.13.17, NumPy 2.5.4, SciPy 1.18.1:
- 142 tests passed: grid, masks, rms, debleed, chain, envelopes.
- 47 workspace agreement tests passed.
- 36 additional dense-reference comparisons passed across rates 100, 8000,
  44100 and 48000 Hz and varied frame/hop sizes, including odd windows.
- Root ruff 0.17.2 check passed.
- Full speechmix suite exceeded the local 120-second execution window and
  is not claimed as passed. Native macOS consumers were not tested.

No app version bump: this changes the shared library, whose workspace changes
reach consumers together, per root CLAUDE.md and CONTRIBUTING.md. No release,
build, merge, workflow dispatch or application packaging is part of this fix.
Commit uses [skip ci] to avoid new GitHub cost.
