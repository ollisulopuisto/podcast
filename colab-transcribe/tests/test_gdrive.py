"""Google Drive -integraation yksikkötestit.

Testaa tokenin haun, väliaikaisen paketin luonnin, kansioiden hallinnan
sekä resumable upload -protokollan ilman oikeita verkkoyhteyksiä.
"""

from __future__ import annotations

import io
import json
import tarfile
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

from colabtranscribe import gdrive


def test_get_drive_token_from_colab_cli_config(tmp_path: Path):
    fake_token = {
        "access_token": "ya29.test-access-token",
        "refresh_token": "1//test-refresh-token",
        "client_id": "test-client-id",
        "client_secret": "test-client-secret",
    }
    token_file = tmp_path / "token.json"
    token_file.write_text(json.dumps(fake_token), encoding="utf-8")

    with patch("colabtranscribe.gdrive.COLAB_TOKEN_PATH", token_file):
        token = gdrive.get_drive_token()
        assert token == "ya29.test-access-token"


def test_get_drive_token_refreshes_when_needed(tmp_path: Path):
    fake_token = {
        "refresh_token": "1//test-refresh-token",
        "client_id": "test-client-id",
        "client_secret": "test-client-secret",
    }
    token_file = tmp_path / "token.json"
    token_file.write_text(json.dumps(fake_token), encoding="utf-8")

    fake_response = io.BytesIO(
        json.dumps({"access_token": "ya29.refreshed-token"}).encode("utf-8")
    )
    fake_urlopen = MagicMock()
    fake_urlopen.return_value.__enter__.return_value = fake_response

    with (
        patch("colabtranscribe.gdrive.COLAB_TOKEN_PATH", token_file),
        patch("urllib.request.urlopen", fake_urlopen),
    ):
        token = gdrive.get_drive_token()
        assert token == "ya29.refreshed-token"


def test_create_input_archive_excludes_hidden(tmp_path: Path):
    in_dir = tmp_path / "input"
    in_dir.mkdir()
    (in_dir / "audio.wav").write_bytes(b"RIFFtest")
    (in_dir / "project.nhsx").write_text("<Session/>", encoding="utf-8")
    (in_dir / ".DS_Store").write_bytes(b"junk")
    (in_dir / "sub").mkdir()
    (in_dir / "sub" / "track.wav").write_bytes(b"RIFFtrack")

    archive_path = tmp_path / "input.tar"
    gdrive.create_input_archive(in_dir, archive_path)

    assert archive_path.is_file()
    with tarfile.open(archive_path, "r") as tar:
        names = sorted(tar.getnames())
        assert "audio.wav" in names
        assert "project.nhsx" in names
        assert "sub/track.wav" in names
        assert ".DS_Store" not in names


def test_ensure_folder_finds_existing():
    token = "test-token"
    mock_urlopen = MagicMock()

    # Google Drive v3 list response: kansio löytyy
    list_response = io.BytesIO(
        json.dumps({
            "files": [{"id": "folder-123", "name": "ColabTranscribe"}]
        }).encode("utf-8")
    )
    mock_urlopen.return_value.__enter__.return_value = list_response

    with patch("urllib.request.urlopen", mock_urlopen):
        folder_id = gdrive.ensure_folder("ColabTranscribe", token=token)
        assert folder_id == "folder-123"


def test_ensure_folder_creates_if_not_found():
    token = "test-token"
    mock_urlopen = MagicMock()

    # 1. haku: ei löydy
    empty_list = io.BytesIO(json.dumps({"files": []}).encode("utf-8"))
    # 2. luonti: uusi kansio luotu
    created = io.BytesIO(
        json.dumps({"id": "folder-new-456", "name": "ColabTranscribe"}).encode("utf-8")
    )

    mock_urlopen.return_value.__enter__.side_effect = [empty_list, created]

    with patch("urllib.request.urlopen", mock_urlopen):
        folder_id = gdrive.ensure_folder("ColabTranscribe", token=token)
        assert folder_id == "folder-new-456"


def test_resumable_upload_file(tmp_path: Path):
    token = "test-token"
    test_file = tmp_path / "payload.tar.gz"
    test_file.write_bytes(b"A" * 1024)  # 1 KB

    mock_urlopen = MagicMock()

    # 1. Aloitus: palauttaa Location-otsakkeen
    init_resp = MagicMock()
    init_resp.__enter__.return_value = init_resp
    init_resp.headers = {"Location": "https://www.googleapis.com/upload/drive/v3/files?upload_id=abc"}
    init_resp.status = 200

    # 2. Ensimmäinen chunk (512 B): palauttaa 308 Resume Incomplete
    chunk1_err = urllib.error.HTTPError(
        url="https://www.googleapis.com/upload/drive/v3/files?upload_id=abc",
        code=308,
        msg="Resume Incomplete",
        hdrs={"Range": "bytes=0-511"},
        fp=io.BytesIO(b""),
    )

    # 3. Toinen chunk (512 B): palauttaa 200 OK ja tiedoston tiedot
    chunk2_resp = MagicMock()
    chunk2_resp.__enter__.return_value = chunk2_resp
    chunk2_resp.read.return_value = json.dumps({"id": "file-999"}).encode("utf-8")
    chunk2_resp.status = 200

    mock_urlopen.side_effect = [
        init_resp,
        chunk1_err,
        chunk2_resp,
    ]

    progress_reports = []

    def on_progress(uploaded: int, total: int):
        progress_reports.append((uploaded, total))

    with patch("urllib.request.urlopen", mock_urlopen):
        file_id = gdrive.upload_resumable(
            test_file,
            folder_id="folder-123",
            token=token,
            chunk_size=512,
            progress_callback=on_progress,
        )
        assert file_id == "file-999"
        assert len(progress_reports) == 2
        assert progress_reports[0] == (512, 1024)
        assert progress_reports[1] == (1024, 1024)


def test_delete_file_or_folder():
    token = "test-token"
    mock_urlopen = MagicMock()
    with patch("urllib.request.urlopen", mock_urlopen):
        gdrive.delete_file_or_folder("file-123", token=token)
        assert mock_urlopen.called
        req = mock_urlopen.call_args[0][0]
        assert req.get_method() == "DELETE"
        assert req.full_url == f"{gdrive.DRIVE_FILES_URL}/file-123"


def test_compute_file_hash(tmp_path: Path):
    sample = tmp_path / "sample.wav"
    sample.write_bytes(b"HELLO-PODCAST-AUDIO-BYTES")
    digest = gdrive.compute_file_hash(sample)
    assert isinstance(digest, str)
    assert len(digest) == 32  # MD5 hex length


def test_prune_expired_cache():
    token = "test-token"
    # Kaksi tiedostoa välimuistissa: toinen vanha (48 h), toinen tuore (2 h)
    fake_files = [
        {
            "id": "old-file-1",
            "name": "hash1_old.wav",
            "createdTime": "2026-09-09T10:00:00.000Z",  # yli 24 h sitten
        },
        {
            "id": "new-file-2",
            "name": "hash2_new.wav",
            "createdTime": "2026-09-11T15:00:00.000Z",  # tuore
        },
    ]

    mock_urlopen = MagicMock()
    list_resp = io.BytesIO(json.dumps({"files": fake_files}).encode("utf-8"))
    delete_resp = MagicMock()
    delete_resp.status = 204

    mock_urlopen.return_value.__enter__.side_effect = [list_resp, delete_resp]

    # Kiinnitetään nykyhetki: 2026-09-11T16:00:00+00:00
    now_ts = 1789142400.0  # Kiinteä timestamp
    with patch("urllib.request.urlopen", mock_urlopen):
        deleted = gdrive.prune_expired_cache(
            "cache-folder-id",
            max_age_seconds=24 * 3600,
            token=token,
            current_time=now_ts,
        )
    # Vain vanha tiedosto pitää poistaa
    assert deleted == ["old-file-1"]


def test_sync_input_to_cache_skips_existing(tmp_path: Path):
    in_dir = tmp_path / "input"
    in_dir.mkdir()
    f1 = in_dir / "audio.wav"
    f1.write_bytes(b"cached-content")
    f1_hash = gdrive.compute_file_hash(f1)

    token = "test-token"
    # Google Drivessa on jo tiedosto samalla hashilla
    existing_cache = [
        {
            "id": "drive-file-100",
            "name": f"{f1_hash}_audio.wav",
            "md5Checksum": f1_hash,
            "createdTime": "2026-09-11T15:00:00.000Z",
        }
    ]

    def fake_urlopen(req):
        resp = MagicMock()
        resp.read.return_value = json.dumps({"files": existing_cache}).encode("utf-8")
        resp.__enter__.return_value = resp
        return resp

    mock_urlopen = MagicMock(side_effect=fake_urlopen)
    logs = []
    with patch("urllib.request.urlopen", mock_urlopen):
        manifest = gdrive.sync_input_to_cache(
            in_dir,
            cache_folder_id="cache-folder-id",
            token=token,
            log=logs.append,
        )

    assert "audio.wav" in manifest
    assert manifest["audio.wav"] == f"{f1_hash}_audio.wav"
    assert any("Välimuistissa" in line for line in logs)


def test_copy_drive_file():
    token = "test-token"
    mock_urlopen = MagicMock()
    copy_resp = MagicMock()
    copy_resp.read.return_value = json.dumps({"id": "copied-file-id"}).encode("utf-8")
    copy_resp.status = 200
    mock_urlopen.return_value.__enter__.return_value = copy_resp

    with patch("urllib.request.urlopen", mock_urlopen):
        new_id = gdrive.copy_drive_file(
            "orig-file-id",
            target_folder_id="target-folder-123",
            new_name="input.tar",
            token=token,
        )
        assert new_id == "copied-file-id"
        req = mock_urlopen.call_args[0][0]
        assert req.get_method() == "POST"
        assert req.full_url == f"{gdrive.DRIVE_FILES_URL}/orig-file-id/copy"


def test_upload_archive_with_cache_skips_when_cached(tmp_path: Path):
    in_dir = tmp_path / "input"
    in_dir.mkdir()
    (in_dir / "a.wav").write_bytes(b"content")

    token = "test-token"
    with (
        patch("colabtranscribe.gdrive.get_drive_token", return_value=token),
        patch("colabtranscribe.gdrive.ensure_folder", side_effect=["root-id", "cache-id", "sess-id"]),
        patch("colabtranscribe.gdrive.prune_expired_cache") as mock_prune,
        patch("colabtranscribe.gdrive.list_cache_files") as mock_list,
        patch("colabtranscribe.gdrive.upload_resumable") as mock_upload,
        patch("colabtranscribe.gdrive.copy_drive_file", return_value="sess-tar-id") as mock_copy,
    ):
        # Simuloidaan että arkiston tiiviste löytyy jo välimuistista
        def fake_list(cache_id, token=""):
            return [{"id": "cached-tar-id", "name": "input.tar", "md5Checksum": "DUMMY"}]

        mock_list.side_effect = fake_list

        # Pakotetaan sama hash listaan
        with patch("colabtranscribe.gdrive.compute_file_hash", return_value="DUMMY"):
            logs = []
            file_id = gdrive.upload_archive_with_cache(in_dir, "vst-sess", log=logs.append)
            assert file_id == "sess-tar-id"
            mock_prune.assert_called_once()
            mock_copy.assert_called_once_with(
                "cached-tar-id",
                target_folder_id="sess-id",
                new_name="input.tar",
                token=token,
            )
            # Uutta latausta EI saa tapahtua!
            mock_upload.assert_not_called()
            assert any("Välimuistissa" in line for line in logs)


def test_drive_requests_include_quota_project_header(monkeypatch):
    monkeypatch.setenv("COLAB_QUOTA_PROJECT", "my-custom-quota-proj")
    mock_urlopen = MagicMock()
    mock_urlopen.return_value.__enter__.return_value = io.BytesIO(b'{"files": []}')

    with patch("urllib.request.urlopen", mock_urlopen):
        gdrive.list_cache_files("folder123", token="tok123")
        req = mock_urlopen.call_args[0][0]
        assert req.get_header("X-goog-user-project") == "my-custom-quota-proj"




