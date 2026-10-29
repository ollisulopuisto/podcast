# Podcast Magic: keyboard discovery / näppäinoikoteiden löydettävyys

Local branch / paikallinen haara: `overnight/podcast-keyboard-discovery`.
Base / pohja: `5a179e6`.

## Implemented / toteutettu

The separate Podcast Magic proposal in `2026-10-25-contextual-controls.md` calls
for a small help sheet rather than a floating toolbar. Current source had no
keyboard listener. This branch adds one registry for both dispatch and help:
`?` or F1 opens a native dialog; Cmd/Ctrl+O opens the existing session picker;
Cmd/Ctrl+1–9 switches among the available tool tabs. A visible rail button opens
the same help. English and Finnish text is included.

Erillinen Podcast Magic -ehdotus pyytää pientä ohjetta kelluvan työkalupalkin
sijaan. Sama rekisteri ohjaa näppäimiä ja ohjetta. Näkyvä painike avaa ohjeen;
? tai F1 avaa saman dialogin. Cmd/Ctrl+O avaa istuntovalitsimen, numerot
vaihtavat käytettävissä olevaa välilehteä. Tekstit ovat suomeksi ja englanniksi.

Text inputs, textareas, selects and editable content keep their native keys.
Composition/repeats and unavailable tab numbers do nothing. Escape and modal
focus stay with the native dialog. There is deliberately no global Run key:
no job, export or audio processing starts from these shortcuts.

Tekstikenttien omat näppäimet säilyvät. Tekstin koostaminen, toistuvat painallukset
ja puuttuvat välilehdet eivät käynnistä komentoa. Escape ja kohdistus ovat
selaimen dialogin vastuulla. Globaalilla näppäimellä ei käynnistetä ajoa,
vientiä tai äänen käsittelyä.

## Verification / tarkistus

- Podcast Magic tests:367passed,1skipped (existing optional environment test).
  New Node regression covers help, tab bounds, text fields, modifier conflicts,
  composition/repeats and absence of a Run binding.
- Ruff0.17.2 check on changed Python test passes. JavaScript syntax check passes.
- Real Chrome screenshots inspected in English and Finnish at1280x820. Dialog
  text/key rows fit, close button and focus ring are visible, Escape and F1 work.
  Server state was mocked; no real session/audio processing or native Mac test.
- No dependency/lockfile changes intended, no version bump, workflow edit,
  push, release, merge, artifact upload or GitHub charge. Mac DMG is not built.

Testit367läpi,1ohitettu. Ohjeen molemmat kielet ja Escape/F1 tarkistettu oikeassa
selaimessa valepalvelimella. Tämä ei ole natiivi Mac -testi tai äänen kuuntelu.
Ei versiopäivitystä, työnkulun muutosta, GitHub-kulua tai valmista DMG:tä.
