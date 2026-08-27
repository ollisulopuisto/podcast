# Podcast Magic

> **Siirtynyt.** Kehitys jatkuu repositoriossa
> [ollisulopuisto/podcast](https://github.com/ollisulopuisto/podcast)
> hakemistossa `apps/podcast-magic`, autoraffkatin, automixerin ja jaetun
> `packages/speechmix`-paketin rinnalla. Tämä repositorio on arkisto: alla
> oleva koodi on täydellinen ja ajettava, mutta sitä ei enää päivitetä.

Kaksi Hindenburg-työvaihetta omalla Macilla Google Colabin sijaan: istunnon
äänipoolin litterointi ja hiljaisten kohtien vaimennus. Yksi ikkuna, yksi
istuntotiedosto, kaksi työkalua — ja tilaa kolmannelle.

*[README in English](README.md)*

* **Litterointi ajetaan näytönohjaimella.** Whisper Applen MLX:llä, eli
  Metalilla. Ei latausta pilveen, ei kesken katkeavaa ajoympäristöä, ei
  Driven liittämistä.
* **Istunto on formaatti.** Molemmat työkalut lukevat ja kirjoittavat samaa
  `.nhsx`-tiedostoa. Sanat menevät äänipooliin aikoineen, ja vaimennus lukee
  ne sieltä ja pilkkoo raidat.
* **Mitään ei kirjoiteta yli.** Jokainen ajo tekee uuden tiedoston lähteen
  viereen, ja jos sellainen on jo, seuraavasta tulee `… v2`.

## Asennus

```
uv sync --extra mlx        # Apple Silicon — se nopea
uv sync --extra faster     # Intel-Mac tai toinen mielipide
brew install ffmpeg        # äänen purku; käännetyssä sovelluksessa mukana
```

## Käyttö

```
uv run podcast-magic                    # etsii uusimman istunnon täältä
uv run podcast-magic "jakso 8.nhsx"
uv run podcast-magic ~/Podcast/jakso8/
```

Selain avautuu osoitteeseen `http://127.0.0.1:8741/`. Sovellukseksi
käännettynä ohjelma avaa oman ikkunansa.

Työjärjestys:

1. Äänitä ja aseta istunto Hindenburgissa. Tallenna.
2. **Litterointi** — kirjoittaa `jakso 8 litteroitu.nhsx`.
3. Avaa se Hindenburgissa jos haluat lukea, tai jatka suoraan.
4. **Vaimennus** — kirjoittaa `jakso 8 litteroitu vaimennettu.nhsx`.
5. Avaa se Hindenburgissa. Jokainen tauko on vaimennettu alue, jonka saa
   takaisin kuuluviin.

## Mikä Whisper

| Moottori | Missä ajaa | Milloin |
|---|---|---|
| `mlx-whisper` | Applen GPU, Metalilla | **oletus Apple Siliconilla** |
| `faster-whisper` | Suoritin, int8 | Intel-Macit, tai toinen mielipide |

Kolmatta vaihtoehtoa ei tähän ole. `faster-whisper` on sama moottori kuin
Colab-muistikirjassa, ja CTranslate2:ssa ei ole Metal-taustaa lainkaan — se
ajaa Macilla suorittimella, joten `--compute_type auto` ei löydä
näytönohjainta käytettäväksi. MLX ajaa saman mallin GPU:lla ilman erillistä
muunnosvaihetta.

Molemmat tuottavat sanatarkat aikaleimat, ja vain sillä on tässä merkitystä:
`.nhsx`-litterointi on lista `<w>`-elementtejä, joilla on alku ja pituus, ja
vaimennuksen koko päätös rakentuu niistä. Muistikirjan `--max_line_width` ja
`--max_line_count` muotoilivat vain tekstitystiedostoja, eivätkä ne ole enää
mukana.

Mallien painoja ei paketoida. Ensimmäinen ajo lataa mallin Hugging Facesta —
`large-v3-turbo` on gigatavun luokkaa — ja se jää sen jälkeen välimuistiin.

### Täytesanat ovat tarkoituksella mukana

Whisper siistii puheen ellei toisin sanota. Muistikirja otti sen pois päältä
`--suppress_tokens "" --suppress_blank False`illa, ja niin tekee tämäkin,
koska «tota noin» on puhetta: ilman sitä vaimennus sulkee puolikkaan sekunnin
kohdalta, jossa joku selvästi puhui.

## Vaimennus

Puhejaksot tulevat litteroinnista, eivät tasokynnyksestä. Sanan aikaleima on
**tiedoston** aikaa; alue kertoo mistä kohtaa tiedostoa se alkaa (`Offset`)
ja mihin kohtaan aikajanaa se on sijoitettu (`Start`), joten sana osuu
kohtaan `Start + (s - Offset)`. Muunnos tehdään alueittain, koska sama
tiedosto voi esiintyä aikajanalla useaan kertaan.

Kolme säädintä:

* **Häntä** — kuinka paljon puhetta jätetään sanan molemmin puolin. Sanan
  aikaleima on sanan reuna, ja tarkalleen reunasta katkaistu puhe kuulostaa
  katkaisulta.
* **Lyhin tauko** — tätä lyhyempää taukoa ei suljeta. Sanaväli on
  kymmenesosia; jos jokainen niistä vaiennettaisiin, raita naksuisi koko
  jakson ajan.
* **Tason tarkistus** — kun mikit vuotavat, Whisper kuulee naapurin puheen
  myös tältä raidalta ja kirjaa sen sinun sanoiksesi. Taso erottaa oman
  puheen vuodosta. Teksti ei erota.

Tason tarkistus purkaa jokaisen raidan levyltä, joten se ajetaan työssä eikä
säätimien alla olevassa ennakossa. Ennakko sanoo sen itse.

## Kun käsikirjoitusnäkymän kohdistin jää jumiin

Hindenburgilla on kaksi näkymää samaan litterointiin. Aikajana piirtää sanat
alueen sisään, jolloin muunnosta ei tarvita — sana on siinä missä alue on.
Käsikirjoitusnäkymä on erillinen dokumentti, ja seuratakseen toistokohdistinta
sen pitää rakentaa aikaindeksi. **Epäonnistunut indeksi osoittaa alkuun**,
mikä on täsmälleen tämä oire.

Formaattia ei ole dokumentoitu, joten työkalu mittaa eikä arvaa:

```
uv run podcast-magic --inspect "jakso 8 litteroitu.nhsx"
```

tai **Tarkista litterointi** litterointipaneelissa. Se raportoi poolin
tiedostoittain neljä asiaa, jotka voisivat rikkoa aikaindeksin:

* **backwards** — sana joka alkaa ennen edellistä. Whisper tuottaa näitä, kun
  lämpötilan pudotus siirtää aikaleimoja segmentin rajalla. Puolitushaku
  järjestämättömän listan yli ei palauta virhettä vaan väärän kohdan, usein
  ensimmäisen.
* **overlap** — sana joka alkaa ennen kuin edellinen loppuu.
* **empty** — nolla tai negatiivinen pituus.
* **outside_regions** — sana, jota yksikään alue ei sijoita aikajanalle.
  Alueen alun trimmaus Hindenburgissa jättää leikatun puheen litterointiin:
  aikajananäkymä ei piirrä sitä ja näyttää oikealta, käsikirjoitusnäkymä
  näyttää sen eikä voi olla samaa mieltä soittimen kanssa.

Kaksi muuta raportoidaan huomioina eikä vikoina, koska ne ovat epäiltyjä
eivätkä mittaustuloksia: kaikki yhdessä `<p>`:ssä, ja jokainen sana
`sp="UU"`.

Kirjoittaja estää nyt kolme ensimmäistä rakenteellisesti — sanat lajitellaan,
päällekkäisyys korjataan lyhentämällä edeltävää sanaa (ei koskaan siirtämällä
seuraavaa, koska alkuaika on se mihin kohdistin osuu), ja pituudella on
lattia. **Jaa kappaleisiin** on oletuksena päällä ja sen voi ottaa pois,
jolloin saman istunnon voi ajaa molemmin tavoin ja verrata; asetus on mukana
tunnisteessa, joten toinen ajo todella ajaa uudestaan.

Mikä ratkaisisi asian: `.nhsx`, jossa Hindenburgin oma litterointi ohjaa
käsikirjoitusnäkymää oikein. Sen rakenne on totuus siitä, mitä `<p>`:ssä ja
`sp`:ssä pitäisi olla.

## Sovelluksen kääntäminen

```
uv run --extra mlx python scripts/build_app.py --dmg
```

PyInstaller pakkaa koodin, staattisen `ffmpeg`in ja sen Whisper-moottorin
joka on asennettu käännösympäristöön — mukaan lukien MLX:n Metal-varjostimet,
joita ilman sovellus ei litteroi. Tulos on `dist/Podcast Magic.app`.

## Uusi moduuli

Moduuli on neljä asiaa: avain, nimi, `APIRouter` ja yksi `mod_*.js`, joka
rekisteröi paneelin. `modules.py` luettelee ne; kuori ja palvelin eivät
muutu. Istuntovalitsin ja työjono ovat kuoressa, joten uusi moduuli perii
molemmat.

Aiottu kolmas on [automixerin](https://github.com/ollisulopuisto/automixer)
puheenkäsittelyketju. `nhsx/pipeline.py` tarjoaa istunnon jo siinä muodossa
jota ketju odottaa — raita, jolla on puhuja ja lista jaksoja
ohjelma-aikajanalla — joten jäljellä on ketju itse, ei putkitus.

## Rakenne

```
src/podcastmagic/
  __main__.py  gui.py  server/      kuori: ikkuna, palvelin, staattinen UI
  jobs.py                           yksi taustatyö kerrallaan, edistymisineen
  nhsx/                             istuntoformaatti — kaikkien moduulien yhteinen
  transcribe/  backends/            Whisper: yksi rajapinta, monta moottoria
  silence/                          puhejaksot, alueiden pilkkominen
  modules.py                        rekisteri
```

Koodi, kommentit ja docstringit ovat suomeksi; käyttöliittymä ja
dokumentaatio suomeksi ja englanniksi.

## Lisenssi

MIT.
