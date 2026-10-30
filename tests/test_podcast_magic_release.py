"""Ylisuuri Linux-paketti ei estä Mac-julkaisua eikä katoa hiljaa."""

import hashlib
import importlib.util
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LIMIT = 2_147_483_648


@pytest.fixture
def publisher():
    path = ROOT / "scripts/publish_podcast_magic.py"
    assert path.exists(), "Julkaisija puuttuu"
    spec = importlib.util.spec_from_file_location("publisher", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sparse(path, size):
    with path.open("wb") as stream:
        stream.truncate(size)
    return path


@pytest.mark.parametrize("size", [LIMIT - 1, LIMIT, LIMIT + 1])
def test_real_api_boundary_selects_splitting(publisher, tmp_path, monkeypatch, size):
    archive = sparse(tmp_path / "podcast-magic-linux-x86_64.tar.gz", size)
    calls = []

    def split(source, destination):
        calls.append(source)
        return [destination / "part"]

    monkeypatch.setattr(publisher, "split_archive", split)
    assets = publisher.prepare_asset(archive, tmp_path)
    assert calls == ([archive] if size >= LIMIT else [])
    assert assets == ([tmp_path / "part"] if size >= LIMIT else [archive])


def test_split_reassembles_exact_bytes_and_checksums(publisher, tmp_path):
    archive = tmp_path / "podcast-magic-linux-x86_64.tar.gz"
    data = bytes(range(256)) * 5 + b"last bytes"
    archive.write_bytes(data)
    output = tmp_path / "parts"
    output.mkdir()
    assets = publisher.split_archive(archive, output, part_size=512)
    parts = [p for p in assets if ".part" in p.name]
    assert [p.name for p in parts] == [archive.name + f".part{i:04d}" for i in range(3)]
    assert all(0 < p.stat().st_size <= 512 for p in parts)
    assert b"".join(p.read_bytes() for p in parts) == data
    checksums = next(p for p in assets if p.name.endswith(".sha256"))
    for line in checksums.read_text().splitlines():
        digest, name = line.split("  ")
        payload = data if name == archive.name else (output / name).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == digest
    readme = next(p for p in assets if p.name.endswith(".txt")).read_text()
    assert "cat " + " ".join(p.name for p in parts) + " > " + archive.name in readme
    assert f"sha256sum -c {checksums.name}" in readme
    assert "Download all" in readme and "Lataa kaikki" in readme


def test_mac_published_before_oversized_linux_preparation(publisher, tmp_path, monkeypatch):
    mac = sparse(tmp_path / "podcast-magic-macos-arm64.dmg", 10)
    linux = sparse(tmp_path / "podcast-magic-linux-x86_64.tar.gz", LIMIT)
    windows = sparse(tmp_path / "podcast-magic-windows-x86_64.zip", 10)
    notes = tmp_path / "notes.md"
    notes.write_text("Release notes")
    commands = []

    def run(command, **kwargs):
        assert kwargs["check"] is True
        commands.append(command)

    def split(source, destination):
        assert commands[0][:4] == ["gh", "release", "create", "podcast-magic-vTEST"]
        assert str(mac) in commands[0] and str(linux) not in commands[0]
        part = destination / (source.name + ".part0000")
        part.write_bytes(b"part")
        return [part]

    monkeypatch.setattr(publisher.subprocess, "run", run)
    monkeypatch.setattr(publisher, "split_archive", split)
    publisher.publish_macos(tmp_path, notes, "podcast-magic-vTEST", "owner/repo")
    publisher.publish_others(tmp_path, "podcast-magic-vTEST", "owner/repo")
    assert any(str(windows) in c for c in commands[1:])
    assert any(any(".part0000" in arg for arg in c) for c in commands[1:])
    assert all(str(linux) not in c for c in commands)
    assert all("--clobber" not in c and "delete" not in c for c in commands)
    assert "--verify-tag" in commands[0]


@pytest.mark.parametrize("size", [None, 0, LIMIT, LIMIT + 1])
def test_missing_empty_or_oversized_mac_prevents_release(publisher, tmp_path, monkeypatch, size):
    if size is not None:
        sparse(tmp_path / "podcast-magic-macos-arm64.dmg", size)
    monkeypatch.setattr(publisher.subprocess, "run", lambda *a, **kw: pytest.fail("gh ran"))
    with pytest.raises(ValueError, match="macOS"):
        publisher.publish_macos(tmp_path, tmp_path / "notes.md", "tag", "owner/repo")


@pytest.mark.parametrize("stage", ["macos", "others"])
def test_upload_or_existing_release_failure_is_not_suppressed(publisher, tmp_path, monkeypatch, stage):
    for name in ["podcast-magic-macos-arm64.dmg", "podcast-magic-linux-x86_64.tar.gz",
                 "podcast-magic-windows-x86_64.zip"]:
        (tmp_path / name).write_bytes(b"artifact")
    calls = []

    def fail(command, **kwargs):
        calls.append(command)
        raise subprocess.CalledProcessError(1, command, stderr="API rejected operation")

    monkeypatch.setattr(publisher.subprocess, "run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        if stage == "macos":
            publisher.publish_macos(tmp_path, tmp_path / "notes.md", "tag", "owner/repo")
        else:
            publisher.publish_others(tmp_path, "tag", "owner/repo")
    assert len(calls) == 1
    assert "--clobber" not in calls[0]


def test_workflow_publishes_mac_before_downloading_other_platforms():
    text = (ROOT / ".github/workflows/build-podcast-magic.yml").read_text()
    release = text.split("\n  release:\n")[1]
    assert "actions/checkout@v7" in release
    assert release.index("name: podcast-magic-macos") < release.index("--stage macos")
    assert release.index("--stage macos") < release.index("name: podcast-magic-linux")
    assert release.index("name: podcast-magic-windows") < release.index("--stage others")
    assert "continue-on-error" not in release
    assert "dist/podcast-magic-*" not in release


def test_later_upload_failure_leaves_successful_mac_operation(publisher, tmp_path, monkeypatch):
    for name in ["podcast-magic-macos-arm64.dmg", "podcast-magic-linux-x86_64.tar.gz",
                 "podcast-magic-windows-x86_64.zip"]:
        (tmp_path / name).write_bytes(b"artifact")
    successful = []

    def run(command, **kwargs):
        if command[2] == "upload":
            raise subprocess.CalledProcessError(1, command)
        successful.append(command)

    monkeypatch.setattr(publisher.subprocess, "run", run)
    publisher.publish_macos(tmp_path, tmp_path / "notes.md", "tag", "owner/repo")
    with pytest.raises(subprocess.CalledProcessError):
        publisher.publish_others(tmp_path, "tag", "owner/repo")
    assert len(successful) == 1
    assert successful[0][2] == "create"


@pytest.mark.parametrize("size", [512, 1024, 1025])
def test_split_does_not_append_empty_part_at_exact_multiple(publisher, tmp_path, size):
    source = tmp_path / "archive.tar.gz"
    source.write_bytes(b"x" * size)
    assets = publisher.split_archive(source, tmp_path, part_size=512)
    parts = [p for p in assets if ".part" in p.name]
    assert len(parts) == (size + 511) // 512
    assert b"".join(p.read_bytes() for p in parts) == source.read_bytes()
    assert all(p.stat().st_size > 0 for p in parts)


def test_cli_passes_tag_repository_and_mac_notes_to_publisher(publisher, tmp_path, monkeypatch):
    import sys

    mac = tmp_path / "podcast-magic-macos-arm64.dmg"
    mac.write_bytes(b"dmg")
    notes = tmp_path / "notes.md"
    notes.write_text("notes")
    monkeypatch.setattr(sys, "argv", ["publisher", "--stage", "macos", "--dist", str(tmp_path),
                                     "--notes", str(notes), "--tag", "tag", "--repo", "o/r"])
    commands = []
    monkeypatch.setattr(publisher.subprocess, "run", lambda cmd, **kw: commands.append(cmd))
    publisher.main()
    assert commands == [["gh", "release", "create", "tag", str(mac), "--repo", "o/r",
                         "--title", "tag", "--notes-file", str(notes), "--generate-notes",
                         "--verify-tag"]]
