"""Google Drive -siirto: pakkaus, resumable upload ja tiedostojen hallinta.

Mahdollistaa syötetiedostojen nopean lataamisen suoraan käyttäjän Google
Driveen, josta Colab-virtuaalikone noutaa ne sisäverkon nopeudella
`colab drivemount` -liitoksen kautta.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import datetime, timezone
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
    """Pakkaa syötekansion tiedostot yhteen .tar-pakettiin (pakkaamaton, nopea).

    Jättää pois piilotiedostot (.DS_Store ym.) ja tallentaa suhteelliset polut.
    """
    root = input_dir.resolve()
    archive_path.parent.mkdir(parents=True, exist_ok=True)

    with tarfile.open(archive_path, "w") as tar:
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


def get_quota_project(token: str = "") -> str | None:
    """Etsii aktiivisen GCP-kiintiöprojektin (quota project) Google Drive API -kutsuja varten."""
    proj = os.environ.get("COLAB_QUOTA_PROJECT") or os.environ.get("GOOGLE_CLOUD_QUOTA_PROJECT")
    if proj:
        return proj

    if ADC_PATH.is_file():
        try:
            data = json.loads(ADC_PATH.read_text(encoding="utf-8"))
            quota_id = data.get("quota_project_id")
            if quota_id and quota_id != "suosittelemme":
                return quota_id
        except Exception:
            pass

    if COLAB_TOKEN_PATH.is_file():
        try:
            data = json.loads(COLAB_TOKEN_PATH.read_text(encoding="utf-8"))
            quota_id = data.get("quota_project_id")
            if quota_id and quota_id != "suosittelemme":
                return quota_id
        except Exception:
            pass

    if token:
        try:
            url = "https://cloudresourcemanager.googleapis.com/v1/projects"
            req = urllib.request.Request(url)
            req.add_header("Authorization", f"Bearer {token}")
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                for p in data.get("projects", []):
                    if p.get("lifecycleState") == "ACTIVE":
                        pid = p.get("projectId", "")
                        if "drive" in pid:
                            return pid
                for p in data.get("projects", []):
                    if p.get("lifecycleState") == "ACTIVE":
                        return p.get("projectId")
        except Exception:
            pass

    return "g-drive-move-all-files"


def drive_request(
    url: str,
    data: bytes | None = None,
    method: str | None = None,
    token: str = "",
    headers: dict[str, str] | None = None,
) -> urllib.request.Request:
    """Luo HTTP-pyynnön Google Driven API:lle valtuutettuna ja kiintiöprojektilla varustettuna."""
    if not token:
        token = get_drive_token()
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    quota_project = get_quota_project(token)
    if quota_project:
        req.add_header("X-Goog-User-Project", quota_project)
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    return req


def ensure_folder(folder_name: str, parent_id: str | None = None, token: str = "") -> str:
    """Tarkistaa onko kansio olemassa Google Drivessa tai luo uuden."""
    if not token:
        token = get_drive_token()

    query = f"name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    if parent_id:
        query += f" and '{parent_id}' in parents"

    url = f"{DRIVE_FILES_URL}?q={urllib.parse.quote(query)}&spaces=drive&fields=files(id,name)"
    req = drive_request(url, method="GET", token=token)

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
    create_req = drive_request(
        DRIVE_FILES_URL,
        data=body,
        method="POST",
        token=token,
        headers={"Content-Type": "application/json; charset=UTF-8"},
    )

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
    init_req = drive_request(
        DRIVE_UPLOAD_URL,
        data=json.dumps(meta).encode("utf-8"),
        method="POST",
        token=token,
        headers={
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Type": "application/x-tar",
            "X-Upload-Content-Length": str(total_size),
        },
    )

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
    req = drive_request(url, method="DELETE", token=token)
    try:
        with urllib.request.urlopen(req):
            pass
    except urllib.error.HTTPError as err:
        if err.code != 404:
            raise


def compute_file_hash(file_path: Path) -> str:
    """Laskee tiedostolle MD5-tarkistussumman 1 MB paloissa."""
    hasher = hashlib.md5()
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def list_cache_files(cache_folder_id: str, token: str = "") -> list[dict]:
    """Listaa kaikki Google Driven välimuistikansiossa olevat tiedostot."""
    if not token:
        token = get_drive_token()
    query = f"'{cache_folder_id}' in parents and trashed = false"
    fields = "files(id,name,createdTime,md5Checksum)"
    url = f"{DRIVE_FILES_URL}?q={urllib.parse.quote(query)}&spaces=drive&fields={urllib.parse.quote(fields)}&pageSize=1000"
    req = drive_request(url, method="GET", token=token)
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        return data.get("files", [])


def prune_expired_cache(
    cache_folder_id: str,
    max_age_seconds: float = 24 * 3600,
    token: str = "",
    current_time: float | None = None,
) -> list[str]:
    """Poistaa välimuistikansiosta tiedostot jotka ovat vanhempia kuin max_age_seconds (oletus 24 h)."""
    if not token:
        token = get_drive_token()
    now_ts = current_time if current_time is not None else datetime.now(timezone.utc).timestamp()
    files = list_cache_files(cache_folder_id, token=token)
    deleted: list[str] = []
    for f in files:
        created_str = f.get("createdTime", "")
        if not created_str:
            continue
        try:
            created_dt = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
            age = now_ts - created_dt.timestamp()
            if age > max_age_seconds:
                delete_file_or_folder(f["id"], token=token)
                deleted.append(f["id"])
        except Exception:
            continue
    return deleted


def sync_input_to_cache(
    input_dir: Path,
    cache_folder_id: str,
    token: str = "",
    log: Callable[[str], None] | None = None,
) -> dict[str, str]:
    """Synkronoi syötekansion tiedostot Google Driven 24 h välimuistiin.

    Tiedostot tallennetaan nimellä `<hash>_<nimi>`. Jos tiedosto samalla
    sisällöllä löytyy jo Drivesta, sen lähetys ohitetaan kokonaan (0 sekuntia).
    Palauttaa manifestin suhteellisista poluista välimuistinimiin.
    """
    if not token:
        token = get_drive_token()

    # Siivotaan ensin vanhentuneet (> 24 h) pois
    pruned = prune_expired_cache(cache_folder_id, token=token)
    if pruned and log:
        log(f"  Siivottiin vanhentuneita tiedostoja välimuistista: {len(pruned)} kpl")

    # Haetaan nykyiset välimuistitiedostot
    cached_files = list_cache_files(cache_folder_id, token=token)
    cached_names = {f["name"]: f["id"] for f in cached_files if "name" in f}
    cached_md5s = {f["md5Checksum"]: f["name"] for f in cached_files if "md5Checksum" in f and f.get("md5Checksum")}

    root = input_dir.resolve()
    manifest: dict[str, str] = {}

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

            rel_path = file_path.relative_to(root).as_posix()
            file_hash = compute_file_hash(file_path)
            cache_name = f"{file_hash}_{name}"

            manifest[rel_path] = cache_name

            # Tarkistetaan onko jo Drivessa
            if cache_name in cached_names or file_hash in cached_md5s:
                if log:
                    log(f"  Välimuistissa: {rel_path} (ohitetaan siirto)")
                continue

            file_size_mb = file_path.stat().st_size / (1024 * 1024)
            if log:
                log(f"  Ladataan välimuistiin: {rel_path} ({file_size_mb:.1f} MB)...")

            upload_resumable(
                file_path,
                folder_id=cache_folder_id,
                token=token,
            )

    return manifest


def copy_drive_file(
    file_id: str,
    target_folder_id: str,
    new_name: str,
    token: str = "",
) -> str:
    """Kopioi tiedoston Google Driven sisällä uuteen kansioon uudella nimellä (0 tavua verkkoa)."""
    if not token:
        token = get_drive_token()
    url = f"{DRIVE_FILES_URL}/{file_id}/copy"
    meta = {
        "name": new_name,
        "parents": [target_folder_id],
    }
    body = json.dumps(meta).encode("utf-8")
    req = drive_request(
        url,
        data=body,
        method="POST",
        token=token,
        headers={"Content-Type": "application/json; charset=UTF-8"},
    )
    with urllib.request.urlopen(req) as resp:
        res = json.loads(resp.read().decode("utf-8"))
        return res.get("id", "")


def upload_archive_with_cache(
    input_dir: Path | str,
    session: str,
    token: str = "",
    log: Callable[[str], None] | None = None,
) -> str:
    """Pakkaa syötteen, hyödyntää Google Driven 24 h välimuistia ja valmistelee istunnon tiedoston.

    1. Pakkaa syötteen tilapäiseksi .tar-paketiksi (pakkaamaton, nopea).
    2. Laskee paketin MD5-tarkistussumman.
    3. Siivoaa Drivesta vanhentuneet (> 24 h) välimuistitiedostot.
    4. Jos sama paketti löytyy jo Drive-välimuistista, ohittaa lähetyksen kokonaan ja
       tekee suoran palvelinpuolen kopion istuntokansioon (0 s verkkosiirtoa).
    5. Jos ei löydy, lataa paketin välimuistiin ja kopioi sen istuntokansioon.
    """
    if not token:
        token = get_drive_token()

    source = Path(input_dir)
    if log:
        log(f"Pakataan syötetiedostot ({source.name})...")

    with tempfile.TemporaryDirectory() as tmp_dir:
        archive_path = Path(tmp_dir) / "input.tar"
        create_input_archive(source, archive_path)
        archive_size_mb = archive_path.stat().st_size / (1024 * 1024)
        archive_hash = compute_file_hash(archive_path)

        if log:
            log(f"Valmistellaan Google Drive -välimuistia ({archive_size_mb:.1f} MB)...")

        root_folder_id = ensure_folder("ColabTranscribe", token=token)
        cache_folder_id = ensure_folder("cache", parent_id=root_folder_id, token=token)
        session_folder_id = ensure_folder(session, parent_id=root_folder_id, token=token)

        # 1. 24 h vanhentuneiden siivous
        pruned = prune_expired_cache(cache_folder_id, max_age_seconds=24 * 3600, token=token)
        if pruned and log:
            log(f"  Siivottiin vanhentuneita paketteja välimuistista ({len(pruned)} kpl).")

        # 2. Tarkistetaan löytyykö sama paketti jo välimuistista
        cached_files = list_cache_files(cache_folder_id, token=token)
        cache_file_name = f"{archive_hash}.tar"

        matching_cached = None
        for f in cached_files:
            if f.get("name") == cache_file_name or f.get("md5Checksum") == archive_hash:
                matching_cached = f
                break

        if matching_cached:
            if log:
                log(f"  Välimuistissa: paketti löytyi Google Drivesta ({archive_size_mb:.1f} MB, ohitetaan lähetys).")
            return copy_drive_file(
                matching_cached["id"],
                target_folder_id=session_folder_id,
                new_name="input.tar",
                token=token,
            )

        # 3. Ei löytynyt: ladataan välimuistiin
        last_logged_mb = 0.0

        def on_progress(uploaded: int, total: int) -> None:
            nonlocal last_logged_mb
            up_mb = uploaded / (1024 * 1024)
            tot_mb = total / (1024 * 1024)
            if up_mb - last_logged_mb >= 10.0 or uploaded == total:
                pct = int(uploaded / total * 100) if total else 100
                if log:
                    log(f"  Google Drive -lataus: {up_mb:.1f} / {tot_mb:.1f} MB ({pct}%)")
                last_logged_mb = up_mb

        if log:
            log(f"Ladataan paketti Google Driveen (ColabTranscribe/cache/{cache_file_name})...")

        cached_archive_path = Path(tmp_dir) / cache_file_name
        shutil.copyfile(archive_path, cached_archive_path)

        cached_id = upload_resumable(
            cached_archive_path,
            folder_id=cache_folder_id,
            token=token,
            progress_callback=on_progress,
        )

        if log:
            log("Google Drive -siirto valmis.")

        return copy_drive_file(
            cached_id,
            target_folder_id=session_folder_id,
            new_name="input.tar",
            token=token,
        )


