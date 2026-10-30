# Podcast Magic release audit — 2026-10-30

## Result

The current published Apple Silicon DMG is already built from current remote
`main`, commit `5a179e6f16024a0e1aa6fa9d01a0edcb09cdf2fc`, tagged
`podcast-magic-v2026.10.29.1`. The failed workflow does not invalidate the
successful macOS build. Its publisher failed on the Linux release asset.
Any source changes made after this audit will require a new build before the
DMG can be described as containing those changes.

This is a read-only release audit except for this report. No workflow, source,
tests, versions, release assets, or existing local changes were modified;
nothing was committed. The primary checkout's HEAD is `9d7f6665b52aa57d7b1cc34ee4fb0b035a375574`,
so it must not be mistaken for current remote main. Remote main was checked
through the GitHub API, not inferred from that checkout.

## Evidence: exact failure

[Run 40871931298](https://github.com/ollisulopuisto/podcast/actions/runs/40871931298)
was triggered by a tag push, with head SHA `5a179e6f16024a0e1aa6fa9d01a0edcb09cdf2fc`.
All three platform build jobs succeeded. Release job `123477756216` downloaded
the artifacts successfully, then failed in `Publish release`:

```text
HTTP 422: Validation Failed (...name=podcast-magic-linux-x86_64.tar.gz)
size must be less than 2147483648
```

The Linux build log records the actual tarball as **3,249,209,008 bytes**.
The Actions artifact wrapping it is **3,237,277,137 bytes**; that latter number
is not the tarball size. Both exceed the **2,147,483,648-byte** boundary reported
by the release upload API. Actions artifact storage accepted it; release asset
storage rejected it. This was not a build, test, or artifact-download failure.
The Linux test log reports 366 passed, 1 skipped, and 1 warning; a successful
job alone should not be represented as every Linux test having executed.

The tagged workflow combines every platform in one command:

```sh
gh release create "$GITHUB_REF_NAME" dist/podcast-magic-* ...
```

There is no per-file size check, and a single rejected asset makes this command
fail. `fail-fast: false` protects the build matrix only. `needs: [build]` still
couples publication to aggregate build success. The local workflow has the
same publishing logic; it differs from the tag by removing the manual test
bypass. That bypass did not run in the audited tag build.

Why the Linux package grew this large was not established by inspecting the
archive contents. Do not attribute the measured size to a specific dependency
without that separate investigation.

## Evidence: Mac release is available and current

The [published release](https://github.com/ollisulopuisto/podcast/releases/tag/podcast-magic-v2026.10.29.1)
is public, not a draft or prerelease, and currently has one asset:

- [podcast-magic-macos-arm64.dmg](https://github.com/ollisulopuisto/podcast/releases/download/podcast-magic-v2026.10.29.1/podcast-magic-macos-arm64.dmg)
- Size: **489,783,030 bytes**, identical to the macOS build log's DMG size.
- GitHub-reported SHA-256: `042101846e18410cec102cebdd686fe7447d6ca55fc59a8eca85274cbb42c483`.
- Published: **2026-10-29 16:20:36 UTC**.
- Release notes identify recovery from the successful macOS job of this run,
  without rebuilding or changing the source.

macOS job `123440889625` reports **367 passed, 1 warning**, successful packaging,
both app executable and ffmpeg as **Mach-O arm64**, and successful
`codesign --verify --deep --strict` on the app. The source artifact
`podcast-magic-macos` (ID `12900433897`) remains available and unexpired at audit
time, with expiry `2027-01-27T12:16:37Z`. Its ZIP digest differs from the DMG
digest because it represents the enclosing Actions artifact.

This establishes build and publication evidence, not native user acceptance.
This audit did not download/re-hash or mount the DMG, launch the app, exercise
real ASR models, or listen to an episode. The app is not Apple-notarized. Those
limitations are already stated on the release. Windows and Linux release
downloads are absent; their build artifacts are still present.

## Safest small workflow change

Publish the Mac asset in its own first release operation, then handle the other
platforms in subsequent upload steps. Preserve test gates and keep unexpected
upload failures visible. In concrete terms:

1. Download and require the named `podcast-magic-macos` artifact first. Require
   exactly the expected DMG, ensure it is nonempty and below the API boundary,
   and create/publish the release using only that DMG. Release notes should
   accurately describe the assets currently available.
2. Download the other platform artifacts after the Mac publication. Preflight
   their actual archive sizes before attempting uploads. Upload eligible assets
   separately; record an oversized Linux asset's name, measured size, and the
   release limit in the job summary and release notes.
3. Under the current strict CI policy, report the unsupported oversized asset
   as a final failed publication check after eligible uploads, leaving the
   already published Mac DMG available. Do not use `continue-on-error`, hide
   upload failures, or mark Linux as published. Alternatively, explicitly agree
   on and document a Mac-only release policy before treating an omitted Linux
   asset as success.
4. Make retries deliberate: inspect an existing release, verify its tag/asset
   identity, and only add missing assets. Do not use automatic `--clobber` to
   replace the recovered DMG or recreate the existing release. Authentication
   or network failures must not be mistaken for a missing release.

This is a small publisher change and addresses the observed oversized archive
failure. Keeping `needs: [build]` still means an actual Linux/Windows build
failure prevents starting publication. Fully independent Mac publication needs
a separate Mac build/publish dependency (or publishing at the end of the Mac
matrix leg), which is a broader follow-up. Avoid claiming the small fix handles
all cross-platform failures.

Before implementation, add a failing regression test using temporary files
(including sparse files at and above the size boundary) and a mocked `gh`
command: an oversized Linux archive must never be passed to release creation,
Mac publication must happen first, and a later rejected asset must remain
visible as failure. Also cover absent/oversized Mac, existing releases, and
non-size upload failures. Do not change the tag or delete the existing release
to test this. Rerunning the old tag uses its old workflow; a workflow repair
must reach the source selected for the next release.

## Checks performed

Read root `CLAUDE.md`, `CONTRIBUTING.md`, Podcast Magic `CLAUDE.md`, and the
ASR handoff. Compared the tagged and local workflows. Inspected GitHub release,
remote main, workflow run, job status, artifact metadata, and Mac/Linux/release
job logs through the connected GitHub tools. Ran
`UV_CACHE_DIR=/tmp/podcast-release-audit-uv uv run --no-sync ruff check .`:
**all checks passed**. No code was changed and no test suite was rerun locally;
the CI test counts above are historical evidence from the tagged build.
