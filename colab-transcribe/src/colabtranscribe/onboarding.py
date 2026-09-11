"""Apuohjelmien ja ympäristömuuttujien tarkistus ja opastus (onboarding).

Tarkistaa että tarvittavat työkalut (`colab`-komento) ja
tunnistetiedot (Google Cloud ADC tai Colab-token) ovat kunnossa ennen
ajoa. Jos jokin puuttuu, antaa selkeät ja välittömästi ajettavat ohjeet.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


def patch_colab_cli_automation(colab_path: str | None = None) -> bool:
    """Tarkistaa ja korjaa google-colab-cli:n Drive-valtuutusbugin.

    Upstream google-colab-cli 0.6.0 jää odottamaan Enteriä /dev/tty:stä, mikä
    jumiuttaa tausta-ajot ja TUI-sovellukset selaintunnistuksen jälkeen.
    Korvaamme odotuksen automaattisella selaintunnistuksen kyselyllä (polling).
    """
    if not colab_path:
        colab_path = shutil.which("colab")
    if not colab_path:
        return False
    try:
        colab_file = Path(colab_path)
        if not colab_file.is_file():
            return False
        shebang = colab_file.read_text(encoding="utf-8", errors="ignore").splitlines()[0]
        if not shebang.startswith("#!"):
            return False
        py_bin = shebang[2:].strip()
        if not Path(py_bin).is_file():
            return False

        res = subprocess.run(
            [py_bin, "-c", "import colab_cli.commands.automation as a; print(a.__file__)"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if res.returncode != 0 or not res.stdout.strip():
            return False
        automation_path = Path(res.stdout.strip())
        if not automation_path.is_file():
            return False

        content = automation_path.read_text(encoding="utf-8")
        if 'poll_params["dryrun"] = "false"' in content:
            return True

        pattern = re.compile(
            r'([ \t]*)try:\s*\n'
            r'[ \t]*webbrowser\.open\(uri\)\s*\n'
            r'[ \t]*typer\.echo\("[^"]*"\)\s*\n'
            r'[ \t]*except Exception:\s*\n'
            r'[ \t]*pass\s*\n'
            r'[ \t]*sys\.stdout\.write\("Press Enter after you have granted access\.\.\. "\)\s*\n'
            r'[ \t]*sys\.stdout\.flush\(\)\s*\n'
            r'[ \t]*with open\("/dev/tty"\) as tty:\s*\n'
            r'[ \t]*tty\.readline\(\)',
            re.MULTILINE,
        )

        def _repl(m: re.Match[str]) -> str:
            indent = m.group(1)
            return (
                f'{indent}if not os.environ.get("COLAB_CLI_NO_BROWSER"):\n'
                f'{indent}    try:\n'
                f'{indent}        webbrowser.open(uri)\n'
                f'{indent}        typer.echo("[colab] Opening authorization URL automatically in your default browser...")\n'
                f'{indent}    except Exception:\n'
                f'{indent}        pass\n'
                f'{indent}typer.echo("[colab] Waiting for authorization in browser...")\n'
                f'{indent}import time\n'
                f'{indent}deadline = time.time() + 300\n'
                f'{indent}poll_params = dict(params)\n'
                f'{indent}poll_params["dryrun"] = "false"\n'
                f'{indent}while time.time() < deadline:\n'
                f'{indent}    time.sleep(2)\n'
                f'{indent}    try:\n'
                f'{indent}        resp = creds.request(\n'
                f'{indent}            "POST",\n'
                f'{indent}            url,\n'
                f'{indent}            params=poll_params,\n'
                f'{indent}            headers=headers,\n'
                f'{indent}            files={{"file_id": (None, "empty.ipynb")}},\n'
                f'{indent}        )\n'
                f'{indent}        data = json.loads(resp.text.split("\\n", 1)[-1])\n'
                f'{indent}        if data.get("success"):\n'
                f'{indent}            typer.echo("[colab] Authorization granted in browser.")\n'
                f'{indent}            break\n'
                f'{indent}    except Exception:\n'
                f'{indent}        pass\n'
                f'{indent}if not data.get("success"):\n'
                f'{indent}    typer.echo("[colab] Authorizing VM...")\n'
                f'{indent}    params["dryrun"] = "false"\n'
                f'{indent}    resp = creds.request(\n'
                f'{indent}        "POST",\n'
                f'{indent}        url,\n'
                f'{indent}        params=params,\n'
                f'{indent}        headers=headers,\n'
                f'{indent}        files={{"file_id": (None, "empty.ipynb")}},\n'
                f'{indent}    )'
            )

        if 'with open("/dev/tty")' in content:
            new_content = pattern.sub(_repl, content)
            if new_content != content:
                automation_path.write_text(new_content, encoding="utf-8")
                return True
        return True
    except Exception:
        return False


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
        patch_colab_cli_automation(colab_path)
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
