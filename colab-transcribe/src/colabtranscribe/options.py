"""Asetukset ja niiden muoto pilvessä ajettavan skriptin argumenteiksi.

Tämä moduuli on sopimus paikallisen ja pilvessä ajettavan puolen välillä:
`pipeline_args`in tuottama lista menee merkkijonona `python3
/content/pipeline.py`n perään. Jos kenttä lisätään tänne, se on lisättävä
myös skriptiin — ja kenttä jää ilman vaikutusta jos vain toinen pää tietää
sen, ilman että mikään kaatuu.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

#: GPU:t joita Colab tarjoaa. `--gpu` menee suoraan `colab new`ille.
GPUS = ("T4", "L4", "A100")

#: Skriptin tuntemat esiasetukset. Niiden numerot asuvat pilvessä ajettavassa
#: skriptissa, ei täällä — täällä on vain valinta.
PRESETS = ("remote", "intra-mic", "learned")

#: Tuetut siirtotavat. "drive" käyttää Google Drivea ja liitosta (nopea),
#: "direct" käyttää Colabin hidasta suoraa upload-tunnelia tiedosto kerrallaan.
TRANSFERS = ("drive", "direct")

#: Mitä litteroidaan. "tracks" litteroi raidat erikseen (puhujat tiedossa),
#: "downmix" litteroi koko miksauksen kerran ilman puhujia — ks. podcast-magicin
#: ``transcribe/downmix.py``. "audio" litteroi pelkät äänitiedostot ilman istuntoa
#: ja palauttaa sanat JSONina (``docs/KUULAS-COLAB.md``). Oletus on raidat, eikä
#: sitä kerrota skriptille.
SOURCES = ("tracks", "downmix", "audio")

#: Tuetut litterointitaustat. "colab" ajaa ketjun Google Colabissa (oletus),
#: "parakeet" tai "orukeet" ajaa litteroinnin paikallisesti Apple Siliconilla (parakeet-mlx / orukeet).
BACKENDS = ("colab", "parakeet", "orukeet")

#: Orukeet/Parakeet-oletusmalli paikalliseen ajoon.
DEFAULT_ORUKEET_MODEL = (
    str(Path.home() / ".models" / "orukeet-mlx")
    if (Path.home() / ".models" / "orukeet-mlx").exists()
    else "mlx-community/parakeet-tdt-0.6b-v3"
)
DEFAULT_PARAKEET_MODEL = DEFAULT_ORUKEET_MODEL

#: Orukeet ei tarjoa dekooderin initial prompt -toimintoa. Säilytetään
#: --prompt-yhteensopivuusvalitsin, mutta oletusarvo on tyhjä.
DEFAULT_PROMPT = ""


@dataclass
class RunOptions:
    """Yksi ajo, alusta loppuun: istunto, siirrot ja leikkausasetukset."""

    session: str = "whisper"
    gpu: str = "T4"
    input_dir: str = ""
    output_dir: str = "output"
    preset: str = "remote"
    transfer: str = "direct"
    # Isot PCM-WAVit FLACiksi ennen suoraa siirtoa (häviötön, puretaan Colabissa).
    compress: bool = True
    source: str = "tracks"
    rms: bool = False
    # Auto-Silence litteroinnin jälkeen. Pois päältä tulos on pelkkä
    # ``<jakso> litteroitu.nhsx`` — kaikki eivät vaimenna hiljaisia kohtia.
    silence: bool = True
    thr: int = -35
    tail: float = 1.0
    gap: float = 1.0
    prompt: str = field(default=DEFAULT_PROMPT)
    reset_session: bool = False
    keep_session: bool = False
    # Toisen mikin vuoto pois litteroinnista jonka istuntoon kirjoitetaan.
    bleed_filter: bool = True
    # Käsikirjoitus: lyhyet huomautukset kappaleen sisään, ei omille riveilleen.
    inline_remarks: bool = False
    # ``model`` säilyy yhteensopivuusvalitsimena; Colab käyttää Orukeetia.
    model: str = "parakeet-ultra"
    language: str = "fi"
    # Vain ``source="audio"``: sanojen alut kohdistetaan ääneen Colabissa
    # (``wordalign``), ja tiedoston ``timing`` on silloin ``ctc-v1``.
    align: bool = False
    # Litterointitausta: "colab" (Colab GPU, oletus) tai "parakeet" (paikallinen Apple Silicon).
    allow_low_memory: bool = False
    backend: str = "colab"
    parakeet_model: str = DEFAULT_PARAKEET_MODEL

    def __post_init__(self):
        if self.backend not in BACKENDS:
            raise ValueError(
                f"Tuntematon backend: {self.backend} (sallitut: {', '.join(BACKENDS)})"
            )
        if self.backend in ("parakeet", "orukeet") and self.source != "audio":
            raise ValueError(
                f"Backend '{self.backend}' tukee toistaiseksi vain pelkän äänen tilaa (--audio / --json). "
                "Käytä .nhsx-istuntojen paikalliseen ajoon podcast-magicia."
            )
        if not self.parakeet_model.strip():
            raise ValueError("parakeet_model ei saa olla tyhjä")
        if self.gpu not in GPUS:
            raise ValueError(f"Tuntematon GPU: {self.gpu} (sallitut: {', '.join(GPUS)})")
        if self.preset not in PRESETS:
            raise ValueError(
                f"Tuntematon preset: {self.preset} (sallitut: {', '.join(PRESETS)})"
            )
        if self.transfer not in TRANSFERS:
            raise ValueError(
                f"Tuntematon transfer: {self.transfer} (sallitut: {', '.join(TRANSFERS)})"
            )
        if self.source not in SOURCES:
            raise ValueError(
                f"Tuntematon source: {self.source} (sallitut: {', '.join(SOURCES)})"
            )
        if self.align and self.source != "audio":
            raise ValueError("align vaatii source=audio")
        if not self.model.strip():
            raise ValueError("model ei saa olla tyhjä")
        if not self.language.strip():
            raise ValueError("language ei saa olla tyhjä")
        if self.tail <= 0:
            raise ValueError(f"tail on oltava positiivinen, ei {self.tail}")
        if self.gap <= 0:
            raise ValueError(f"gap on oltava positiivinen, ei {self.gap}")

    def resolved_output_dir(self) -> Path:
        """Palauttaa tulostehakemiston polun. Jos polku on suhteellinen, se ratkaistaan suhteessa input_diriin."""
        out = Path(self.output_dir) if self.output_dir else Path("output")
        if self.input_dir and not out.is_absolute():
            inp = Path(self.input_dir)
            base = inp.parent if inp.is_file() else inp
            return base / out
        return out

    @classmethod
    def from_env(cls) -> RunOptions:
        """Luo asetukset ympäristömuuttujista, täydentäen puuttuvat oletuksilla."""
        import os

        session = os.environ.get("COLAB_SESSION", "whisper")
        gpu = os.environ.get("COLAB_GPU", "T4")
        input_dir = os.environ.get("COLAB_INPUT_DIR") or os.environ.get("COLAB_INPUT", "")
        output_dir = os.environ.get("COLAB_OUTPUT_DIR") or os.environ.get(
            "COLAB_OUTPUT", "output"
        )
        preset = os.environ.get("COLAB_PRESET", "remote")
        transfer = os.environ.get("COLAB_TRANSFER", "direct")
        source = os.environ.get("COLAB_SOURCE", "tracks")
        rms = os.environ.get("COLAB_RMS", "").lower() in ("1", "true", "yes")
        transcribe_only = os.environ.get("COLAB_TRANSCRIBE_ONLY", "").lower() in (
            "1",
            "true",
            "yes",
        )
        thr = int(os.environ.get("COLAB_THR", "-35"))
        tail = float(os.environ.get("COLAB_TAIL", "1.0"))
        gap = float(os.environ.get("COLAB_GAP", "1.0"))
        prompt = os.environ.get("COLAB_PROMPT", DEFAULT_PROMPT)
        reset_session = os.environ.get("COLAB_RESET_SESSION", "").lower() in (
            "1",
            "true",
            "yes",
        )
        keep_session = os.environ.get("COLAB_KEEP_SESSION", "").lower() in (
            "1",
            "true",
            "yes",
        )
        backend = os.environ.get("COLAB_BACKEND", "colab")
        parakeet_model = os.environ.get(
            "COLAB_ORUKEET_MODEL",
            os.environ.get("COLAB_PARAKEET_MODEL", DEFAULT_PARAKEET_MODEL),
        )

        return cls(
            session=session,
            gpu=gpu,
            input_dir=input_dir,
            output_dir=output_dir,
            preset=preset,
            transfer=transfer,
            source=source,
            rms=rms,
            silence=not transcribe_only,
            thr=thr,
            tail=tail,
            gap=gap,
            prompt=prompt,
            reset_session=reset_session,
            keep_session=keep_session,
            backend=backend,
            parakeet_model=parakeet_model,
        )


def pipeline_args(options: RunOptions) -> list[str]:
    """Asetukset skriptin komentoriviksi.

    Kaikki arvot viedään auki eikä luoteta pilvipään oletuksiin: ajo on
    toistettava ja se mitä ajettiin on nähtävä valmiissa komennossa.
    """
    args = [
        "--preset",
        options.preset,
        "--thr",
        str(options.thr),
        "--tail",
        str(options.tail),
        "--gap",
        str(options.gap),
        "--prompt",
        options.prompt,
    ]
    if options.source != "tracks":
        args += ["--source", options.source]
    if options.source == "audio":
        args += ["--model", options.model, "--language", options.language]
        if options.align:
            args.append("--align")
    if options.rms:
        args.append("--rms")
    if not options.silence:
        args.append("--no-silence")
    if not options.bleed_filter:
        args.append("--no-bleed-filter")
    if options.inline_remarks:
        args.append("--inline-remarks")
    return args
