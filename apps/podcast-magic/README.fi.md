# Podcast Magic

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

## Pikakäynnistys

macOS ja [uv](https://docs.astral.sh/uv/). Tyhjästä kloonista ikkunaan:

```
git clone https://github.com/ollisulopuisto/podcast
cd podcast
brew install ffmpeg
uv sync --all-packages --extra mlx
uv run podcast-magic ~/Podcast/jakso8/
```

Selain avautuu osoitteeseen `http://127.0.0.1:8741/`. `--gui` avaa selaimen
sijaan natiivin ikkunan.

Istunnon voi antaa kolmella tavalla:

```
uv run podcast-magic                    # uusin .nhsx tästä kansiosta
uv run podcast-magic "jakso 8.nhsx"     # tämä
uv run podcast-magic ~/Podcast/jakso8/  # uusin .nhsx tuosta kansiosta
```

### Kaksi asiaa `uv sync`istä

**Aja se työtilan juuressa ja anna `--all-packages`.** Tämä sovellus on yksi
työtilan jäsen autoraffkatin, automixerin ja jaetun `packages/speechmix`in
rinnalla, ja siitä seuraa kaksi asiaa jotka on parempi tietää etukäteen kuin
ihmetellä jälkikäteen:

* `uv sync --extra mlx` juuressa ei asenna **yhtään moottoria** — lisä kuuluu
  jäsenelle eikä työtilalle, joten sillä ei ole mitään mihin osua eikä siitä
  sanota mitään.
* `uv sync` **`apps/podcast-magic`in sisällä** synkronoi vain sen jäsenen ja
  **poistaa muiden jäsenten** riippuvuudet yhteisestä ympäristöstä.

`uv run podcast-magic` toimii mistä tahansa puun kohdasta; vain `uv sync`
välittää siitä missä seisot.

**Moottori valitaan lisällä.** `--extra mlx` Apple Siliconilla, `--extra
faster` Intel-Macilla. Molemmat yhtä aikaa käy myös — `--extra mlx --extra
faster` on se mitä CI asentaa — ja silloin ikkunan moottorivalitsimessa on
mistä valita.

## Käyttö

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

Neljä säädintä:

* **Häntä** — kuinka paljon puhetta jätetään sanan molemmin puolin. Sanan
  aikaleima on sanan reuna, ja tarkalleen reunasta katkaistu puhe kuulostaa
  katkaisulta.
* **Lyhin tauko** — tätä lyhyempää taukoa ei suljeta. Sanaväli on
  kymmenesosia; jos jokainen niistä vaiennettaisiin, raita naksuisi koko
  jakson ajan.
* **Tason tarkistus** — kun mikit vuotavat, Whisper kuulee naapurin puheen
  myös tältä raidalta ja kirjaa sen sinun sanoiksesi. Taso erottaa oman
  puheen vuodosta. Teksti ei erota — litteroinneissa ei ole edes samaa
  merkkijonoa, jota vertailla.
* **Erotus kovimpaan** — kummalle raidalle sana kuuluu. Ks. alla.

Tason tarkistus purkaa jokaisen raidan levyltä, joten se ajetaan työssä eikä
säätimien alla olevassa ennakossa. Ennakko sanoo sen itse.

### Yksi huone, ja jokainen mikki kuulee jokaisen

Kynnys yksinään ei tähän pysty. Hiljaisessa studiossa hyvillä mikeillä vuoto
ei ole hiljaista — se on *hiljaisempaa*, ja vain suhteessa siihen mikkiin
jonka edessä puhuja istuu. Oikealla jaksolla mitattuna:

* molemmat mikit ylittävät kynnyksen **41 % ajasta**,
* mutta vuoto on mediaanissa **12,8 dB** hiljempaa kuin sama puhe omalla
  mikillä.

Erottava tekijä ei siis ole taso vaan **raitojen välinen ero samalla
hetkellä**. Absoluuttinen taso liikkuu jokaisen mikin esivahvistuksen
mukana; raitojen välinen ero ei liiku. Sana jää sille raidalle jolla se on
kovimmillaan, ja niille jotka ovat **erotus kovimpaan** ‑kaistan sisällä
siitä.

Kaista eikä «kovin vie kaiken», ja se on tarkoituksellista. 6 dB jättää
mitatusta 12,8 dB:n erosta noin 6,8 dB pelivaraa, joten aito päällekkäinen
puhe — keskeytykset, naurut, se mikä tekee keskustelusta keskustelun — jää
läpi, mutta vuoto ei. Kova sääntö «vain yksi kerrallaan» leikkaisi juuri
ne. Nolla ottaa vertailun pois; se on pois päältä eikä nollan desibelin
kaista.

Sanaa jonka tasoa ei jollain raidalla saatu mitattua ei pudoteta sen raidan
takia: tiedon puute ei ole päätös vaientaa. Sama sääntö kuin puuttuvalla
tiedostolla. Yhdellä raidalla ei ole mihin verrata, joten vertailua ei ajeta
ja se sanotaan lokissa.

Sama päätös samasta mittauksesta kuin autoraffkatin ``duck_dominance_db``,
jossa se ohjaa vaimennusta eikä vaientamista.

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
