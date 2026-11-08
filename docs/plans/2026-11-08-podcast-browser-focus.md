# Podcast Magic file-browser focus repair, PR 196

Opening the browser focuses Close. Folder navigation now focuses the first
child folder, then the first session file if there are no child folders.
An empty folder focuses its parent entry, or Close at the filesystem root.
The file browser stays nonmodal (`aria-modal="false"`): Tab may leave it.
This is focus management, not a focus trap. Escape still closes it and returns
focus to Change.

The existing UI smoke test now tracks focus and covers initial opening,
repeated folder activation, file-only folders, empty folders, an empty root,
and return focus. Before the implementation it failed with Close focused
instead of the child folder.

Validation:

- Podcast Magic suite: 375 passed, 1 macOS-only CFBundleName test skipped.
- UI tests: 12 passed, including the Node behavior smoke test.
- Full-repository Ruff: passes.
- Workspace contract suite: 244 passed, 1 failed because zsh is unavailable
  locally (PermissionError when trying to execute it), 12 subtests passed.
- Real Chrome with mocked API state, 1280 x 820: Ctrl+O focuses Close;
  Tab/Enter navigates twice without dismissal; the folder outline is visible;
  Tab leaves the nonmodal browser; Escape closes it and restores focus.
  Initial and navigation screenshots inspected. No page errors.
- No native macOS file-picker or audio-pipeline validation in this change.

No version, dependency, lockfile, workflow or changelog changes. No merge,
release or build dispatch.

## Suomeksi

Avaaminen kohdistaa Sulje-painikkeeseen. Kansion vaihto kohdistaa ensimmäiseen
alikansioon tai istuntotiedostoon. Tyhjässä kansiossa kohde on ylös-painike,
tyhjässä juuressa Sulje. Selain pysyy ei-modaalisena: sarkain saa siirtyä
muualle sivulle. Escape sulkee selaimen ja palauttaa kohdistuksen Vaihda-nappiin.

Käyttöliittymän savutesti seuraa kohdistusta ja tarkistaa avaamisen, toistuvan
kansiopainalluksen, vain tiedostoja sisältävän kansion, tyhjän kansion, tyhjän
juuren ja kohdistuksen palautuksen. Testi epäonnistui ennen korjausta, koska
kohdistus jäi Sulje-painikkeeseen alikansion sijaan.

Sovelluksen testit: 375 läpi, yksi macOS:n CFBundleName-testi ohitettu.
Käyttöliittymän 12 testiä ja koko repon Ruff läpi. Työtilan testeistä 244 läpi,
yksi epäonnistui koska zsh ei käynnisty paikallisesti; 12 alitestiä läpi.
Oikealla Chromella ja valepalvelimella tarkistettiin avaus, kaksi peräkkäistä
Enter-siirtymää, näkyvä kohdistuskehys, sarkaimella poistuminen ja Escape.
Kuvat tarkistettu, ei sivuvirheitä. Natiivia Mac-valitsinta tai ääniketjua ei
kokeiltu. Ei versio-, riippuvuus-, lukko-, työnkulku- tai muutoslokimuutoksia,
ei yhdistämistä eikä julkaisun tai paketoinnin käynnistystä.

## Concurrent update follow-up / rinnakkaisen päivityksen korjaus

A concurrent commit replaced the tested child-first behavior with the first
enabled button (Up) and removed the assertions. Restored the child-first
selection and tests on top of that commit, retaining its boolean `initial`
parameter. Added this Finnish counterpart to keep the work note bilingual.

Rinnakkainen päivitys korvasi alikansioon kohdistamisen ensimmäisellä käytössä
olevalla painikkeella (ylös) ja poisti testiväitteet. Palautettu alikansion
valinta ja testit päivityksen päälle, säilyttäen sen totuusarvoparametri
`initial`. Lisätty suomenkielinen vastine. Sovellustestit, Ruff ja Chrome-
tarkistus ajettu uudestaan onnistuneesti.
