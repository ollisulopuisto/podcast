# Podcast Magic

Hindenburgin istunto sisään, Hindenburgin istunto ulos. Kaksi työkalua
saman `.nhsx`-tiedoston ympärillä, tilaa kolmannelle.

Koodi, kommentit ja docstringit ovat **suomeksi** — ne ovat tekijöille.
Käyttöliittymä ja dokumentaatio ovat suomeksi ja englanniksi. Pidä se niin.

## Istunto on ainoa yhteys moduulien välillä

`nhsx/` on kaikkien moduulien yhteinen, `transcribe/` ja `silence/` eivät
tunne toisiaan. Litterointi kirjoittaa sanat äänipooliin, vaimennus lukee ne
sieltä. Jos moduuli alkaa tarvita toisen sisäistä tilaa, se kuuluu `nhsx/`:ään
tai ei kuulu tänne.

Uusi moduuli on neljä asiaa: merkintä `modules.py`:ssä, `APIRouter`, yksi
`mod_*.js` ja mahdollisesti oma alipaketti. Kuori (`server/app.py`, `app.js`)
ei muutu. Istuntovalitsin ja työjono ovat kuoressa, joten moduuli perii ne.

## Sanan aika on tiedoston aikaa

`<w s="…">` on aikaa **tiedoston** alusta. Alueen `Offset` kertoo mistä
kohtaa tiedostoa alue alkaa ja `Start` mihin kohtaan aikajanaa se on
sijoitettu, joten sana osuu aikajanalla kohtaan `Start + (s - Offset)`.
Muunnos tehdään alueittain, koska sama tiedosto voi esiintyä aikajanalla
useaan kertaan.

Sama kaava toiseen suuntaan on `nhsx/pipeline.py`:n `Span.file_time`, ja se
on kaikki mitä ääniketju tarvitsee aikajanasta tietää.

Väärä muunnos ei näy XML:ssä mitenkään: tiedosto avautuu, alueet ovat oikean
mittaisia ja ääni tulee väärästä kohtaa tiedostoa.

## Nopein Whisper Macilla on MLX, ja syy kannattaa tietää

CTranslate2:ssa (faster-whisper) **ei ole Metal-taustaa lainkaan**. Macilla
se ajaa suorittimella, ja Colab-muistikirjan `--compute_type auto` ei löydä
näytönohjainta käytettäväksi. MLX ajaa saman mallin GPU:lla. Ero on
kertaluokka, ja siksi `mlx` on ensimmäisenä `BACKENDS`-listassa — valinta
`auto` ottaa listasta ensimmäisen asennetun.

`faster-whisper` on silti mukana: Intel-Macit, ja toinen mielipide silloin
kun tulos näyttää oudolta.

Ääni annetaan moottorille **valmiiksi puretuna taulukkona**, ei polkuna.
mlx-whisperin oma `load_audio` kutsuu ffmpegiä PATHista, ja pakatussa
sovelluksessa PATHissa ei ole mitään — binääri on paketin sisällä. Polkua
antamalla litterointi toimisi kehityskoneella ja kaatuisi valmiissa
`.app`-paketissa.

`mlx_whisper.transcribe` on **funktio**, ei alimoduuli: paketin `__init__`
tekee `from .transcribe import transcribe` ja varjostaa samannimisen
moduulin. Myös `import mlx_whisper.transcribe as x` päätyy funktioon. Moduuli
haetaan `sys.modules`ista, ja siitä paikataan `tqdm` edistymisen lukemiseksi
— ilman sitä tunnin jakso etenee ilman yhtään merkkiä etenemisestä.

## Tunniste, ei muutosaika

Valmis litterointi luetaan levyltä JSONina. Se, milloin sen saa lukea, on
`Options.fingerprint()`: malli, kieli, täytesanat ja hiljaisuuden suodatus.
Ilman tunnistetta mallin vaihtaminen ei tekisi mitään — vanha tulos löytyisi
levyltä eikä uutta mallia ajettaisi, eikä siitä sanottaisi mitään.

Kenttäluettelo on kirjoitettu käsin `test_fingerprint_fields_are_written_out_by_hand`iin,
jotta uusi asetus ei livahda tunnisteeseen tai siitä pois huomaamatta.

## Käsikirjoitusnäkymän kohdistin: mitä tiedetään ja mitä ei

Oire: aikajananäkymässä sanat osuvat kohdalleen, käsikirjoitusnäkymässä
toistokohdistin jää alkuun. Näkymät lukevat samaa dataa mutta eri tavalla:
aikajana piirtää sanat alueen sisään (muunnosta ei tarvita), käsikirjoitus on
erillinen dokumentti joka tarvitsee aikaindeksin. Epäonnistunut indeksi
osoittaa alkuun.

Syytä **ei tiedetä**. Formaattia ei ole dokumentoitu, eikä Hindenburgin omaa
litterointia ole vertailtavaksi. `nhsx/verify.py` on lista epäiltyjä, ei
diagnoosi, ja se erottaa vian (mitattavasti väärin) huomiosta (rakenteellinen
tosiasia tuotoksestamme). Älä muuta sitä diagnoosiksi ilman mittausta.

`nhsx/write.py` estää kolme epäiltyä rakenteellisesti: sanat lajitellaan,
päällekkäisyys korjataan **lyhentämällä edeltävää** sanaa eikä siirtämällä
seuraavaa (alkuaika on se mihin kohdistin osuu, ja siirtäminen kasaisi
virheen eteenpäin koko tiedoston läpi), ja pituudella on lattia.

`Options.paragraphs` on olemassa vertailua varten eikä mieltymyksenä: sama
istunto kahdella asetuksella kertoo onko kappalejako syy. Se on siksi myös
tunnisteessa — muuten toinen ajo lukisi ensimmäisen tuloksen levyltä eikä
vertailua tapahtuisi.

`sp="UU"` jätetään ennalleen, koska aikajananäkymä toimii sillä. Oikeaa
arvoa ei arvata: väärä puhujatunnus voisi rikkoa sen mikä nyt toimii.

## Ominaisuus, joka ei tuottanut mitään, sanoo sen

Tämän luokan viat ovat kaikki samanlaisia: kelvollinen tiedosto, puhdas ajo,
ei poikkeusta, väärä tulos — ja se huomataan vasta kuuntelemalla, jolloin
leikkaus on jo tehty käsin eikä sitä voi rakentaa uudestaan. Siksi:

* Litterointi, joka ei tunnistanut yhtään sanaa, **ei kirjoita istuntoa**.
  Tyhjä `<Transcription>` on kelvollinen ja saisi vaimennuksen vaientamaan
  koko raidan.
* Tason tarkistus päällä ja yhdenkään raidan ääntä ei löydy levyltä on
  **virhe**. Tulos olisi sama kuin ilman tarkistusta, ja käyttöliittymä
  lupasi muuta.
* Raita, jolla ei ole litterointia lainkaan, **jätetään koskematta**.
  Colab-muistikirja teki niin (`if not intervals: return`), ja se on oikein:
  tiedon puute ei ole päätös vaientaa. Musiikkiraita on tästä se tapaus jota
  ei huomaa ennen kuin se puuttuu.

## Vuoto ratkaistaan raitojen välillä, ei raidan sisällä

Kynnys on raidan sisäinen kysymys ja vuoto on raitojen välinen. Siksi
`threshold` ei riitä: hiljaisessa studiossa hyvillä mikeillä vuoto on
reilusti kynnyksen yläpuolella. Autoraffkatissa mitattuna molemmat mikit
ylittävät kynnyksen **41 % ajasta**, mutta vuoto on mediaanissa **12,8 dB**
hiljempaa kuin sama puhe omalla mikillä.

`dominant_words` mittaa siksi **jokaisen** raidan tason **jokaisen** sanan
kohdalta — myös toisten raitojen sanojen — ja sana jää sille raidalle jolla
se on kovimmillaan sekä niille jotka ovat `dominance`-kaistan sisällä.
Litteroinneista ei voi verrata: sama puhe tuottaa eri merkkijonon eri
mikeillä, joten tekstissä ei ole mitään mitä täsmäyttää.

Kaista on 6 dB eikä nolla, koska nolla leikkaisi päällekkäisen puheen.
Mitatusta 12,8 dB:stä jää silti ~6,8 dB pelivaraa vuotoa vastaan.

**`-inf` on kaksi eri asiaa, ja niitä ei saa laskea yhteen.** Mittaamaton
(tiedosto puuttuu, ei aukea, raidalla ei ole aluetta tällä hetkellä) on eri
kuin mitattu digitaalinen hiljaisuus. Yhteen laskettuna raita jonka tiedosto
ei aukea häviää joka vertailun ja vaikenee kokonaan — sama vika jota vastaan
`speech_intervals` jo suojaa puuttuvalla tiedostolla. Siksi `measured` on oma
taulukkonsa tason rinnalla. Tämä ei ole teoreettinen: se syntyi ja jäi kiinni
vasta testiin, ei lukemalla.

Muisti ei muutu: raidat mitataan yksi kerrallaan ja ikkunat ovat sekunnin
murto-osia, joten levyltä on auki edelleen enintään kaksi tiedostoa.

Sama päätös samasta mittauksesta on `speechmix.masks.duck_masks`. Se antaa
liu'utettavan vahvistuskäyrän ruudukolla; tämä antaa sanakohtaisen kyllä/ei,
koska vaimennus tarvitsee tiedon siitä mikä alue jää auki. Jos ero katoaa,
tämä kuuluu `speechmix`iin — se ei kuulu sinne ennen sitä.

## Kaksi säädintä sulkee taukoja, ja suurempi ratkaisee

`audible_zones` sulkee tauon jos se on lyhyempi kuin `gap` **tai** lyhyempi
kuin kaksi kertaa `tail`. Häntä puoli sekuntia sulkee sekunnin tauon vaikka
«lyhin tauko» olisi 0,4. Järjestys — sulje, sitten pehmennä — on tämä eikä
toisin päin: hännän lisääminen ensin sulkisi tauot pituuteen
`gap + 2 × tail` asti, eli säätimet laskisivat yhteen.

## Muuta

* **Lähdettä ei kirjoiteta koskaan yli.** Vienti on uusi tiedosto, ja jos
  sellainen on jo, siitä tulee `… v2`.
* **Alueen lapsielementit eivät seuraa pilkkomisessa.** Sama häivytys sadassa
  palassa on eri asia kuin yksi häivytys alueen alussa. Siitä kerrotaan
  lokissa; muistikirja pudotti ne hiljaa.
* **Yksi työ kerrallaan.** Kaksi litterointia jakaisi saman näytönohjaimen ja
  valmistuisi molemmat myöhemmin kuin peräkkäin ajettuina.
* **Tason mittauksen välimuisti pitää int16:ta.** Tunnin jakso on 16 kHz:llä
  115 MB int16:na ja 230 MB float32:na, ja niitä on istunnossa useita.
  Katto on kaksi tiedostoa: ajo etenee raita kerrallaan.
* **Mallien painoja ei paketoida.** `large-v3-turbo` on gigatavun luokkaa;
  se ladataan ensimmäisellä ajolla ja jää käyttäjän välimuistiin.

## Istunnon kuuleminen: mikä on mitattu ja mikä arvattu

`nhsx/mix.py` sijoittaa alueet ohjelma-aikajanalle tasoineen, häivytyksineen
ja panorointeineen; `nhsx/render.py` summaa ne WAViksi. Yhdessä ne ovat se,
mikä tekee istunnosta kuunneltavan **ilman Hindenburgia** — tiedosto on XML
ja äänipooli on WAVeja levyllä, eikä muuta tarvita.

**Mitattua on geometria.** `Start`, `Length`, `Offset` ja `Muted` ovat
attribuutteja joita tämä repositorio on lukenut ja kirjoittanut alusta asti.

**Ja nyt mitattua on myös taso, panorointi ja häivytys.** `pans and stuff`
-istunto ja siitä Hindenburgin itsensä renderöimä tiedosto vastasivat
kaikkiin kolmeen; ks. `tests/test_measured_session.py`, jossa luvut ovat.

Se, mitä mittaus kertoi, on karua luettavaa arvauksista:

* `<Fade In= Out=>` oli **keksitty**. Oikeat nimet ovat `Start`, `Length`
  ja `Gain`, joten jokaisen istunnon jokainen häivytys luettiin nollana.
* Panorointi oli vakiotehoinen ja **väärin päin**. Oikea laki on
  lineaarinen ja vakiosummainen, ja positiivinen on vasen.
* `ClipGain` ohitettiin kokonaan, eli mitatun istunnon kolmas alue
  renderöityi 22,2 dB liian kovaa.

Kaksi näistä kolmesta ei ole väärä luku vaan väärä **muoto**: häivytys ei
mene hiljaisuuteen vaan tasolle, ja `fade_in`/`fade_out` ei osaa esittää
tasannetta millään lukuparilla.

Siksi kaksi asiaa. `KNOWN_REGION_ATTRS` on **käsin kirjoitettu** lista, sama
vartija kuin litteroinnin tunnisteella: uusi nimi ei livahda tunnettujen
joukkoon ilman että joku päätti niin. Ja tuntematon attribuutti
**kerrotaan** — `Mix.unknown`, ja `nhsx-render` varoittaa siitä — koska
miksaus joka ohitti faderin on kelvollinen WAV väärällä tasolla, eli
täsmälleen tämän talon hiljainen vika.

`nhsx/prospect.py` on se joka vaihtaa arvauksen mittaukseksi. Aja
`nhsx-render jakso.nhsx --inspect` istuntoon, jossa taso, panorointi ja
häivytys **on asetettu**, ja se kertoo nimet — ja esimerkkiarvot, koska
«Gain» ei kerro onko se desibeliä vai kerroin. Sama kuvio kuin
`verify.py`:llä: formaattia ei arvata, siitä kysytään tiedostolta.

Mitä tässä ei ole eikä pidä olla: taajuuskorjaus, kompressointi ja
Hindenburgin oma tasonsäätö. Esikatselu on geometria, taso, häivytys ja
panorointi — ja siksi se voi olla nopea. Se ei siis kuulosta Hindenburgin
toistolta silloin kun istunnossa on käytetty ääniprofiileja.

### Lohkoraja on renderöinnin vaarallinen kohta

Ohjelmaa ei pidetä muistissa: tunnin jakso on 48 kHz:llä stereona
liukulukuina 1,4 GB, ja lähteitä on lisäksi yksi per raita. `render.blocks`
antaa ohjelman 30 sekunnin paloina ja `to_wav` kirjoittaa jokaisen heti.
Lähteestä puretaan vain se kohta jota tarvitaan (`-ss` **ennen** `-i`:tä,
muuten tunnin nauhan lopusta otettu kolmen sekunnin leike on tunnin työ).

Jokainen lohkon raja on paikka, jossa leike voi katketa, häivytys alkaa
alusta tai lähteestä luetaan väärä kohta. Mikään niistä ei kaada mitään:
tulos on kelvollinen WAV, jossa on naksahdus puolen minuutin välein. Siksi
verhokäyrä lasketaan **koko leikkeelle** ja viipaloidaan lohkoon, kaikki
paikat lasketaan näyteindekseinä eikä sekunteina, ja
`test_the_block_size_does_not_change_the_result` ajaa saman miksauksen
kahdella lohkokoolla. Se on se yksi testi joka näkee ne kaikki kerralla.

### Panorointi on lineaarinen ja vakiosummainen, ja positiivinen on vasen

Mitattu, ei valittu. Renderöidystä istunnosta sovitettu suhde `R = k·L`:

    Pan="0.625"   ennuste 0,23077   mitattu 0,23027
    Pan="-0.55"   ennuste 3,44444   mitattu 3,44347

eli `R/L = (1-p)/(1+p)`. Normalisointi on vakiosumma (`vasen + oikea = 1`)
eikä vakioteho: kaksi eri tavoin panoroitua raitaa ovat summattuna 0,24 dB:n
päässä toisistaan, kun vakiotehoinen laki antaisi eron 1,5 dB.

Aiempi valinta oli vakiotehoinen laki, ja perustelu oli hyvä — lineaarisella
lailla keskellä oleva raita on summassa 3 dB kovempaa kuin laidoille ajettu.
Se on vain perustelu sille miten asian *pitäisi* olla, ja tämä lukee
Hindenburgin istuntoja eikä kirjoita omaansa. **Ja laki oli väärin päin**,
mikä on kelvollinen tiedosto jossa puhujat ovat vaihtaneet puolta: mikään ei
kaadu, eikä sitä huomaa muuten kuin kuuntelemalla.

Asteikon ulkopuolinen arvo **rajataan** eikä kierretä: kierrettynä se
antaisi negatiivisen vahvistuksen eli vaihekäännöksen.

### Häivytys on luiska tasolle, ei häivytys hiljaisuuteen

`<Fade Start= Length= Gain=>` kulkee edellisestä tasosta arvoon `Gain` ja
**jää sinne**. Mitattu alue laskee 2,5 sekunnissa −11,2 dB:hen ja pysyy
siellä 26 sekuntia; renderissä sen runko on 12,02 dB vaimeampi kuin
vaimentamaton alue. Ilman `Gain`ia luiska palaa ykköseen, ja juuri se on
kuvaruudulla näkyvä käyrä joka laskee, kulkee tasaisena ja nousee takaisin.

Siksi malli on `Ramp`-lista eikä `fade_in`/`fade_out`: lukupari ei esitä
tasannetta lainkaan. Leikettä pidempi luiska **katkeaa** alueen loppuun eikä
kutistu — pilkottu pala on lyhyempi kuin alue, ei hitaampi. Luiskat
seuraavat toisiaan eivätkä summaudu, joten käyrä ei voi painua nollan ali.

Luiskan **muotoa** ei vieläkään tiedetä: puheen dynamiikka peittää 2,5
sekunnin rampin, eikä sitä voi mitata muusta kuin tasaisesta signaalista.
Lineaarinen on niistä se joka ei väitä mitään, ja kun muoto mitataan, se
vaihdetaan yhdessä funktiossa (`envelope`).

### `nhsx/`:llä on toinen toteutus, ja se on toista kieltä

`viewer/` on NHSX Viewer: `.nhsx` sisään, aikajana ja ääni ulos — sovelluksen
ikkunassa ja Finderin välilyönnillä samasta näkymästä. Se **jäsentää istunnon uudestaan Swiftillä** eikä
kutsu tätä koodia. Se ei ole valinta: macOS-laajennus on hiekkalaatikossa
eikä voi käynnistää `nhsx-render`iä.

Kaksi toteutusta samasta formaatista on täsmälleen se ajautuminen jota
vastaan tämä repositorio on — mutta tätä ei voi ratkaista jakamalla koodi.
Mitä voi jakaa on **vastaus**: `viewer/Conformance/session.nhsx` on
istunto, joka erottaa jokaisen kohdan jossa kaksi jäsennintä voi mennä eri
mieltä huomaamatta, ja `plan.json` on sen kirjattu vastaus. Molemmat
toteutukset testaavat itseään sitä vasten
(`tests/test_conformance.py` täällä, `Tests/NhsxKitTests/` siellä).

**Kun muutat `nhsx/read.py`:tä tai `nhsx/mix.py`:tä, muutat sopimusta.**
Jos vastaus muuttuu, se luodaan uudestaan tahallaan ja diffi luetaan —
muuttunut luku on joko korjaus tai regressio — ja Swift-puoli muutetaan
samassa hengessä. Muuten esikatselu näyttää eri jakson kuin `nhsx-render`
renderöi, eikä kumpikaan kaadu.

`viewer/` **ei ole työtilan jäsen** eikä voi olla: `apps/*` vaatii
`pyproject.toml`in, ja Swift-hakemisto siellä kaataa `uv sync`in koko
työtilalta. Siksi se on juuressa ja sillä on oma työnkulkunsa.

### Purkaja on parametri — ja siksi tarvitaan myös päästä päähän -testi

`render.blocks` ottaa purkajan argumenttina. Ilman sitä jokainen summauksen
testi tarvitsisi ffmpegin, ja ffmpegiä tarvitseva testi on vihreä siellä
missä ffmpegiä ei ole — eli sama kuin ettei sitä olisi. Renderöinnin viat
ovat summauksessa, eivät purussa.

**Mutta silloin oikea polku jää ajamatta, ja siellä oli vika.** 24-bittinen
näyte pakattiin int32:n kolmesta **ylimmästä** tavusta kolmen alimman
sijaan, eli jokainen ohjelma kirjoitettiin **48 dB** (256×) liian hiljaa.
Mikään ei kaatunut: WAV oli kelvollinen, kesto oikea, kanavat oikein — ja
`Report.peak` kertoi oikean huipun, koska se mitataan liukuluvuista **ennen**
pakkausta. Ohjelma sanoi «huippu −6,7 dBFS» tiedostosta, jonka huippu oli
−54,7. Yksikään yksikkötesti ei lukenut 24-bittisiä tavuja takaisin, vain
16-bittiset.

Siksi `tests/test_render_endtoend.py`: oikeat lähteet, oikea ffmpeg, oikea
WAV levylle ja tavut luettuna takaisin käsin. Lähteet tehdään niin, että
**taajuus kertoo sekunnin** (sekunti `s` on siniä taajuudella `400 + 200·s`),
jolloin renderistä näkee suoraan mistä kohtaa lähdettä kukin ohjelmasekunti
tuli. Tiedosto-offsetin voi laskea väärin niin, että tulos on joka muulla
tavalla kelvollinen.

Ohittunut testi on vihreä testi, joten CI tarkistaa erikseen ettei se
ohittunut — sama kuvio kuin käyttöliittymän savutestillä.

`-ss` **ennen** `-i`:tä ei ole tarkistettavissa tuloksesta: väärällä puolella
se antaa täsmälleen saman äänen, se vain puretaan alusta asti ja heitetään
pois. Kellosta eron näkisi vasta tiedostolla joka on liian iso testattavaksi,
joten komentorivi on oma funktionsa (`decode_command`) ja järjestys
väitetään siitä.

## Ääniketju tulee joskus, ei vielä

`nhsx/pipeline.py` on sauma autoraffkatin mitatulle puheenkäsittelyketjulle:
raita, jolla on puhuja, monolippu, bittisyvyys ja lista jaksoja
ohjelma-aikajanalla. Siinä ei ole yhtään käsittelyä eikä sitä pidä lisätä
tänne — ketju kuuluu jaettuun pakettiin, jotta se ei ehdi ajautua erilleen
kolmessa projektissa. Tämän tiedoston tehtävä on, ettei ketjun tuominen ole
lukijan uudelleenkirjoittamista.

### `speechmix` on tuotu, mutta vain sääntö — lue tämä ennen kuin kirjoitat DSP:tä

Riippuvuus on `pyproject.toml`issa työtilasta, ja tuotuna on **päätössääntö**:
`grid.noise_floor`, `grid.smooth`, `grid.FLOOR_MARGIN_DB` ja
`masks.DUCK_DOMINANCE_DB`. Tasojen mittaaminen jää tänne, ja se on tarkoitus
eikä laiskuutta — `lane`in docstring jakaa työn juuri noin: sääntö on yksi,
tapa saada tasot on isännän oma.

**Miksi `speech_grid` ei ole suora korvaaja.** Se ottaa kaikki raidat yhtä
aikaa liukulukutaulukkoina. Tämän sovelluksen istunto on viisi raitaa kertaa
75 minuuttia: 16 kHz:n int16:na 575 MB, liukulukuina yli kaksi kertaa se, ja
katto on kaksi tiedostoa kerrallaan. `noise_floor_of` mittaa käyrän raita
kerrallaan ja pitää vain käyrän, joka on megatavun luokkaa.

**Mitä kiinteän kynnyksen tilalle tuli.** `Settings.sensitivity` on
desibeleitä raidan oman pohjakohinan yli (oletus `grid.FLOOR_MARGIN_DB` =
12), ei absoluuttinen `-35 dBFS`. Ero on mitattu tämän repositorion omalla
jaksolla (`vst s13e01`, 4 raitaa, 9 412 sanaa), ja se on iso:

    raita   pohja      vanha −35 dBFS vaiensi   uusi pohja+12 dB vaiensi
    Olli    −60,9 dB   1 482 / 5 257  (28,2 %)  136 / 5 257  (2,6 %)
    Karde   −72,4 dB     332 / 1 833  (18,1 %)  139 / 1 833  (7,6 %)
    Panu    −93,2 dB     901 / 2 322  (38,8 %)   82 / 2 322  (3,5 %)

Kiinteä kynnys siis vaiensi joka kolmannen sanan raidalta jonka mikki on
58 dB sen oletuksen alapuolella. Se on juuri se virhe joka on pahempi kuin
päinvastainen: liikaa vaimennetusta jaksosta puuttuu puhetta, ja sen huomaa
vasta valmiista jaksosta.

Loput, kun ketju tuodaan — **käytä näitä äläkä kirjoita uusia**:

| täällä nyt | `speechmix` | huomio |
|---|---|---|
| `silence/detect.py` `dominant_words` | `grid.lane`, `SpeechGrid.speaking` | sama päätös; vaatii käyrät, ei stemejä |
| `Settings.sensitivity` | `grid.FLOOR_MARGIN_DB` | **tuotu** |
| `Settings.dominance` | `masks.DUCK_DOMINANCE_DB` | **tuotu** |
| «vain minä äänessä» (ei ole vielä) | `SpeechGrid.only_frames`, `masks.solo_masks` | vuodon vähennys tarvitsee juuri nämä |
| `silence/apply.py` `merge`, `audible_zones` | `masks.open_windows`, `drop_short`, `envelopes.closed_ranges` | jaksot vs. ruudukko, sama idea |
| `audio.py` `dbfs` | `dsp.moving_rms`, `dsp.lin_to_db` | sama mitta, eri hankintatapa |
| ristivuodon poisto (ei ole) | `debleed.path`, `debleed.remove` | mitattu, tarkistaa tuloksensa |

Mikä **jää** tänne, koska se on istuntoformaattia eikä ketjua: `nhsx/`
kokonaan, `silence/apply.py`:n `split_track` ja `has_region_children`,
`audio.py`:n `decode_pcm` (paketoitu ffmpeg-binääri, ei PATH) ja
`silence/presets.py`:n käyttöliittymäsanasto.

Seuraava askel on `dominant_words`: se vertaa raitoja sanan kohdalla, ja sama
vertailu on `lane`issa ruudukon päällä. Se vaatii käyrät kaikilta raidoilta
yhtä aikaa — käyrät mahtuvat muistiin vaikka raidat eivät.
