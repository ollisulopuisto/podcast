"""Asetukset ja niiden muoto pilvessä ajettavan skriptin argumenteiksi.

Tämä moduuli on sopimus paikallisen ja pilvessä ajettavan puolen välillä:
`pipeline_args`in tuottama lista menee merkkijonona `python3
/content/pipeline.py`n perään. Jos kenttä lisätään tänne, se on lisättävä
myös skriptiin — ja kenttä jää ilman vaikutusta jos vain toinen pää tietää
sen, ilman että mikään kaatuu.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: GPU:t joita Colab tarjoaa. `--gpu` menee suoraan `colab new`ille.
GPUS = ("T4", "L4", "A100")

#: Skriptin tuntemat esiasetukset. Niiden numerot asuvat pilvessä ajettavassa
#: skriptissa, ei täällä — täällä on vain valinta.
PRESETS = ("remote", "intra-mic")

#: Täytesanat Whispereille. Oletus on sama kuin skriptissa itsessään; jos
#: se muuttuu sinne, se muuttuu tänne samaan hengessä.
DEFAULT_PROMPT = "öö, tota, niinku, mhm, joo, silleen, vähän, niinkun, ööh, ömm."


@dataclass
class RunOptions:
    """Yksi ajo, alusta loppuun: istunto, siirrot ja leikkausasetukset."""

    session: str = "vst-pipeline"
    gpu: str = "T4"
    input_dir: str = ""
    output_dir: str = "output"
    preset: str = "remote"
    rms: bool = False
    thr: int = -35
    tail: float = 1.0
    gap: float = 1.0
    prompt: str = field(default=DEFAULT_PROMPT)

    def __post_init__(self):
        if self.gpu not in GPUS:
            raise ValueError(f"Tuntematon GPU: {self.gpu} (sallitut: {', '.join(GPUS)})")
        if self.preset not in PRESETS:
            raise ValueError(f"Tuntematon preset: {self.preset} (sallitut: {', '.join(PRESETS)})")
        if self.tail <= 0:
            raise ValueError(f"tail on oltava positiivinen, ei {self.tail}")
        if self.gap <= 0:
            raise ValueError(f"gap on oltava positiivinen, ei {self.gap}")


def pipeline_args(options: RunOptions) -> list[str]:
    """Asetukset skriptin komentoriviksi.

    Kaikki arvot viedään auki eikä luoteta pilvipään oletuksiin: ajo on
    toistettava ja se mitä ajettiin on nähtävä valmiissa komennossa.
    """
    args = [
        "--preset", options.preset,
        "--thr", str(options.thr),
        "--tail", str(options.tail),
        "--gap", str(options.gap),
        "--prompt", options.prompt,
    ]
    if options.rms:
        args.append("--rms")
    return args
