"""Google Drive -siirto: pakkaus, resumable upload ja tiedostojen hallinta.

Mahdollistaa syötetiedostojen nopean lataamisen suoraan käyttäjän Google
Driveen, josta Colab-virtuaalikone noutaa ne sisäverkon nopeudella
`colab drivemount` -liitoksen kautta.
"""

from __future__ import annotations

import json
import os
import tarfile
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path

COLAB_TOKEN_PATH = Path.home() / ".config" / "colab-cli" / "token.json"
ADC_PATH = Path.home() / ".config" / "gcloud" / "application_default_credentials.json"
TOKEN_URL = "https://oauth2.googleapis.com/token"
DRIVE_FILES_URL = "https://www.googleapis.com/drive/v3/files"
DRIVE_UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable"

# Google Drivessa chunkin koon on oltava 256 KB:n monikerta. 8 MB on tehokas oletus.
DEFAULT_CHUNK_SIZE = 8 * 1024 * 1024


def get_drive_token() -> str:
    """Hakee ja tarvittaessa päivittää Google Drive -pääsytokenin.

    Etsii tunnistetiedot ensisijaisesti Colab CLI:n tokenista, toissijaisesti
    Google Cloud ADC:stä tai GOOGLE_APPLICATION_CREDENTIALS -tiedostosta.
    """
    token_data: dict | None = None

    if COLAB_TOKEN_PATH.is_file():
        try:
            token_data = json.loads(COLAB_TOKEN_PATH.read_text(encoding="utf-8"))
        except Exception:
            token_data = None

    if not token_data and ADC_PATH.is_file():
        try:
            token_data = json.loads(ADC_PATH.read_text(encoding="utf-8"))
        except Exception:
            token_data = None

    gac = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not token_data and gac and Path(gac).is_file():
        try:
            token_data = json.loads(Path(gac).read_text(encoding="utf-8"))
        except Exception:
            token_data = None

    if not token_data:
        raise RuntimeError(
            "Google-tunnistetietoja ei löydy. Kirjaudu ajamalla:\n"
            "  uv tool run google-colab-cli auth login\n"
            "tai: gcloud auth application-default login"
        )

    # Jos access_token on valmiina ja voimassa, käytetään sitä
    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")
    client_id = token_data.get("client_id")
    client_secret = token_data.get("client_secret")

    if access_token and not refresh_token:
        return access_token

    if not refresh_token or not client_id:
        if access_token:
            return access_token
        raise RuntimeError("Puutteellinen Google-token (refresh_token tai client_id puuttuu).")

    # Päivitetään access_token refresh_tokenilla
    req_data = urllib.parse.urlencode({
        "client_id": client_id,
        "client_secret": client_secret or "",
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }).encode("utf-8")

    req = urllib.request.Request(TOKEN_URL, data=req_data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with urllib.request.urlopen(req) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return payload["access_token"]
    except Exception as err:
        if access_token:
            return access_token
        raise RuntimeError(f"Google-tokenin virkistys epäonnistui: {err}") from err


def create_input_archive(input_dir: Path, archive_path: Path) -> Path:
    """Pakkaa syötekansion tiedostot yhteen .tar.gz-pakettiin.

    Jättää pois piilotiedostot (.DS_Store ym.) ja tallentaa suhteelliset polut.
    """
    root = input_dir.resolve()
    archive_path.parent.mkdir(parents=True, exist_ok=True)

    with tarfile.open(archive_path, "w:gz") as tar:
        for dirpath, dirnames, filenames in root.walk(follow_symlinks=False):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for name in filenames:
                if name.startswith("."):
                    continue
                file_path = dirpath / name
                try:
                    resolved = file_path.resolve()
                except OSError:
                    continue
                if not resolved.is_file() or not resolved.is_relative_to(root):
                    continue
                rel_name = file_path.relative_to(root).as_posix()
                tar.add(file_path, arcname=rel_name)

    return archive_path


def ensure_folder(folder_name: str, parent_id: str | None = None, token: str = "") -> str:
    """Tarkistaa onko kansio olemassa Google Drivessa tai luo uuden."""
    if not token:
        token = get_drive_token()

    query = f"name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    if parent_id:
        query += f" and '{parent_id}' in parents"

    url = f"{DRIVE_FILES_URL}?q={urllib.parse.quote(query)}&spaces=drive&fields=files(id,name)"
    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", f"Bearer {token}")

    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        files = data.get("files", [])
        if files:
            return files[0]["id"]

    # Luodaan uusi kansio
    meta: dict[str, str | list[str]] = {
        "name": folder_name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    if parent_id:
        meta["parents"] = [parent_id]

    body = json.dumps(meta).encode("utf-8")
    create_req = urllib.request.Request(DRIVE_FILES_URL, data=body, method="POST")
    create_req.add_header("Authorization", f"Bearer {token}")
    create_req.add_header("Content-Type", "application/json; charset=UTF-8")

    with urllib.request.urlopen(create_req) as resp:
        res = json.loads(resp.read().decode("utf-8"))
        return res["id"]


def upload_resumable(
    file_path: Path,
    folder_id: str,
    token: str = "",
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    progress_callback: Callable[[int, int], None] | None = None,
) -> str:
    """Lataa tiedoston Google Driveen suoralla resumable upload -protokollalla."""
    if not token:
        token = get_drive_token()

    total_size = file_path.stat().st_size
    filename = file_path.name

    # 1. Aloita lataussessio
    meta = {
        "name": filename,
        "parents": [folder_id],
    }
    init_req = urllib.request.Request(DRIVE_UPLOAD_URL, data=json.dumps(meta).encode("utf-8"), method="POST")
    init_req.add_header("Authorization", f"Bearer {token}")
    init_req.add_header("Content-Type", "application/json; charset=UTF-8")
    init_req.add_header("X-Upload-Content-Type", "application/gzip")
    init_req.add_header("X-Upload-Content-Length", str(total_size))

    with urllib.request.urlopen(init_req) as resp:
        upload_url = resp.headers.get("Location")
        if not upload_url:
            raise RuntimeError("Google Drive ei palauttanut latausosoitetta (Location-otsaketta).")

    # 2. Lähetä data lohkoina
    with open(file_path, "rb") as f:
        bytes_sent = 0
        while bytes_sent < total_size:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            chunk_len = len(chunk)
            range_end = bytes_sent + chunk_len - 1

            chunk_req = urllib.request.Request(upload_url, data=chunk, method="PUT")
            chunk_req.add_header("Content-Range", f"bytes {bytes_sent}-{range_end}/{total_size}")
            chunk_req.add_header("Content-Length", str(chunk_len))

            try:
                with urllib.request.urlopen(chunk_req) as chunk_resp:
                    bytes_sent += chunk_len
                    if progress_callback:
                        progress_callback(bytes_sent, total_size)
                    if chunk_resp.status in (200, 201):
                        payload = json.loads(chunk_resp.read().decode("utf-8"))
                        return payload.get("id", "")
            except urllib.error.HTTPError as err:
                if err.code == 308:
                    bytes_sent += chunk_len
                    if progress_callback:
                        progress_callback(bytes_sent, total_size)
                    continue
                raise RuntimeError(f"Virhe Google Drive -latauksessa (HTTP {err.code}): {err.reason}") from err

    return ""


def delete_file_or_folder(file_id: str, token: str = "") -> None:
    """Poistaa tiedoston tai kansion Google Drivesta."""
    if not token:
        token = get_drive_token()
    url = f"{DRIVE_FILES_URL}/{file_id}"
    req = urllib.request.Request(url, method="DELETE")
    req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req):
            pass
    except urllib.error.HTTPError as err:
        if err.code != 404:
            raise
