# PR 234: scalar-compatible music-bed vectorization

The fade mask now preserves rise priority even when the bed ends before the
chosen speech pause. Fade interpolation uses scaled knots and compares the
original delta with the scaled endpoint, so digital silence starts on the
same sample as before vectorization.

Exact-output tests uncovered another difference: NumPy's slope-first interp
rounds some public results differently (-0.11 instead of -0.10). The batch
lookup now uses searchsorted and the original multiply-then-divide order.
The scalar curve and interpolation from pre-PR main are frozen in a test
oracle, with 450 seeded timelines exercised in both cold-open modes, plus
focused overlap, endpoint and rounding regressions. Both reported failures
were observed red before repair. Replacing the new interpolation with
np.interp was also checked to fail the rounding regression.

Validation: nhsx 56 passed; repository ruff check clean. Root workspace
contracts: 267 passed, 3 skipped, 16 subtests passed, one failure because zsh
is unavailable in this Linux environment. No test was weakened or skipped
by this patch. Mac/app suites await the existing CI workflow.

Synthetic invocation using the 102.851-second intro timing layout, five
repeats of 100 calls: median scalar 2.021 ms, vectorized 0.675 ms. This
measures curve calculation, not rendered episode audio.
