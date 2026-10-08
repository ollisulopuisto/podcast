# colab-transcribe

Litterointi ja Auto-Silence Colabin näytönohjaimella. Paikallinen ajuri
ketjun ympärillä joka ajaa pilvessä — tämä kone lähettää, näytönohjain
tekee. (In English: [README.md](README.md).)

## Mitä se tekee

Osoita kansioon jossa on Hindenburgin `.nhsx`-istuntoja ja niiden äänet.
Se käynnistää Colab-istunnon, lähettää kaiken, litteroi siellä Whisperillä
(faster-whisper T4:llä, L4:llä tai A100:lla), kirjoittaa sanat istuntoon,
vaimentaa jokaisen kohdan jossa kukaan ei puhu (Auto-Silence) ja lataa
tulokset takaisin: `<jakso> litteroitu.nhsx` ja `<jakso>_processed.nhsx`.
Pelkkä litterointi ilman Auto-Silencea: `--transcribe-only` (tai TUI:ssa
Auto-Silence pois päältä), jolloin tulos on vain `<jakso> litteroitu.nhsx`.

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
colab-transcribe --input ~/jakso/ --dry-run     # tulosta suunnitelma, älä aja
colab-transcribe --input ~/jakso/ --gpu A100 --rms --thr -40
colab-transcribe --input ~/jakso/ --no-drive    # käytä vanhaa hidasta suoraa Colab-latausta
colab-transcribe --session-status               # tarkista aktiivisen Colab-istunnon tila
colab-transcribe --stop                         # sulje aktiivinen Colab-istunto
colab-transcribe --input ~/jakso/ --reset-session # pakota vanhan istunnon sulkeminen ja uusi VM
colab-transcribe --input ~/jakso/ --keep-session  # jätä Colab-istunto käyntiin ajon jälkeen
```

Tiedostot siirretään oletuksena Google Driven kautta (`--transfer drive`), jolloin
paketti ladataan Google Driveen resumable uploadina ja Colab-kone purkaa sen
sisäverkon nopeudella sekunneissa.
Esiasetukset ovat Colabissa ajettavan skriptin: `remote` (häntä 1,0 s,
tauko 1,0 s) ja `intra-mic` (RMS-tarkistus päällä, häntä 0,4 s, tauko
0,4 s). `--thr`, `--tail`, `--gap`, `--rms` ja `--prompt` korvaavat
esiasetuksen lukua.

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
