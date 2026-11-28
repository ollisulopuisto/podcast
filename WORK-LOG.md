# Work log

## 2026-11-28: Autoraffkat release version 2026.11.28.1

Owner: Instinct. User requested bump PR after merged277, maincc77cbb. Manifest, runtime, bundle spec and lock agree. No runtime/workflow change. Main/open/recent PRs and branches checked, no competing bump. Own review traced version into app/About, spec and tag/build consumer. No tag, Mac build, release or merge by this PR.

## 2026-11-27: Autoraffkat release version 2026.11.27.1

Owner: Instinct. User requested a bump PR so the next DMG includes merged #268. Manifest, runtime version, bundle spec and lock agree. No new runtime behavior. Repo default says version bumps belong to the integrator; this task explicitly requests the bump. Main cfd413b, open/recent PRs and branches checked, no duplicate open bump. Ruff clean; 57 version/workspace contract tests pass. Full root suite collection attempted but lacks numpy in the dev-only environment; not claimed passed. No Mac build, tag, release or merge.

## 2026-11-26: fcpxml read walk -56% on large timelines

Owner: Instinct. Branch: bolt/podcast-20261126-fcpxml-read-walk. Status: Review. `read_fcpxml` on a synthetic 4000-clip project (348 KB, built from `packages/fcpxml/tests/xml_builders.py`): 73.8 ms to 32.3 ms median of 25 runs (-56%), same sandbox session. The walk hoisted the loop-invariant `abs_offset - local_start`, skips zero-base adds and unclipped `_clip` arithmetic, builds `_State` directly instead of `dataclasses.replace`, caches parsed times in a dict keyed on the string (lru_cache hashed the Fraction default per call), compares Fractions by cross product and numerator sign instead of the Rational ABC path, and gives the dataclasses `slots=True`. Parity: `repr(dataclasses.asdict(timeline))` byte-identical before/after across the xml_fixtures documents (sync, project, multicam) and the 4000-clip file, `include_muted` both ways. 119 fcpxml tests pass; autoraffkat test_timeline + test_write 103 pass; repo-wide ruff clean. Pre-existing failure on clean main: tests/test_run_script.py zsh case (no zsh in this sandbox). Duplicate check: open/recent PRs and git log show no other fcpxml read-perf work. No merge authorized for this PR.

## CUDA 13 command-line test, 2026-11-21

Owner: Instinct. Branch: agent/cuda13-test-script. Status: Review. Adds scripts/cuda13_test.py and stage/fail-closed tests for the owner-requested Linux/Colab/WSL2 experiment. No app dependencies, drivers, releases or main changes. See docs/CUDA13-TEST.md for checks and unrun GPU acceptance. No merge authorized for this PR.

## CUDA runner safety follow-up

Fixed inherited uv project environment escape, selected-GPU validation and WSL probe lookup. 17 mocked regressions pass, including external environment preservation and visibility failures. Full Ruff passes. No real GPU acceptance claimed; PR remains unmerged.

Follow-up: disabled machine-wide pip settings and fail closed on an empty first GPU-list entry. 21 mock cases pass after three red-before regressions; Ruff passes.

Unposted review investigations: added the offline regression module to existing Linux CI and documented the optional transcription backend's CUDA 12/cuDNN runtime prerequisite. No GPU CI, driver install or dependency change added.

## 2026-11-22: CUDA child-environment regression coverage

Extended the existing two CUDA runner tests, without changing production code.
The mixed-GPU case now selects a UUID prefix and asserts that both Torch and WAV
transcription receive the complete supported UUID. The environment-isolation
case now includes a WAV and asserts sanitized uv/pip/Python overrides and a
checkout-local project environment for every uv invocation, including speech.
Both smoke commands must be present in order, so an omitted branch cannot pass.

Mutation validation: deliberately handing off the older GPU and restoring the
caller's environment for WAV transcription made the two tests fail for those
reasons. Restoring the unchanged runner yields 21 passing offline cases on
Linux/Python 3.13. Repository-wide Ruff 0.17.2 and git diff --check pass.
No network/GPU operations occur in the test stubs. Real hardware acceptance is
still unrun. Duplicate check: inspected open/recent PRs, branch list and main;
#263 is the only CUDA experiment runner work, so its existing tests are extended.

## 2026-11-24 - shared aligner installation tuple

Structure-only move from main13850c0: wordalign.py owns ALIGN_PACKAGES and
derives INSTALL; Colab install_aligner imports that tuple lazily. Torch and
TorchAudio remain2.8.0, no dependency or lock change. The remote driver already
uploads this single-file module only for --align; ordinary runs import none of
it. Existing test covers upload-before-run and no upload without --align.
Checked main, branches, open/recent PRs:264 is separate CUDA experiment and
bootstrap work, no duplicate constant refactor. Own adversarial review traced
the upload resource, install argv, unavailable error hint, ALIGN_TIMING/version
contract and unaligned isolated run.118 audio-mode, wordalign and new contract
tests pass. Tests failed first on missing tuple; hardcoded installer mutation
fails, restored implementation passes. Whole-repo Ruff0.17.2 and diff checks
pass. No real Colab/GPU install or inference run; no version bump or merge.

265 review follow-up: contract tests no longer duplicate production pins.
Hint mutation replaces the tuple assignment through AST, not a version-string
match. Pin-only0.0.1 mutation failed before test repair, then all three contracts
passed with only wordalign.py changed; reverted to2.8.0 afterward. INSTALL
readers and lazy installer use the shared tuple. CalVer follows the owner's standing instruction to bump each update:
colab-transcribe2026.11.24.1, matching uv.lock workspace metadata. No dependency
resolution change, publication, tag or merge.

## 2026-11-25: Macin tekstikenttien pikanäppäimet

Haara `fix/mac-text-shortcut-ownership`, kb-audit-autoraffkat. Jaettu
`shortcuts.js` hylkää Macissa fyysisen Controlin, myös Commandin kanssa.
Command-E/O säilyvät, muualla vanha Control/Command-yhteensopivuus säilyy.
Kumoaminen ja uudelleenteko jätetään tekstikentässä selaimelle; muualla
projektihistorialle. Molemmat sivut käyttävät samaa koneistoa. ARIA-vihje
kertoo Macissa vain toimivan Command-yhdistelmän.

Uusi tuotantokoneiston testi ensin punainen: Mac Control-O kaappautui.
Korjauksen jälkeen 94 käyttöliittymä-, näppäin-, traileri- ja valikkotestiä
läpi; mukana koko renderöinnin savutesti. Ruff koko repossa puhdas.
Työtilan sopimustestit: 267 läpi, 3 alustan ohitusta, 16 alitestiä;
yksi ympäristövirhe, zsh:n käynnistys estetty PermissionErrorilla.
Oma vastahakoinen katselmointi RAN: jäljitetty molemmat rekisterit,
keydown-käsittelijät, tekstitila, ARIA/vihjeet ja natiivivalikkosilta.
Natiivivalikon projektihistoria on vain vihje, ei keyEquivalent, joten
se ei ohita selaimen tekstihistoriaa. Ei avoimia löydöksiä.
Ei fyysistä Mac-koetta, Final Cutia, pakattua sovellusta tai DSP-testisarjaa.
Versio 2026.11.25.1 neljässä metadata-/lukkotiedostossa. Ei julkaisua,
PR:n yhdistäminen odottaa erillistä käyttäjän sanaa. #264/#265 ennallaan.
## 2026-11-24: Colab CUDA experiment bootstrap repair

Owner: Instinct. Branch: fix/cuda13-colab-bootstrap. Replaces the stdlib venv/ensurepip bootstrap with pinned uv installed through isolated pip --target. uv's native binary creates the locked project environment; inherited pip/uv/Python redirects stay stripped. Captures install stderr and reports distro venv repair guidance without changing the machine. Updates the experiment pin to the PyAV<19 compatibility commit. Two new regressions failed first and all 23 runner tests now pass; full Ruff passes. No GPU inference or driver change performed. Separate PR, no merge.

CUDA runtime follow-up: pin Kuulas experiment 5ba4e993c1a29b0bdaf21c4d6483ffb3104d0fd7 with Linux CUDA12 cuBLAS (and its required nvrtc dependency). The transcription child alone gets project cuBLAS/cuDNN library paths before launch. Added mocked isolation/path regression, failed first then passed, all 24 runner tests and full Ruff pass. No library symlinks or GPU claims. Actual T4 verification remains with the owner.

Optional Kuulas end-to-end stage: --kuulas-path calls local_whisper.local with tiny and low-memory override after Torch, reports nonempty aligned word records/flick timestamps and elapsed time, then runs the separate GPU transcription smoke. Two mocked result cases failed first, all26 runner tests and full Ruff pass. Reviewed subprocess boundaries, input validation and CPU-vs-GPU claims against actual local_whisper implementation. No real model/GPU execution here, no merge.

## 2026-11-27: Automixer Apple Silicon packaging

Separate packaging branch stacked above the GUI. Native PyInstaller bundle,
manifest-derived version, arm64-only standalone media binaries, frozen
Files/Folder synthetic-audio smoke and minimal JIT entitlements. One new
Mac-only workflow approved by owner: PRs build/test without signing secrets;
manual main builds sign, notarize, staple and publish a versioned DMG only
after the frozen smoke. Existing signing helpers and pinned media downloader
reused. No mic entitlement or third-party plug-in permission added. StdIO
retained for the GUI's isolated worker protocol. Source-path environment and
Homebrew PATH stripped for frozen acceptance. Local tests cover tool discovery,
platform refusal and build arguments, not a real Mac bundle. Own review traced
worker re-entry, media resolution, signing gates and draft-first publication.
Actual Mac freezing, hardened-runtime behavior and notarization remain pending.

Packaging review follow-up: PR job is now explicitly contents:read with no signing or publishing steps; the separate write-capable release job and each credential step require manual dispatch on main. PyInstaller is selected by a dedicated root dependency group, resolved through the existing hash-bearing uv.lock entry, rather than an ephemeral --with installation. Release collision preflight now lists published and draft tags and fails on either. Workflow boundary regression and permissions tests pass (15); actual frozen Mac and notarization checks remain pending.
