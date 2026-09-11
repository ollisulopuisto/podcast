"""Apuohjelmien ja ympäristömuuttujien tarkistus ja opastus (onboarding).

Tarkistaa että tarvittavat työkalut (`colab`-komento) ja
tunnistetiedot (Google Cloud ADC tai Colab-token) ovat kunnossa ennen
ajoa. Jos jokin puuttuu, antaa selkeät ja välittömästi ajettavat ohjeet.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class OnboardingItem:
    """Yhden vaatimuksen tila ja korjausohje."""

    key: str
    title: str
    ok: bool
    current_value: str
    instructions: str
    required: bool = True


@dataclass(frozen=True)
class OnboardingReport:
    """Kokonaisraportti järjestelmän valmiudesta."""

    items: list[OnboardingItem]

    @property
    def is_ready(self) -> bool:
        """Onko kaikki pakolliset vaatimukset täytetty."""
        return all(item.ok for item in self.items if item.required)

    def summary(self) -> str:
        """Selkeä tekstikooste terminaaliin tai lokiin."""
        lines = ["Järjestelmän valmius (colab-transcribe):"]
        for item in self.items:
            icon = "✓" if item.ok else "✗"
            req = " (pakollinen)" if item.required else ""
            lines.append(f"  [{icon}] {item.title}{req}: {item.current_value}")
            if not item.ok and item.instructions:
                indented = "\n".join(f"      {line}" for line in item.instructions.splitlines())
                lines.append(f"{indented}")
        return "\n".join(lines)


def check_helper_apps() -> list[OnboardingItem]:
    """Tarkistaa ulkoiset apuohjelmat."""
    items: list[OnboardingItem] = []

    colab_path = shutil.which("colab")
    if colab_path:
        items.append(
            OnboardingItem(
                key="colab",
                title="Google Colab CLI (colab)",
                ok=True,
                current_value=colab_path,
                instructions="",
                required=True,
            )
        )
    else:
        instructions = (
            "Asenna Google Colab CLI komennolla:\n"
            "  uv tool install google-colab-cli\n"
            "(tai vaihtoehtoisesti: pip install google-colab-cli)\n"
            "Varmista myös, että asennushakemisto (~/.local/bin) on PATH-muuttujassasi."
        )
        items.append(
            OnboardingItem(
                key="colab",
                title="Google Colab CLI (colab)",
                ok=False,
                current_value="Ei löydy PATHista",
                instructions=instructions,
                required=True,
            )
        )
    return items


def check_credentials() -> list[OnboardingItem]:
    """Tarkistaa pilvipalvelun tunnistetiedot ja ympäristömuuttujat."""
    items: list[OnboardingItem] = []

    # 1. GOOGLE_APPLICATION_CREDENTIALS -ympäristömuuttuja
    gac = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if gac:
        gac_path = Path(gac)
        if gac_path.is_file():
            items.append(
                OnboardingItem(
                    key="credentials",
                    title="Google Cloud -tunnisteet",
                    ok=True,
                    current_value=f"GOOGLE_APPLICATION_CREDENTIALS={gac}",
                    instructions="",
                    required=True,
                )
            )
            return items
        items.append(
            OnboardingItem(
                key="credentials",
                title="Google Cloud -tunnisteet",
                ok=False,
                current_value=f"GOOGLE_APPLICATION_CREDENTIALS viittaa puuttuvaan tiedostoon: {gac}",
                instructions=f"Tarkista että tiedosto on olemassa: {gac}",
                required=True,
            )
        )
        return items

    # 2. Application Default Credentials (gcloud ADC)
    adc_path = Path.home() / ".config" / "gcloud" / "application_default_credentials.json"
    if adc_path.is_file():
        items.append(
            OnboardingItem(
                key="credentials",
                title="Google Cloud -tunnisteet",
                ok=True,
                current_value=f"ADC löydetty ({adc_path})",
                instructions="",
                required=True,
            )
        )
        return items

    # 3. Colab CLI:n oma OAuth-token
    colab_token = Path.home() / ".config" / "colab-cli" / "token.json"
    if colab_token.is_file():
        items.append(
            OnboardingItem(
                key="credentials",
                title="Google Cloud -tunnisteet",
                ok=True,
                current_value=f"Colab CLI token löydetty ({colab_token})",
                instructions="",
                required=True,
            )
        )
        return items

    # 4. Ei tunnistetietoja
    instructions = (
        "Kirjaudu Google Cloudiin komennolla:\n"
        "  gcloud auth application-default login --scopes=openid,https://www.googleapis.com/auth/cloud-platform,https://www.googleapis.com/auth/userinfo.email,https://www.googleapis.com/auth/colaboratory\n"
        "tai aseta palvelutunnuksen JSON-avaintiedosto:\n"
        '  export GOOGLE_APPLICATION_CREDENTIALS="/polku/avaimeen.json"'
    )
    items.append(
        OnboardingItem(
            key="credentials",
            title="Google Cloud -tunnisteet",
            ok=False,
            current_value="Ei tunnistetietoja (ADC tai Colab-token puuttuu)",
            instructions=instructions,
            required=True,
        )
    )
    return items


def check_environment() -> OnboardingReport:
    """Tarkistaa koko järjestelmän tilan."""
    all_items = check_helper_apps() + check_credentials()
    return OnboardingReport(items=all_items)
