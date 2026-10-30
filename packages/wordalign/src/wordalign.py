"""Sanojen alkujen pakotettu kohdistus ääneen: yksi tiedosto, jota kaksi käyttää.

Whisperin sanaleimat ovat huomiomatriisin arvio, ja käsin merkittyjä alkuja
vasten mitattuna (15 sanaa, yksi puhuja, jakson ``vst s13e04`` raaka mikki)
ne ovat lähes aina liian aikaisin: mediaani +87 ms, vaihteluväli −118…+557 ms,
ja noin yhdellä sanalla sadasta alku on 1,0–2,5 s liian aikaisin. Tauon
jälkeen mediaani on +263 ms. Mikään vakio ei korjaa sitä, ja äänen energiasta
sanan alkua ei löydä luotettavasti (tavun alku ja sanan alku eivät ole sama).

Tämä kohdistaa **tekstin** ääneen foneettisesti (CTC, torchaudion ``MMS_FA``,
joka tukee suomea) 20 ms:n kehyksillä, eikä luota Whisperin omaan aika-arvioon.
Samoilla 15 sanalla kohdistimen mediaanivirhe on 28 ms ja Whisperin 117 ms.

Kirjasto on yksi tiedosto, koska se on myös **ladattava**: colab-transcribe
lähettää ``wordalign.py``n Colabiin skriptin viereen, jossa työtilaa ei ole.
podcast-magic tuo saman tiedoston kuin mitä tahansa pakettia, joten kopiota ei
ole eikä sen driftiä tarvitse vartioida. Siksi kirjasto ei tunne kumpaakaan
sovellusta: ei ``Word``ia, ei ``Options``ia, ei välimuistia. Kutsuja antaa
Whisperin raakatuloksen (``segments[].words[]``) ja äänen ja saa rivit.

Neljä sääntöä on mitattu eikä keksitty:

* **Ryhmät katkaistaan tauoista** (``SPLIT_GAP_S``). Segmentissä oli 2,9 s tauko,
  jossa kuului toisen mikin ääntä, ja kohdistin sijoitti tauon jälkeisen sanan
  sinne, 2,7 s liian aikaisin. Pakotettu kohdistus ahtaa sanat peräkkäin.
* **Siirto myöhemmäksi hyväksytään kolmeen sekuntiin** (``MAX_LATE_S``).
  Kuunneltaessa neljä sanaa, joita Whisper oli 1,0–2,5 s liian aikaisin,
  kohdistin osui 34 ms:n sisään jokaisessa.
* **Siirto aikaisemmaksi vain 0,3 s** (``MAX_EARLY_S``). Whisper ei ole koskaan
  ollut yli 0,12 s myöhässä, ja ainoa mitattu suuri siirto aikaisemmaksi oli
  väärä. Raja pitää olla alle ``PAD_S``:n: ikkuna alkaa ``PAD_S`` ennen leimaa,
  joten sitä suurempi siirto aikaisemmaksi on mahdoton ja raja olisi tyhjä.
* **Hylätty sana ei saa aikaa** eikä arvausta: se jää Whisperin aikaan ja syy
  kirjataan.

Mitä **ei** ole mitattu: sanan loppu, ajautuminen pitkässä äänityksessä, muut
puhujat ja jaksot, ja Colabin GPU-reitti. Siksi ``refined`` ottaa alun
kohdistimelta mutta lopun pidemmästä kahdesta: vaimennus käyttää sanojen välejä
äänen paikkana, ja liian lyhyt sana leikkaisi äänen.

Neuroverkko annetaan funktiolle parametrina (``aligner``), jotta kaikki sen
ympärillä on testattavissa ilman torchia. Paino (noin 1,2 Gt) ladataan
ensimmäisellä ajolla käyttäjän välimuistiin eikä sitä paketoida.

Komentorivi (``python3 wordalign.py --check`` ja ``python3 wordalign.py
TYÖT.json``) on Colabia varten: kohdistus ajetaan omassa prosessissaan, jotta
torchin kirjastot eivät sekoitu litteroinnin (CTranslate2) kirjastoihin.
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import unicodedata

import numpy as np

#: Kohdistimen näytetaajuus (``torchaudio.pipelines.MMS_FA.sample_rate``) ja
#: sama kuin ``audio.SAMPLE_RATE``, joten litteroinnin purkama ääni kelpaa suoraan.
RATE = 16000

#: Täyte ryhmän molemmin puolin sekunteina. Whisperin leima voi olla sadan
#: millisekunnin verran pielessä (mitattu), joten ikkunan pitää ulottua sanan
#: oikean alun taakse. Liian suuri täyte vetää viereisen sanan äänen mukaan.
PAD_S = 0.5

#: Tätä pidempi tauko sanojen välillä aloittaa uuden kohdistusryhmän. Puheen
#: sisäiset tauot ovat harvoin yli puolen sekunnin, joten ryhmä ei menetä
#: kontekstia jonka kohdistin tarvitsee.
SPLIT_GAP_S = 0.5

#: Litteroinnin, jossa on vain tasainen sanalista, ryhmittely.
GROUP_GAP_S = 1.0
GROUP_MAX_S = 25.0

#: Siirto Whisperin leimasta on epäsymmetrinen, koska Whisperin virhe on: se on
#: lähes aina liian aikaisin. Suuri siirto *myöhemmäksi* on korjaus (kaikki
#: kahdeksan mitattua olivat enintään 2,5 s), yli tämän selittämätön.
MAX_LATE_S = 3.0

#: Siirto *aikaisemmaksi* on epäilyttävä (ks. moduulin ohje); alle ``PAD_S``.
MAX_EARLY_S = 0.3

#: Kohdistuksen välimuistin versio. Se vaihtuu kun sääntö tai malli vaihtuu,
#: jolloin vanha tulos ei kelpaa uuden nimen alla.
VERSION = "ctc1"


#: Ohje, kun torch puuttuu. Kutsuja voi antaa omansa (``make_aligner(install=...)``).
INSTALL = "pip install torch==2.8.0 torchaudio==2.8.0"


class AlignerUnavailable(RuntimeError):
    """Kohdistin ei ole käytettävissä: torch tai torchaudio puuttuu."""


def make_aligner(install: str = INSTALL):
    """Torchaudion ``MMS_FA``: monikielinen CTC-kohdistin (tukee suomea).

    Painot (noin 1,2 Gt) ladataan ensimmäisellä ajolla ja jäävät käyttäjän
    välimuistiin. Palauttaa funktion ``align(pala, sanat) -> [(alku, loppu)]``,
    sekunteina palan alusta; ``pala`` on 16 kHz:n float32-mono.
    """
    try:
        import torch
        import torchaudio
    except ImportError as exc:
        raise AlignerUnavailable(
            f"Kohdistus tarvitsee torchin ja torchaudion ({exc}). Asenna: {install}"
        ) from exc

    bundle = torchaudio.pipelines.MMS_FA
    model = bundle.get_model(with_star=False).eval()
    tokenizer = bundle.get_tokenizer()
    aligner = bundle.get_aligner()

    def align(chunk, words):
        waveform = torch.from_numpy(np.array(chunk, dtype=np.float32))[None, :]
        with torch.inference_mode():
            emission, _ = model(waveform)
        spans = aligner(emission[0], tokenizer(words))
        ratio = waveform.size(1) / emission.size(1) / bundle.sample_rate
        return [(s[0].start * ratio, s[-1].end * ratio) for s in spans]

    return align


def normalise_word(text: str) -> str:
    """Sana sellaiseksi kuin malli tuntee: pienet kirjaimet a-z ja heittomerkki.

    ä, ö ja å romanisoidaan ``a``, ``o`` ja ``a``; numerot ja välimerkit
    pudotetaan. Tyhjä tulos tarkoittaa sanaa, jota ei voi kohdistaa.
    """
    text = unicodedata.normalize("NFKD", text.replace("’", "'").lower())
    return "".join(c for c in text if ("a" <= c <= "z") or c == "'")


def _clean_words(raw) -> list[dict]:
    return [
        {
            "word": w.get("word", ""),
            "start": float(w["start"]),
            "end": float(w.get("end", w["start"])),
        }
        for w in raw
        if isinstance(w, dict) and w.get("start") is not None
    ]


def groups_of(raw: dict) -> list[list[dict]]:
    """Whisperin raakatuloksesta sanaryhmät (segmentit); tyhjä lista jos sanoja ei ole."""
    groups: list[list[dict]] = []
    if isinstance(raw, dict) and raw.get("segments"):
        for segment in raw["segments"]:
            words = _clean_words(segment.get("words") or [])
            if words:
                groups.append(words)
    elif isinstance(raw, dict) and raw.get("words"):
        current: list[dict] = []
        for word in _clean_words(raw["words"]):
            if current and (
                word["start"] - current[-1]["end"] > GROUP_GAP_S
                or word["end"] - current[0]["start"] > GROUP_MAX_S
            ):
                groups.append(current)
                current = []
            current.append(word)
        if current:
            groups.append(current)
    return groups


def split_at_pauses(
    groups: list[list[dict]], gap: float = SPLIT_GAP_S
) -> list[list[dict]]:
    """Ryhmät katkaistuna kohdista, joissa sanojen välissä on yli ``gap`` sekuntia."""
    out: list[list[dict]] = []
    for words in groups:
        current: list[dict] = []
        for word in words:
            if current and word["start"] - current[-1]["end"] > gap:
                out.append(current)
                current = []
            current.append(word)
        if current:
            out.append(current)
    return out


def window(words: list[dict], audio_s: float, pad: float = PAD_S) -> tuple[float, float]:
    """Ryhmän ikkuna täytteineen, rajattuna äänen sisään."""
    return max(0.0, words[0]["start"] - pad), min(audio_s, words[-1]["end"] + pad)


def align_words(
    words: list[dict],
    audio: np.ndarray,
    aligner,
    pad: float = PAD_S,
    errors: list | None = None,
) -> list[dict]:
    """Yhden ryhmän sanat kohdistettuna; ajat koko äänen aika-akselilla.

    ``aligner(pala, sanat) -> [(alku, loppu), ...]`` sekunteina palan alusta.
    Epäonnistuminen ei kaada ajoa: ryhmän sanat jäävät ilman aikaa ja syy
    kirjataan ``errors``iin. ``None`` ei ole nolla.
    """
    out = [{**w, "ctc_start": None, "ctc_end": None} for w in words]
    texts = [normalise_word(w["word"]) for w in words]
    keep = [i for i, t in enumerate(texts) if t]
    if not keep:
        return out
    start, end = window(words, len(audio) / RATE, pad)
    chunk = audio[int(round(start * RATE)) : int(round(end * RATE))]
    try:
        spans = aligner(chunk, [texts[i] for i in keep])
        if len(spans) != len(keep):
            raise RuntimeError(
                f"aligner returned {len(spans)} spans for {len(keep)} words"
            )
    except Exception as exc:  # mallin virhe ei saa kaataa muita ryhmiä
        if errors is not None:
            errors.append(f"{start:.1f}-{end:.1f} s: {exc}")
        return out
    for i, (a, b) in zip(keep, spans, strict=True):
        shift = start + a - words[i]["start"]
        if shift > MAX_LATE_S or shift < -MAX_EARLY_S:
            if errors is not None:
                errors.append(
                    f"{words[i]['word'].strip()} at {words[i]['start']:.2f} s: aligner said "
                    f"{start + a:.2f} s ({shift:+.1f} s from Whisper), rejected"
                )
            continue
        out[i]["ctc_start"] = start + a
        out[i]["ctc_end"] = start + b
    return out


def align_raw(
    raw: dict, audio: np.ndarray, aligner, pad: float = PAD_S, errors: list | None = None
) -> list[dict]:
    """Kaikki Whisperin raakatuloksen sanat kohdistettuna, järjestys ennallaan."""
    rows: list[dict] = []
    for words in split_at_pauses(groups_of(raw)):
        rows.extend(align_words(words, audio, aligner, pad, errors))
    return rows


def align_segments(
    segments: list[dict],
    audio: np.ndarray,
    aligner,
    pad: float = PAD_S,
    errors: list | None = None,
) -> list[dict]:
    """Kohdista lauseteksti suoraan sen aikarajojen sisällä.

    Käytetään malleille, jotka palauttavat segmentin ajat mutta eivät
    sanakohtaisia siemenleimoja. Toisin kuin ``align_words``, tässä ei
    hyväksytä tai hylätä sanoja arvioidun sanaleiman siirron perusteella:
    kohdistin sovittaa koko lauseen tekstin rajattuun äänipalaan.
    """
    rows: list[dict] = []
    audio_s = len(audio) / RATE
    for segment in segments:
        start = float(segment["start"])
        end = float(segment["end"])
        words = [word for word in str(segment.get("text", "")).split() if word]
        if not words:
            continue
        window_start = max(0.0, start - pad)
        window_end = min(audio_s, end + pad)
        chunk = audio[int(round(window_start * RATE)) : int(round(window_end * RATE))]
        texts = [normalise_word(word) for word in words]
        keep = [index for index, text in enumerate(texts) if text]
        spans_by_index: dict[int, tuple[float, float]] = {}
        try:
            spans = aligner(chunk, [texts[index] for index in keep])
            if len(spans) != len(keep):
                raise RuntimeError(
                    f"aligner returned {len(spans)} spans for {len(keep)} words"
                )
            spans_by_index = dict(zip(keep, spans, strict=True))
        except Exception as exc:
            if errors is not None:
                errors.append(f"{start:.1f}-{end:.1f} s: {exc}")
        for index, word in enumerate(words):
            span = spans_by_index.get(index)
            rows.append(
                {
                    "word": word,
                    "start": start,
                    "end": end,
                    "ctc_start": window_start + span[0] if span else None,
                    "ctc_end": window_start + span[1] if span else None,
                }
            )
    return rows


def refined(rows: list[dict]) -> list[dict]:
    """Kohdistetut sanat: alku kohdistimelta, loppu pidemmästä kahdesta.

    Alku on mitattu. Loppua ei ole, ja vaimennus käyttää sanojen välejä äänen
    paikkana, joten liian lyhyt sana leikkaisi äänen: pidempi kahdesta on
    varovainen valinta. Sana, jota ei kohdistettu, pysyy Whisperin aikana.
    Tyhjä teksti jätetään pois. Rivit ``{"word", "start", "end"}``; pituuden
    lattian ja järjestyksen päättää kutsuja.
    """
    out: list[dict] = []
    for row in rows:
        text = str(row["word"]).strip()
        if not text:
            continue
        start = row["start"] if row["ctc_start"] is None else row["ctc_start"]
        end = row["end"] if row["ctc_end"] is None else max(row["end"], row["ctc_end"])
        out.append({"word": text, "start": start, "end": end})
    return out


def summarize(rows: list[dict], rejected: list[str]) -> dict:
    """Mitä kohdistus teki: montako sanaa kohdistui ja kuinka paljon alut siirtyivät."""
    shifts = [
        (r["ctc_start"] - r["start"]) * 1000 for r in rows if r["ctc_start"] is not None
    ]
    return {
        "words": len(rows),
        "aligned": len(shifts),
        "median_shift_ms": statistics.median(shifts) if shifts else None,
        "rejected": list(rejected),
    }


def decode(path: str) -> np.ndarray:
    """Tiedosto 16 kHz:n float32-monoksi ffmpegillä (Colabissa se on asennettu)."""
    cmd = [
        "ffmpeg",
        "-nostdin",
        "-v",
        "error",
        "-i",
        str(path),
        "-f",
        "f32le",
        "-ac",
        "1",
        "-ar",
        str(RATE),
        "-",
    ]
    out = subprocess.run(cmd, check=True, capture_output=True).stdout
    return np.frombuffer(out, dtype="<f4")


def run_jobs(jobs: list[dict], aligner, decode_audio=decode, log=print) -> None:
    """Jokaiselle työlle ``{"audio", "raw", "out"}`` kirjoitetaan ``out``.

    ``out`` on ``{"version", "rows", "rejected"}``: rivit ``align_raw``sta ja
    hylkäysten syyt. Äänen purku on työn omaa aikaa, ja se puretaan kerran.
    """
    total = len(jobs)
    for index, job in enumerate(jobs, 1):
        log(f"[kohdistus ({index}/{total})] {job['audio']}")
        with open(job["raw"], encoding="utf-8") as handle:
            raw = json.load(handle)
        rejected: list[str] = []
        rows = align_raw(raw, decode_audio(job["audio"]), aligner, errors=rejected)
        with open(job["out"], "w", encoding="utf-8") as handle:
            json.dump(
                {"version": VERSION, "rows": rows, "rejected": rejected},
                handle,
                ensure_ascii=False,
            )


def main(argv=None, aligner=None) -> int:
    parser = argparse.ArgumentParser(description="Sanojen alkujen kohdistus ääneen")
    parser.add_argument("jobs", nargs="?", help="JSON: [{audio, raw, out}, ...]")
    parser.add_argument(
        "--check",
        action="store_true",
        help="lataa kohdistin (painot mukaan) ja poistu; 0 jos se toimii",
    )
    args = parser.parse_args(argv)
    if not args.check and not args.jobs:
        parser.error("anna työtiedosto tai --check")
    try:
        if aligner is None:
            aligner = make_aligner()
    except Exception as exc:
        print(f"Kohdistin ei käynnisty: {exc}", file=sys.stderr)
        return 1
    if args.check:
        print("Kohdistin toimii.")
        return 0
    with open(args.jobs, encoding="utf-8") as handle:
        jobs = json.load(handle)
    run_jobs(jobs, aligner, decode_audio=decode)
    return 0


if __name__ == "__main__":
    sys.exit(main())
