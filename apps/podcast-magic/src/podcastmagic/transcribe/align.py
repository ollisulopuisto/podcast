"""Kohdistus: Whisperin sanat pakotetaan ääneen, ja sanojen alut korjataan.

Whisperin sanaleimat ovat huomiomatriisin arvio, ja käsin merkittyjä alkuja
vasten mitattuna (15 sanaa, yksi puhuja, jakson ``vst s13e04`` raaka mikki)
ne ovat lähes aina liian aikaisin: mediaani +87 ms, vaihteluväli −118…+557 ms,
ja noin yhdellä sanalla sadasta alku on 1,0–2,5 s liian aikaisin. Tauon
jälkeen mediaani on +263 ms. Mikään vakio ei korjaa sitä, ja äänen energiasta
sanan alkua ei löydä luotettavasti (tavun alku ja sanan alku eivät ole sama).

Tämä kohdistaa **tekstin** ääneen foneettisesti (CTC, torchaudion ``MMS_FA``,
joka tukee suomea) 20 ms:n kehyksillä, eikä luota Whisperin omaan aika-arvioon.
Samoilla 15 sanalla kohdistimen mediaanivirhe on 28 ms ja Whisperin 117 ms.

Kohdistus ajetaan **jälkivaiheena**: se lukee Whisperin raakatuloksen
(``segments[].words[]``), joten sama JSON kelpaa kaikille moottoreille eikä
litterointia tarvitse ajaa uudestaan. Tulos on oma välimuistinsa
(``cache_path``), koska kohdistus vaihtuu Whisperistä riippumatta.

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
puhujat ja jaksot, ja Colabin GPU-reitti. Siksi ``refined_words`` ottaa alun
kohdistimelta mutta lopun pidemmästä kahdesta: vaimennus käyttää sanojen välejä
äänen paikkana, ja liian lyhyt sana leikkaisi äänen.

Neuroverkko annetaan funktiolle parametrina (``aligner``), jotta kaikki sen
ympärillä on testattavissa ilman torchia. Paino (noin 1,2 Gt) ladataan
ensimmäisellä ajolla käyttäjän välimuistiin eikä sitä paketoida.
"""

from __future__ import annotations

import importlib.util
import json
import statistics
import unicodedata
from pathlib import Path

import numpy as np

from ..nhsx import Word
from .options import Options

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

#: Asennus. Ei ole ``--extra``: torch on jo ``fcp-subs-whisper``in riippuvuus eri
#: versiolla (>=2.5.1, lukossa 2.13), ja kohdistin tarvitsee torchaudion 2.8:n,
#: koska ``forced_align`` poistuu 2.9:stä. Lisäriippuvuus pakottaisi toisen
#: sovelluksen torchin toiseen versioon hiljaa. ``--with`` ei kosketa lukkoa.
INSTALL = "uv run --package podcast-magic --with torch==2.8.0 --with torchaudio==2.8.0 podcast-magic"


class AlignerUnavailable(RuntimeError):
    """Kohdistin ei ole käytettävissä: torch tai torchaudio puuttuu."""


def _installed(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def availability() -> dict:
    """Onko kohdistin asennettu. Näytetään käyttöliittymässä ennen ajoa."""
    missing = [name for name in ("torch", "torchaudio") if not _installed(name)]
    if missing:
        return {
            "available": False,
            "reason": f"puuttuu: {', '.join(missing)}",
            "install": INSTALL,
        }
    return {"available": True, "reason": "", "install": INSTALL}


def make_aligner():
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
            f"Kohdistus tarvitsee torchin ja torchaudion ({exc}). Asenna: {INSTALL}"
        ) from exc

    bundle = torchaudio.pipelines.MMS_FA
    model = bundle.get_model(with_star=False).eval()
    tokenizer = bundle.get_tokenizer()
    aligner = bundle.get_aligner()

    def align(chunk, words):
        waveform = torch.from_numpy(np.asarray(chunk, dtype=np.float32))[None, :]
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


def refined_words(rows: list[dict]) -> list[Word]:
    """Kohdistetut sanat istuntoon: alku kohdistimelta, loppu pidemmästä kahdesta.

    Alku on mitattu. Loppua ei ole, ja vaimennus käyttää sanojen välejä äänen
    paikkana, joten liian lyhyt sana leikkaisi äänen: pidempi kahdesta on
    varovainen valinta. Sana, jota ei kohdistettu, pysyy Whisperin aikana.
    Nollapituinen sana saa lattian, kuten ``words_from_segments``issa.
    """
    out: list[Word] = []
    for row in rows:
        text = str(row["word"]).strip()
        if not text:
            continue
        start = row["start"] if row["ctc_start"] is None else row["ctc_start"]
        end = row["end"] if row["ctc_end"] is None else max(row["end"], row["ctc_end"])
        out.append(Word(text=text, start=start, length=max(0.02, end - start)))
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
        "cache_error": None,
    }


def cache_path(directory: Path, audio_path: str, options: Options) -> Path:
    """Kohdistuksen välimuisti: äänen nimi, Whisperin tunniste ja kohdistuksen versio.

    Whisperin tunniste on nimessä, koska kohdistus on tehty sen sanoista; toisella
    mallilla tehdyistä sanoista tämä olisi väärä tulos.
    """
    stem = Path(audio_path).stem
    return Path(directory) / f"{stem}.{options.fingerprint()}.align-{VERSION}.json"


def _load(path: Path, source: list) -> tuple[list[dict], list[str]] | None:
    """Välimuisti, jos se on samasta versiosta ja samoista sanoista; muuten ``None``."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("version") != VERSION:
        return None
    if data.get("source") != source:
        return None
    rows, rejected = data.get("rows"), data.get("rejected")
    if not isinstance(rows, list) or not isinstance(rejected, list):
        return None
    return rows, rejected


def refine(raw: dict, samples: np.ndarray, get_aligner, cache: Path | None = None):
    """Whisperin raakatuloksesta korjatut sanat ja yhteenveto.

    ``get_aligner()`` palauttaa kohdistimen ja ``samples`` äänen (16 kHz float32
    -taulukko tai sen palauttava funktio) vasta kun niitä tarvitaan, joten
    välimuistista luettaessa mallia ei ladata eikä ääntä pureta. Välimuisti
    kelpaa vain jos se on tehty samoista sanoista samalla versiolla.
    """
    flat = [w for group in groups_of(raw) for w in group]
    if not flat:
        return [], summarize([], [])
    source = [[w["word"], w["start"]] for w in flat]
    cached = _load(cache, source) if cache else None
    if cached is not None:
        rows, rejected = cached
        return refined_words(rows), summarize(rows, rejected)
    rejected: list[str] = []
    audio = samples() if callable(samples) else samples
    rows = align_raw(raw, audio, get_aligner(), errors=rejected)
    summary = summarize(rows, rejected)
    if cache:
        try:
            Path(cache).write_text(
                json.dumps(
                    {
                        "version": VERSION,
                        "source": source,
                        "rows": rows,
                        "rejected": rejected,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except OSError as exc:
            summary["cache_error"] = str(exc)
    return refined_words(rows), summary
