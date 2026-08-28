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
yhdistyminen ja niiden **kanavakertoimet**, `ClipGain` joka voittaa
`Gain`in, luiska joka päätyy tasolle eikä hiljaisuuteen, leikettä pidempi
luiska, nollan mittainen alue, vaimennettu raita, tuntematon attribuutti —
myös häivytyksen sisällä. `Conformance/plan.json` on sen vastaus, ja **molemmat toteutukset testaavat itseään sitä vasten**:

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

## Toistosäätimet

Soita ja tauko, kello (`kulunut / kesto`), ja aikajanalla osoitin joka
seuraa ääntä. Aikajanaa klikkaamalla tai raahaamalla kelataan; kelaus
toimii myös ennen ensimmäistä soittoa, jolloin soitto alkaa siitä mihin
osoitettiin.

Kolme asiaa, jotka näyttäisivät pikkuseikoilta mutta eivät ole:

**Osoittimen aika luetaan äänimoottorilta**, ei seinäkellosta.
`MixPlayer.currentTime` kysyy solmun omaa kelloa. `Timer` ja ääni ovat eri
kelloja, ja ne ajautuvat erilleen sitä enemmän mitä pidempi jakso — eli
osoitin ei olisi siinä mistä ääni kuuluu, mikä on ainoa asia jota osoitin
on olemassa näyttämään.

**Raahaus siirtää vain osoitinta; ääni kelataan kun nappi nousee.**
Raahaus tuottaa kymmeniä tapahtumia sekunnissa, ja jokainen oikea kelaus
ajastaisi koko miksauksen uudestaan — häivytetyt leikkeet luetaan
puskuriin, eli se on levyluku. Nykiminen osuisi juuri siihen hetkeen jossa
käyttäjä katsoo tarkkaan.

**Osoittimen liike mitätöi vain osoittimen kohdat**, ei koko aikajanaa.
Tunnin istunnossa on satoja palkkeja, ja 30 kertaa sekunnissa piirretty
koko aikajana olisi juuri sitä hitautta jonka takia esikatselu ei
renderöi. `draw(_:)` ohittaa palkit likaisen alueen ulkopuolelta.

Kelauksen geometria (sekunnit ↔ pisteet) on `NhsxKit`in
`TimelineGeometry`, ei näkymän sisällä, ja sillä on testit. Syy on sama
kuin `fitFades`illa: piirto ja osumatesti ovat sama kaava, ja jos ne
laskettaisiin erikseen, palkit näyttäisivät oikeilta ja klikkaus osuisi
väärään kohtaan. Kumpikaan puoli ei näyttäisi yksinään väärältä.

## Mitä tämä ei tee

Ei taajuuskorjausta, ei kompressointia, ei Hindenburgin ääniprofiileja. Se
on tarkoituksellinen lattia eikä tekemättä jäänyt työ: juuri siksi
esikatselu voi olla nopea. Istunnossa, jossa profiileja on käytetty, tämä
ei kuulosta Hindenburgin toistolta.

Panorointi on lisäksi **järjestelmän** panorointilailla
(`AVAudioPlayerNode.pan`), kun `nhsx-render` laskee kertoimet itse
Hindenburgin lailla — lineaarisesti ja vakiosummaisesti, mitattuna
Hindenburgin omasta renderistä. Lait eivät ole samat, joten kovasti laidalle
ajettu raita voi olla esikatselussa eri tasolla kuin renderöidyssä
tiedostossa. Oma laki vaatisi jokaisen leikkeen lukemisen puskuriin, eli
juuri sen nopeuden jonka takia tämä on olemassa.

`Conformance/plan.json` sitoo suunnitelman, ei toiston viimeistä desibeliä —
mutta se sitoo nyt myös panoroinnin **kanavakertoimet**, ei vain
panoroinnin lukua. Pelkkä luku on sama molemmilla toteutuksilla myös
silloin kun ne soveltavat eri lakia, eli juuri se ero jonka estämiseksi
tiedosto on olemassa ei näkyisi.

## `Info.plist` on lähde, ei generoinnin tulos

XcodeGenin `info:`-avain **kirjoittaa** plistin annettuun polkuun. Se ei
viittaa käsin kirjoitettuun tiedostoon vaan korvaa sen joka generoinnilla
omilla oletuksillaan. Kumpikin plist täällä oli sen alla, joten pakettiin
päätyi XcodeGenin versio eikä tämä.

Näkyvä oire oli versionumero: julkaisussa `viewer-v2026.8.28.1` `sed` asetti
version tagista, käännös oli vihreä, ja molemmissa paketeissa luki `1.0` /
`1` — XcodeGenin oletukset. Todellinen vahinko oli isompi. Sovelluksesta
puuttuivat `UTImportedTypeDeclarations` ja `CFBundleDocumentTypes`, eli
macOS ei tiennyt `.nhsx`:stä mitään; laajennuksesta puuttui koko
`NSExtension`-sanakirja, eli se ei ilmoittanut olevansa esikatselu
eikä olisi voinut rekisteröityä sellaiseksi. Julkaistu `.dmg` asentui,
avautui ja allekirjoitus kesti tarkistuksen. Välilyönti Finderissä ei olisi
vain tehnyt mitään.

Nyt kohteet asettavat `INFOPLIST_FILE`in, joka osoittaa tiedostoon
koskematta siihen. Sen mukana plistit omistavat myös ne avaimet jotka
XcodeGen ennen tuotti — `CFBundleExecutable` ennen kaikkea, ilman sitä
paketissa ei ole mitään käynnistettävää.

`build-viewer.yml` väittää kolme asiaa, koska yksikään niistä ei näy
vihreästä käännöksestä: lähdeplistit ovat generoinnin jälkeen ennallaan,
paketoidut plistit ilmoittavat esikatselupisteen ja `.nhsx`:n
tyyppitunnisteen, ja versio on tagin versio. macOS päättää
päivitystarjouksen `CFBundleVersion`ista, joten jumiin jäänyt numero
epäonnistuu tekemällä ei mitään — sama vikaluokka kuin muuallakin täällä.

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

### Äänipoolin lukuoikeus, ja mitä se maksaa

Tämä oli pitkään avoin kysymys. Se on nyt mitattu oikealla Macilla, ja
vastaus oli se ikävämpi: **hiekkalaatikko ei anna pääsyä äänipooliin.**

Quick Look antaa laajennukselle pääsyn vain siihen tiedostoon jonka päällä
välilyöntiä painettiin. `.nhsx` on pelkkä XML, ja WAVit ovat viereisessä
kansiossa. Esikatselu piirsi istunnon oikein — raidat, alueet, kesto,
puhujat — ja oli hiljaa.

Sama koskee **sovellusta**, toisin kuin täällä aiemmin luki: `NSOpenPanel`
antaa pääsyn valittuun tiedostoon eikä sen sisaruksiin, joten `.nhsx`:n
avaaminen ei riitä äänipoolin lukemiseen. Väite «sovelluksessa toisto
toimii joka tapauksessa» oli päättelyä eikä mittausta, ja se oli väärin.

Laajennus ei voi laajentaa omaa pääsyään ajossa. Hiekkalaatikko on sille
pakollinen, eikä Quick Look voi kysyä käyttäjältä kansio-oikeutta.

Ratkaisu on siksi oikeus, ei koodi:

    com.apple.security.temporary-exception.files.absolute-path.read-only
        /Users/     /Volumes/

**Luku, ei kirjoitus**, ja kahteen puuhun rajattuna eikä `/`:ksi. Hinta
sanottuna suoraan: jokainen jaettu kopio sisältää esikatselulaajennuksen,
joka voi lukea käyttäjän kotihakemiston. Se on tietoinen valinta, ei
huomaamatta jäänyt asetus.

Puhdas vaihtoehto on App Group ja käyttäjän myöntämä kansio-oikeus
(`bookmarkData(options: .withSecurityScope)`): pääsy rajautuisi niihin
kansioihin jotka käyttäjä itse antaa. App Group -tunnus vaatii Team ID:n
eli maksullisen Apple-kehittäjätilin. Kun sellainen on, tämä poikkeus
poistetaan ja korvataan sillä — ja se on samalla se päivä jolloin
notarisointi tulee mahdolliseksi, sillä notarisointi hylkää
temporary-exception-oikeudet.

Käännös tarkistaa, että oikeus on molemmissa paketeissa. Ilman sitä
tarkistusta vika palaisi juuri siinä muodossa jossa se löydettiin: kaikki
näyttää oikealta eikä ääntä kuulu.

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

`NhsxKit` kääntyy ja sen testit ajetaan jokaisessa puskussa
(`viewer.yml`, `swift test`), ja esikatselu on ajettu oikealla Macilla:
se rekisteröityy, piirtää istunnon ja kertoo lukemattomat attribuutit.

Swift kirjoitetaan yhä Linux-ympäristössä, jossa ei ole työkaluketjua, joten
CI on edelleen ensimmäinen kääntäjä jokaiselle muutokselle. Se ei ole sama
asia kuin kääntämätön, mutta se tarkoittaa ettei mitään Swift-muutosta ole
kokeiltu ennen kuin se on työnnetty.
