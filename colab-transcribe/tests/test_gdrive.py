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

    archive_path = tmp_path / "input.tar.gz"
    gdrive.create_input_archive(in_dir, archive_path)

    assert archive_path.is_file()
    with tarfile.open(archive_path, "r:gz") as tar:
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

