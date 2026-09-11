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

## Ajaminen

Repositorion juuresta, kun `uv sync --all-packages` on ajettu:

```
uv run colab-transcribe              # TUI (interaktiivinen kansionvalinta + opastus)
uv run colab-transcribe --check      # tarkista apuohjelmat ja tunnistetiedot
```

Täysin skriptattuna, ilman käyttöliittymää:

```
uv run colab-transcribe --input ~/jakso/ --output ~/valmis/ --preset intra-mic
uv run colab-transcribe --input ~/jakso/ --dry-run     # tulosta suunnitelma, älä aja
uv run colab-transcribe --input ~/jakso/ --gpu A100 --rms --thr -40
uv run colab-transcribe --input ~/jakso/ --no-drive    # käytä vanhaa hidasta suoraa Colab-latausta
```

Tiedostot siirretään oletuksena Google Driven kautta (`--transfer drive`), jolloin
paketti ladataan Google Driveen resumable uploadina ja Colab-kone purkaa sen
sisäverkon nopeudella sekunneissa.
Esiasetukset ovat Colabissa ajettavan skriptin: `remote` (häntä 1,0 s,
tauko 1,0 s) ja `intra-mic` (RMS-tarkistus päällä, häntä 0,4 s, tauko
0,4 s). `--thr`, `--tail`, `--gap`, `--rms` ja `--prompt` korvaavat
esiasetuksen lukua.

## Vaatimukset

* `colab`-komentorivityökalu (`uv tool install google-colab-cli`) ja Colab-tili jolla on GPU-käyttö.
* Google Cloud ADC -tunnistetiedot (`gcloud auth application-default login`) tai `GOOGLE_APPLICATION_CREDENTIALS`.
* `colab-transcribe` opastaa käyttäjää (onboarding) automaattisesti TUI:ssa tai `--check`-valitsimella, jos työkaluja tai tunnisteita puuttuu.
* Paikallisesti ei muuta: raskas työ ajaa pilvessä, ja ajettava skripti
  kulkee tämän paketin mukana.

## Ketjusta

Colabissa ajettava skripti (`src/colabtranscribe/colab/pipeline.py`) on
litterointi- ja Auto-Silence-ketjusta erillinen kopio. Se ajaa Colabissa
ja asentaa riippuvuutensa itse, joten se ei voi tuoda työtilan jaettua
`speechmix`-pakettia. Mitä se tarkoittaa silloin kun jaettu ketju muuttuu,
lukee `CLAUDE.md`:ssä.
