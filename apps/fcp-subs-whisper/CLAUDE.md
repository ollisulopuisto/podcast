# fcp-subs-whisper

Tekstitys- ja puheentunnistustyökalu Final Cut Prohon: video tai ääni sisään,
SRT ja SSA -tekstitykset ulos.

## Moottorit

Sovellus tukee kolmea puheentunnistusmoottoria:
* **`mlx`**: Apple Siliconin Metal- ja Neural Engine -kiihdytetty Whisper (`mlx-whisper`).
  Suositeltu ja oletus macOS:llä.
* **`faster`**: CPU-optimoitu `faster-whisper` (CTranslate2).
* **`wyoming`**: Wyoming-protokollaa puhuva etäpalvelin (TCP-asiakas).

## Puhujantunnistus (Diarization)

Valitsin `--diarize` käyttää Hugging Facen `pyannote/speaker-diarization-3.1`
-putkea (`pyannote.audio`), joka vaatii HF-tunnisteen (`HF_TOKEN` tai `--hf-token`).
Puhujaosuudet kohdistetaan Whisperin aikaleimoihin ja käyttäjältä kysytään
tunnistettujen puhujien nimet.

## Formaattierot: SSA vs SRT

* **SSA (SubStation Alpha)**: Aikaleimamuoto `H:MM:SS.cc` (sadasosasekunnit).
  Sisältää tyylittelyn ja `[V4+ Styles]` -määrityksen sekä puhujatiedon erillisenä sarakkeena (`Default,Alice`).
* **SRT (SubRip)**: Aikaleimamuoto `HH:MM:SS,mmm` (millisekunnit). Puhujan nimi
  kirjoitetaan tekstirivin alkuun muodossa `[Alice] Teksti`. Valmis tuotavaksi suoraan
  Final Cut Prohon (`File > Import > Captions...`).

## Versio

CalVer, muotoa `YYYY.M.D.N`. Päivitetään komennolla:
```
uv run python scripts/bump_version.py fcp-subs-whisper
```
Versio elää tiedostoissa `apps/fcp-subs-whisper/pyproject.toml` ja
`apps/fcp-subs-whisper/src/fcp_subs_whisper/__init__.py`.
