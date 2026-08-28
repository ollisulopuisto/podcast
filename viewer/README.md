# NHSX Viewer

Hindenburgin istunto auki ilman Hindenburgia: raidat, alueet ja miksaus
kuultavana.

**Sovellus** avaa `.nhsx`-tiedoston — Arkisto → Avaa…, kaksoisklikkaus
Finderissä tai raahaamalla. **Quick Look -laajennus** näyttää *saman
näkymän* esikatselupaneelissa, kun valitset `.nhsx`:n ja painat välilyöntiä.

Järjestys on tämä päin: katselin on tuote, esikatselu on sen toinen pinta.
Laajennus tarvitsee isäntäsovelluksen joka tapauksessa — macOS ei asenna
`.appex`iä yksin — ja isäntä joka ei tee mitään on isäntä jota kukaan ei
avaa. Koska laajennus rekisteröityy vasta kun sovellus on kerran avattu,
tyhjä isäntä olisi myös se syy, jonka takia esikatselu ei koskaan ilmesty.

## Miksi tämä ei ole `apps/`in alla

Se rikkoisi työtilan. Juuren `pyproject.toml` sanoo
`members = ["packages/*", "apps/*"]`, ja `uv` vaatii jokaiselta osumalta
`pyproject.toml`in. Swift-hakemisto siellä kaataa `uv sync`in **koko
työtilalta**, kaikilta:

```
error: Workspace member `/…/apps/probe-swift` is missing a `pyproject.toml`
       (matches: `apps/*`)
```

Siksi tämä on juuressa. Sen julkaisutyönkulku on silti
`.github/workflows/`issa kuten kaikkien muidenkin — GitHub ajaa vain
juuren työnkulut.

Tästä seuraa myös, ettei tämä ole työtilan jäsen: yksi Python-alaraja, yksi
lukkotiedosto ja yksi `pytest`-muoto eivät koske sitä. `tests/`in
jäsenväitteet eivät muutu.

## Miksi tämä on oma sovelluksensa

Vaihtoehto olisi ollut viedä laajennus `Podcast Magic.app`in sisään. Silloin
istunnon katsominen vaatisi PyInstaller-paketin, jossa on Whisper, MLX ja
ffmpeg — reilusti yli gigatavun. Tämä on muutama megatavu Swiftiä eikä
tarvitse Pythonia lainkaan, ja toimii oli Podcast Magic asennettu tai ei.
Sama päättely kuin `nhsx-render`illä.

## Rakenne

```
Package.swift            kaksi SwiftPM-kirjastoa: kääntyvät ja testautuvat
                         ilman Xcodea
Sources/NhsxKit/         .nhsx:n jäsennys, miksauksen päättely, toisto
Sources/NhsxViewer/      **näkymä** — aikajana, tiedot ja toistopainike
                         — `Sources/` on kokonaan SwiftPM:n, jotta se ei
                         näe Xcode-kohteita eikä valita niistä
App/                     katselin: ikkuna, Avaa…, veto ja pudotus
Extension/               Quick Look -kuori, ~30 riviä
Tests/NhsxKitTests/      yhdenmukaisuustesti
Conformance/             se yksi istunto ja sen kirjattu vastaus
project.yml              XcodeGen — `.xcodeproj`ia ei säilytetä repossa

## Yksi näkymä, kaksi pintaa

`NhsxViewer.SessionView` on koko käyttöliittymä, ja sekä sovellus että
laajennus näyttävät sen. Kumpikaan ei piirrä mitään omaa: `App/` antaa sille
tiedoston jonka käyttäjä avasi, `Extension/` sen jonka Finder esikatselee.

Syy on sama kuin `Conformance/`in: kaksi toteutusta samasta asiasta ajautuu
erilleen. Jäsentimien kohdalla sitä ei voi estää jakamalla koodi, koska
laajennus ei voi ajaa Pythonia — näkymien kohdalla voi, joten jaetaan.
```

Jako on tämä siksi, että se osa jonka **on oltava samaa mieltä Pythonin
kanssa** testautuu ilman Xcodea. Vain laajennus ja isäntä tarvitsevat
Xcode-projektin, koska macOS-laajennus on paketti eikä kirjasto.

## Kaksi toteutusta, yksi vastaus

`NhsxKit` jäsentää `.nhsx`:n uudestaan Swiftillä. Se ei ole valinta:
**laajennus on hiekkalaatikossa eikä voi käynnistää `nhsx-render`iä.**
Koodin jakaminen ei siis ole vaihtoehto.

Vastauksen jakaminen on. `Conformance/session.nhsx` on istunto, joka on
kirjoitettu erottamaan ne kohdat joissa kaksi jäsennintä voi mennä eri
mieltä huomaamatta — nimiavaruudet, kaksi aikamuotoa, `Muted="True"` vastaan
`Muted="1"`, raidan ja alueen vahvistuksen kertautuminen, panorointien
yhdistyminen, leikettä pidemmät häivytykset, nollan mittainen alue,
vaimennettu raita, tuntematon attribuutti. `Conformance/plan.json` on sen
vastaus, ja **molemmat toteutukset testaavat itseään sitä vasten**:

| | |
|---|---|
| Python | `apps/podcast-magic/tests/test_conformance.py` |
| Swift | `Tests/NhsxKitTests/ConformanceTests.swift` |

Jos ne eroavat, esikatselu näyttää eri jakson kuin `nhsx-render` renderöi —
eikä kumpikaan kaadu. Se on tämän talon vikaluokka, ja tämä on se este.

Vastaus on **käsin tarkistettu**, ei koneen kirjaama. Uudelleenluonti on
tahallinen teko ja sen diffi luetaan:

```
uv run nhsx-render <staged session> --conformance > viewer/Conformance/plan.json
```

Muuttunut luku on joko korjaus tai regressio, eikä sitä erota muuten kuin
katsomalla.

## Esikatselu ei renderöi

`nhsx-render` summaa näytteet itse, koska se kirjoittaa tiedoston.
Esikatselun ei tarvitse: `MixPlayer` sijoittaa lähteet aikajanalle ja antaa
järjestelmän summata ne toiston aikana. Välilyönnin ja äänen välissä on
tiedoston avaus, ei renderöinti, joten tunnin istunto avautuu yhtä nopeasti
kuin minuutin.

Solmuja on yksi per **(puhuja, taso, panorointi)** eikä per leike:
vaimennuksen läpi ajettu istunto on satoja pikkualueita raitaa kohden, ja
ne jakavat raidan faderin, joten pilkottu raita on yksi ryhmä.

Häivytetyt leikkeet ovat poikkeus — häivytystä ei voi ajastaa solmun
ominaisuutena palakohtaisesti — joten ne luetaan puskuriin ja verhokäyrä
kerrotaan sisään. Niitä on käytännössä musiikkipohjan alku ja loppu.

## Mitä tämä ei tee

Ei taajuuskorjausta, ei kompressointia, ei Hindenburgin ääniprofiileja. Se
on tarkoituksellinen lattia eikä tekemättä jäänyt työ: juuri siksi
esikatselu voi olla nopea. Istunnossa, jossa profiileja on käytetty, tämä
ei kuulosta Hindenburgin toistolta.

Panorointi on lisäksi **järjestelmän** panorointilailla
(`AVAudioPlayerNode.pan`), kun `nhsx-render` laskee vakiotehoiset kertoimet
itse. Lait ovat lähellä toisiaan mutta eivät välttämättä samat, joten kovasti
laidalle ajettu raita voi olla esikatselussa aavistuksen eri tasolla kuin
renderöidyssä tiedostossa. Oma laki vaatisi jokaisen leikkeen lukemisen
puskuriin, eli juuri sen nopeuden jonka takia tämä on olemassa.
`Conformance/plan.json` sitoo suunnitelman, ei toiston viimeistä desibeliä.

## Asentaminen

Julkaisuista (`viewer-v*`) latautuu kaksi asiaa:

**`NHSX-Viewer.dmg`** — vedä `NHSX Viewer.app` Ohjelmat-kansioon. Sillä voi
avata `.nhsx`-istunnon heti.

**Avaa sovellus kerran**, niin sama näkymä tulee myös Finderin
esikatseluun. Avaaminen on se, mikä rekisteröi laajennuksen; ilman sitä
välilyönti ei tee mitään. Esikatselu toimii niin kauan kuin sovellus on
Ohjelmat-kansiossa.

**`nhsx-render-macos-*.tar.gz`** — yksi binääri, ffmpeg mukana:

```
tar xzf nhsx-render-macos-*.tar.gz
xattr -d com.apple.quarantine nhsx-render
./nhsx-render "jakso 8.nhsx"
```

### Ensimmäinen avaus, ja miksi se on hankala

Kumpikaan ei ole Applen notarisoima: siihen tarvitaan Developer ID, jota
tällä repositoriolla ei ole. Sama koskee `autoraffkat`ia ja Podcast Magicia,
eli tämä ei ole tässä uutta.

Sovellus: oikea klikkaus ja «Avaa», tai Järjestelmäasetukset → Tietosuoja ja
turvallisuus → «Avaa silti». Komentorivityökalu:
`xattr -d com.apple.quarantine nhsx-render`.

Jos esikatselu ei ilmesty avaamisen jälkeenkään:

```
qlmanage -r          # Quick Look lukee laajennukset uudestaan
```

Laajennus on **ad-hoc-allekirjoitettu ja hiekkalaatikossa**. Kumpikin on
pakollinen eikä valinta: allekirjoittamaton laajennus ei rekisteröidy, ja
julkaistuja Quick Look -laajennuksia on jäänyt toimimattomiksi juuri
`com.apple.security.app-sandbox`in puuttuessa — paikallisesti käännettynä
sama koodi toimi. Käännös tarkistaa molemmat (`build-viewer.yml`).

### Yksi avoin kysymys, jota ei ole voitu mitata

Sovelluksessa tätä ei ole: käyttäjä valitsee tiedoston itse, ja
`com.apple.security.files.user-selected.read-only` kattaa sen.

Laajennuksessa on. Hiekkalaatikko antaa sille pääsyn **esikatseltavaan
tiedostoon**.
Äänipooli on eri tiedostoja saman kansion sisällä, eikä ole varmaa antaako
järjestelmä niihin pääsyä samalla.

Jos ei anna, aikajana piirtyy normaalisti (se on pelkkää XML:ää) mutta
toisto vaikenee, ja `MixPlayer` kertoo mitkä tiedostot eivät auenneet — se
näkyy alarivillä. Tämä selviää ensimmäisellä ajolla oikealla Macilla;
täältä sitä ei voi mitata. **Sovelluksessa toisto toimii joka tapauksessa**,
joten pahimmillaankin esikatselu on katselu ilman ääntä.

## Kääntäminen

```
swift test                       # NhsxKit ja yhdenmukaisuustesti, ei Xcodea
brew install xcodegen
xcodegen generate                # tekee .xcodeproj project.yml:stä
xcodebuild -scheme NhsxViewerApp -configuration Release
```

Valmis `NHSX Viewer.app` **Ohjelmat-kansioon**. Laajennus rekisteröityy
kun sovellus on siellä ja se on kertaalleen avattu; `qlmanage -r` pakottaa
Quick Lookin lukemaan laajennukset uudestaan.

## Jos esikatselu ei ilmesty

`.nhsx` ei ole järjestelmän tuntema tyyppi, ja sovellus **tuo** sen
(`UTImportedTypeDeclarations`) tunnisteella `com.hindenburg.nhsx`. Tuo eikä
vie: muoto on Hindenburgin, ei tämän sovelluksen.

Jos Hindenburg itse on asennettu ja julistaa saman päätteen **eri**
tunnisteella, järjestelmä suosii sitä, eikä laajennuksen
`QLSupportedContentTypes` osu. Oikean tunnisteen näkee omalta koneelta:

```
mdls -name kMDItemContentType "jokin jakso.nhsx"
```

Jos se ei ole `com.hindenburg.nhsx`, korjaa arvo
`Extension/Info.plist`iin ja käännä uudestaan. Tätä ei ole
arvattu valmiiksi oikein, koska tässä ympäristössä ei ole Hindenburgia eikä
macOS:ää mitattavaksi.

## Tämän tilanne

`NhsxKit` ja sen testit ovat kirjoitetut mutta **ei käännetty**: ne
syntyivät Linux-ympäristössä, jossa ei ole Swift-työkaluketjua eikä macOS:ää.
Ensimmäinen `swift test` Macilla on siis myös ensimmäinen käännös. Toisin
kuin `nhsx-render`, jonka jokainen väite on ajettu ja mitattu, tämä on
tarkistamatta siihen asti.
