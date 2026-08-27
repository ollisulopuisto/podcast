"""Mallivalikoima ja sen käännös moottorin omalle nimelle.

Käyttäjä valitsee koon, ei repo-osoitetta. Sama valinta tarkoittaa
mlx-whisperille Hugging Face -reposta ja faster-whisperille kokonimeä, ja
kumpikin kirjoitetaan tähän kerran — ei kutsupaikkaan.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelChoice:
    key: str
    label: str
    mlx: str
    faster: str
    # Karkea arvio nopeudesta suhteessa reaaliaikaan M-sarjan koneella.
    # Suuntaa antava: se kertoo mikä on kertaluokkaa hitaampi, ei sekunteja.
    hint_fi: str
    hint_en: str


MODELS: tuple[ModelChoice, ...] = (
    ModelChoice(
        key="turbo",
        label="large-v3-turbo",
        mlx="mlx-community/whisper-large-v3-turbo",
        faster="turbo",
        hint_fi="Oletus. Tarkkuus lähes large-v3:n, murto-osa ajasta.",
        hint_en="Default. Nearly large-v3 accuracy at a fraction of the time.",
    ),
    ModelChoice(
        key="large-v3",
        label="large-v3",
        mlx="mlx-community/whisper-large-v3-mlx",
        faster="large-v3",
        hint_fi="Tarkin. Selvästi hitaampi kuin turbo.",
        hint_en="Most accurate. Clearly slower than turbo.",
    ),
    ModelChoice(
        key="medium",
        label="medium",
        mlx="mlx-community/whisper-medium-mlx",
        faster="medium",
        hint_fi="Nopeampi, suomessa turboa heikompi.",
        hint_en="Faster, weaker than turbo on Finnish.",
    ),
    ModelChoice(
        key="small",
        label="small",
        mlx="mlx-community/whisper-small-mlx",
        faster="small",
        hint_fi="Nopein käyttökelpoinen. Kokeiluihin.",
        hint_en="Fastest usable one. For trying things out.",
    ),
)

DEFAULT_MODEL = "turbo"


def model_choice(key: str) -> ModelChoice:
    """Valinta avaimella.

    Tuntematon avain palautetaan sellaisenaan molemmille moottoreille: siten
    kenttään voi kirjoittaa oman Hugging Face -repon ilman että valikkoa
    pitää kasvattaa jokaisen uuden julkaisun takia.
    """
    for choice in MODELS:
        if choice.key == key:
            return choice
    return ModelChoice(
        key=key, label=key, mlx=key, faster=key, hint_fi="Oma malli.", hint_en="Custom model."
    )
