# NHSX Quick Look

Valitse Finderissä `.nhsx`, paina välilyöntiä, kuule jakso.

Esikatselu näyttää istunnon raidat ja alueet ja soittaa miksauksen —
alueiden paikat, vaimennukset, tasot, häivytykset ja panoroinnin.

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

Koska Quick Look -laajennus **ei ole asennettavissa yksin**. Se on paketti
sovelluksen sisällä (`NHSX Quick Look.app/Contents/PlugIns/…appex`), ja
järjestelmä löytää sen vain sitä kautta. Isäntäsovellus on siis pakollinen;
kysymys on vain siitä, mikä isäntä.

Vaihtoehto olisi ollut viedä laajennus `Podcast Magic.app`in sisään. Silloin
Finderin välilyönti vaatisi PyInstaller-paketin, jossa on Whisper, MLX ja
ffmpeg — reilusti yli gigatavun — jotta tiedostoa voi katsoa. Tämä on
muutama megatavu Swiftiä eikä tarvitse Pythonia lainkaan, ja toimii oli
Podcast Magic asennettu tai ei. Sama päättely kuin `nhsx-render`illä.

## Rakenne

```
Package.swift            NhsxKit SwiftPM-kirjastona: kääntyy ja testautuu
                         ilman Xcodea
Sources/NhsxKit/         .nhsx:n jäsennys, miksauksen päättely, toisto
                         — `Sources/` on kokonaan SwiftPM:n, jotta se ei
                         näe Xcode-kohteita eikä valita niistä
Extension/               laajennus: näkymä ja aikajana
App/                     isäntäsovellus, joka kantaa laajennuksen
Tests/NhsxKitTests/      yhdenmukaisuustesti
Conformance/             se yksi istunto ja sen kirjattu vastaus
project.yml              XcodeGen — `.xcodeproj`ia ei säilytetä repossa
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
uv run nhsx-render <staged session> --conformance > quicklook/Conformance/plan.json
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

Julkaisuista (`quicklook-v*`) latautuu kaksi asiaa:

**`NHSX-Quick-Look.dmg`** — vedä `NHSX Quick Look.app` Ohjelmat-kansioon ja
**avaa se kerran**. Avaaminen on se, mikä rekisteröi laajennuksen; ilman sitä
välilyönti ei tee mitään. Ikkunan saa sen jälkeen sulkea, ja esikatselu
toimii niin kauan kuin sovellus on Ohjelmat-kansiossa.

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
sama koodi toimi. Käännös tarkistaa molemmat (`build-quicklook.yml`).

### Yksi avoin kysymys, jota ei ole voitu mitata

Hiekkalaatikko antaa laajennukselle pääsyn **esikatseltavaan tiedostoon**.
Äänipooli on eri tiedostoja saman kansion sisällä, eikä ole varmaa antaako
järjestelmä niihin pääsyä samalla.

Jos ei anna, aikajana piirtyy normaalisti (se on pelkkää XML:ää) mutta
toisto vaikenee, ja `MixPlayer` kertoo mitkä tiedostot eivät auenneet — se
näkyy esikatselun alarivillä. Tämä selviää ensimmäisellä ajolla oikealla
Macilla; täältä sitä ei voi mitata.

## Kääntäminen

```
swift test                       # NhsxKit ja yhdenmukaisuustesti, ei Xcodea
brew install xcodegen
xcodegen generate                # tekee .xcodeproj project.yml:stä
xcodebuild -scheme NhsxQuickLookApp -configuration Release
```

Valmis `NHSX Quick Look.app` **Ohjelmat-kansioon**. Laajennus rekisteröityy
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
