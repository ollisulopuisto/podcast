# Work log

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
