# colab-transcribe

Litterointi ja Auto-Silence Colabin näytönohjaimella. Paikallinen ajuri
ketjun ympärillä joka ajaa pilvessä — tämä kone lähettää, näytönohjain
tekee. (In English: [README.md](README.md).)

## Mitä se tekee

Osoita kansioon jossa on Hindenburgin `.nhsx`-istuntoja ja niiden äänet.
Se käynnistää Colab-istunnon, lähettää kaiken, litteroi siellä oletuksena Parakeet Ultralla
(Photon NVIDIA-näytönohjaimella), kirjoittaa sanat istuntoon,
vaimentaa jokaisen kohdan jossa kukaan ei puhu (Auto-Silence) ja lataa
tulokset takaisin: `<jakso> litteroitu.nhsx` ja `<jakso>_processed.nhsx`.
Pelkkä litterointi ilman Auto-Silencea: `--transcribe-only` (tai TUI:ssa
Auto-Silence pois päältä), jolloin tulos on vain `<jakso> litteroitu.nhsx`.
Valmiin istunnon luettava käsikirjoitus tulee viereen (`<jakso>_processed.md`,
tai `<jakso> litteroitu.md` kun `--transcribe-only`): yksi kappale per
puheenvuoro, puhujana raidan nimi.

## Ajaminen

Nopein tapa Macilla, jossa on [Homebrew](https://brew.sh): liitä tämä Päätteeseen. Se asentaa puuttuvat `uv`:n (ja muiden työkalujen tarvitseman `ffmpeg`in), hoitaa Google-kirjautumisen ensimmäisellä kerralla ja avaa sovelluksen:

```
curl -fsSL https://raw.githubusercontent.com/ollisulopuisto/podcast/main/run.sh | sh
```

Tai vaihe vaiheelta:

Macilla, jossa on [Homebrew](https://brew.sh), asennettavaksi jää vain uv:

```
brew install uv
```

Sen jälkeen ilman muita asennuksia (`colab`-työkalu tulee mukana):

```
uvx --from "git+https://github.com/ollisulopuisto/podcast#subdirectory=colab-transcribe" colab-transcribe --login   # vain ensimmäisellä kerralla
uvx --from "git+https://github.com/ollisulopuisto/podcast#subdirectory=colab-transcribe" colab-transcribe           # TUI
```

`--login` kirjaa sinut Googleen `colab`-työkalun kautta: se tulostaa osoitteen, jonka avaat selaimessa, ja selaimen antama koodi liitetään takaisin terminaaliin. Sama kirjautuminen kattaa Colabin ja Google Drive -siirron, joten `gcloud`ia ei tarvita. Tarvitset Google-tilin, jolla on Colab; ilmaisversiossa on T4-näytönohjain.

Alla `colab-transcribe` tarkoittaa tuota `uvx --from … colab-transcribe` -komentoa, tai repositoriossa `uv run colab-transcribe` -komentoa, kun `uv sync --all-packages` on ajettu:

```
colab-transcribe              # TUI (interaktiivinen kansionvalinta + opastus)
colab-transcribe --check      # tarkista apuohjelmat ja tunnistetiedot
```

Täysin skriptattuna, ilman käyttöliittymää:

```
colab-transcribe --input ~/jakso/ --output ~/valmis/ --preset intra-mic
colab-transcribe --input ~/jakso/ --transcribe-only   # vain litterointi, ei Auto-Silencea
colab-transcribe --input ~/jakso/yksi.nhsx      # yksi istunto kansiosta jossa niitä on useita
colab-transcribe --input ~/jakso/ --inline-remarks # käsikirjoitus: lyhyet huomautukset "(Vieras: niin)" kappaleen sisään
colab-transcribe --input ~/jakso/ --no-bleed-filter # kirjoita istuntoon myös toisen mikin vuoto
colab-transcribe --input ~/jakso/ --dry-run     # tulosta suunnitelma, älä aja
colab-transcribe --input ~/jakso/ --gpu A100 --rms --thr -40
colab-transcribe --input ~/jakso/ --no-drive    # käytä vanhaa hidasta suoraa Colab-latausta
colab-transcribe --session-status               # tarkista aktiivisen Colab-istunnon tila
colab-transcribe --stop                         # sulje aktiivinen Colab-istunto
colab-transcribe --input ~/jakso/ --reset-session # pakota vanhan istunnon sulkeminen ja uusi VM
colab-transcribe --input ~/jakso/ --keep-session  # jätä Colab-istunto käyntiin ajon jälkeen
```

Tiedostot ladataan oletuksena suoraan Colabiin (`--transfer direct`; isot tiedostot
lähtevät paloina). `--transfer drive` kulkee Google Driven kautta: se on nopeampi,
mutta vaatii että Drive API on käytettävissä tilillä. Ilman sitä Google vastaa
403:lla ja ajo jatkaa itse suoralla latauksella. Suorassa siirrossa isot WAVit pakataan
ensin FLACiksi (häviötön, puretaan Colabissa); `--no-compress` kytkee sen pois. Ladatut tiedostot jäävät Colabin välimuistiin sisällön tarkistussumman mukaan, joten saman istunnon uusinta lähettää vain puuttuvat (välimuisti katoaa kun istunto suljetaan; `--keep-session` pitää sen).

Kahden mikin äänityksessä kumpikin mikki kuulee molemmat puhujat. Istuntoon kirjoitetaan vain sanat, jotka ovat omalla raidalla selvästi kovempia kuin toisella (raja mitataan aineistosta, ja se näkyy lokissa rivillä `Vuodon raja`); käsikirjoitus lukee suodatetun istunnon.
Esiasetukset ovat Colabissa ajettavan skriptin: `remote` (häntä 1,0 s,
tauko 1,0 s) ja `intra-mic` (RMS-tarkistus päällä, häntä 0,4 s, tauko
0,4 s). `--thr`, `--tail`, `--gap`, `--rms` ja `--prompt` korvaavat
esiasetuksen lukua.

`learned` opettaa vaimennuskynnyksen omasta vaimennuksestasi. Avaa istunto
ennen ajoa Hindenburgissa, vaimenna alun minuutin tai parin kohdat joissa
kukaan ei puhu (litterointia ei tarvita siihen), tallenna ja aja
`--preset learned`. Raidan kynnys on sen vaimennettujen kohtien taso (90.
persentiili + 1 dB, joten yskäisy ei aseta sitä), korotettuna jos toisen
raidan puhe vuotaa vaimennettuun mikkiin. Käsin vaimennetut alueet pysyvät
vaimennettuina. Raita jolla on alle 3 s vaimennettua ääntä, tai jonka
vaimennettu taso on yhtä kova kuin sen puhe, ajetaan `--thr`:llä ja lokissa
lukee miksi; istunto jossa ei ole yhtään vaimennettua aluetta pysähtyy
kirjoittamatta mitään. Luvut ovat makuasioita eikä niitä ole mitattu, ja
laskenta on `silencelearn`-kirjasto, joka ladataan Colabiin skriptin viereen.

### Pelkkä ääni: sanat JSONina (`--audio`, `--json`)

Kutsujalle, joka haluaa vain sanat (kuulas-editori kutsuu näin):

```bash
colab-transcribe --audio "Olli 1.wav" --audio Panu.mp3 --json sanat/ --progress
# Whisper Photon Ultran sijaan
colab-transcribe --audio "Olli 1.wav" --json sanat/ --model whisper
```

Kaikki `--audio`-tiedostot menevät samaan Colab-istuntoon ja `sanat/<nimi>.words.json` tulee
takaisin: `{"version":1,"timing":"parakeet-ultra","language":"fi","rejected":0,"words":[{"w","s","e"}]}`,
sekunteja kyseisen tiedoston alusta, aikajärjestyksessä ja `s < e` (päällekkäisyys lyhentää
aiempaa sanaa). Ei `.nhsx`:ää eikä Auto-Silencea. Siirto on aina suora: ääni menee Googlen
Colab-koneelle eikä Driven kautta. Parakeet Ultra on oletus; `--model whisper` valitsee
Whisper Photon -moottorin. Molemmat tunnistavat kielen itse ja palauttavat sanakohtaiset ajat.
`--prompt` ei vaikuta kumpaankaan Photon-moottoriin. `--progress` tulostaa rivit `PROGRESS <0-100> <viesti>`, joiden luku ei
laske. Sanaton tiedosto tai puuttuva tulos antaa poistumiskoodin 1 ja syyn stderriin; samannimiset
vanhat `*.words.json` poistetaan ennen ajoa, ettei vanha kelpaa uudeksi. SIGTERM ja Ctrl+C
sulkevat Colab-istunnon (ellei `--keep-session`) ja palauttavat 130. Sanojen ajat tulevat
valitun Photon-moottorin sanakohtaisista aikaleimoista (`timing: "parakeet-ultra"` tai `"whisper"`).

Paikallinen ajo toimii myös ilman Colab-istuntoa: `--backend orukeet` käyttää
Orukeetin natiivia Metal-runtimea Apple Siliconilla. Asenna paketti ja malli
seuraavilla komennoilla:

```bash
uv pip install 'https://github.com/Oruk-AI/orukeet/releases/download/v0.1.1/orukeet-0.1.1-py3-none-any.whl' torch==2.8.0 torchaudio==2.8.0
orukeet install --device auto --cache ~/.cache/orukeet --output ~/.cache/orukeet/installation.json
```

Orukeet palauttaa lauseajat, joten jaettu CTC-kohdistin
asettaa sanakohtaiset ajat (`timing: "orukeet-ctc"`). Tähän tarvitaan Torch,
torchaudio ja ffmpeg.

Colabiin asennetaan Photon, ja malli ladataan ensimmäisellä ajolla. T4-savukoe latasi 1,26 Gt
mallitiedostoja; siinä käytettiin synteettistä suomenkielistä puhetta, joten se ei mittaa podcastien
tarkkuutta. Photon pilkkoo pitkän äänen taukojen kohdalta ja palauttaa ajat alkuperäisen äänitteen
kellossa. Jälkikäsittely ei poista täytesanoja eikä toistoja. Kumpikaan malli ei käytä
`--prompt`-sanastoa.

`--align` (`--audio`:n kanssa) korjaa sanojen alut Colab-koneella pakotetulla kohdistimella
(`packages/wordalign`, torchaudion `MMS_FA`) ja merkitsee tiedoston `"timing": "ctc-v1"`; `rejected` on
niiden sanojen määrä, joita ei saatu sijoitettua (ne jäävät ASR:n aikaan). Se asentaa torch 2.8:n
koneella omaan kansioonsa ja lataa noin 1,2 Gt painoja, ja tarkistaa sen **ennen** litterointia, joten
rikkinäinen kohdistin pysäyttää ajon kuluttamatta GPU-aikaa. Jos yksikään sana ei kohdistu, ajo
epäonnistuu eikä korjatuksi merkittyä tiedostoa kirjoiteta. **Ei vielä ajettu oikealla Colabilla:**
asennuksen koko ja kesto sekä se, sopiiko kohdistin yhteen litteroinnin CUDA-kirjastojen kanssa, on
mittaamatta. `docs/KUULAS-TIMECODES.md` sisältää aiemman Whisper-ajon mittauksen; sitä ei voi
siirtää Parakeet Ultralle. Parakeet Ultran podcast-tarkkuutta ei ole tässä repossa mitattu.

## Vaatimukset

* [uv](https://docs.astral.sh/uv/) (`brew install uv`). `colab`-komentorivityökalu on riippuvuus ja tulee `uvx`:n mukana, kiinnitettynä versioon jossa on Googlen oma `jupyter-kernel-client`.
* Google-tili, jolla on Colab, kirjautuneena kerran komennolla `colab-transcribe --login`. Vaihtoehtoisesti Google Cloud ADC -tunnisteet (`gcloud auth application-default login`) tai `GOOGLE_APPLICATION_CREDENTIALS`.
* `colab-transcribe` opastaa automaattisesti TUI:ssa tai `--check`-valitsimella, jos jotain puuttuu.
* Siinä kaikki paikallisesti. ffmpegiä ei tarvita: raskas työ tehdään pilvessä, ja ketjun skripti tulee tämän paketin mukana.

## Ketjusta

Colabissa ajettava skripti (`src/colabtranscribe/colab/pipeline.py`) on
litterointi- ja Auto-Silence-ketjusta erillinen kopio. Se ajaa Colabissa
ja asentaa riippuvuutensa itse, joten se ei voi tuoda työtilan jaettua
`speechmix`-pakettia. Mitä se tarkoittaa silloin kun jaettu ketju muuttuu,
lukee `CLAUDE.md`:ssä.
