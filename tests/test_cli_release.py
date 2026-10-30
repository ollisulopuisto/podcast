"""Julkaisun pitää asentua ilman työtilaa, samoilla kirjastoilla kuin sovellus."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import platform
import tarfile
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_colab_pins_the_kernel_client_version_required_by_its_cli():
    project = tomllib.loads((ROOT / "colab-transcribe/pyproject.toml").read_text())
    # The pinned Google CLI requires 0.9.0. The former Google fork is 0.8.0;
    # uv's direct URL resolution accepted it but a fresh `uv pip check` failed.
    dependency = next(d for d in project["project"]["dependencies"]
                      if d.startswith("jupyter-kernel-client"))
    assert "jupyter_kernel_client-0.9.0-py3-none-any.whl#sha256=" in dependency
    assert dependency.startswith("jupyter-kernel-client @ https://files.pythonhosted.org/")
    workspace = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert dependency in workspace["tool"]["uv"].get("override-dependencies", [])


def test_colab_declares_the_xml_parser_imported_at_cli_startup():
    project = tomllib.loads((ROOT / "colab-transcribe/pyproject.toml").read_text())
    assert "lxml>=6.1.3" in project["project"]["dependencies"]


def load_script(name):
    path = ROOT / "scripts" / f"{name}.py"
    assert path.exists(), f"Missing release tool: {path.name}"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("app", "expected"),
    [
        ("automixer", {"automixer", "speechmix", "nhsx"}),
        ("colab-transcribe", {"colab-transcribe", "silencelearn", "wordalign"}),
    ],
)
def test_bundle_contains_the_transitive_workspace_dependencies(app, expected):
    builder = load_script("build_cli_release")
    assert set(builder.workspace_closure(ROOT, app)) == expected


def test_dependency_discovery_follows_a_new_nested_workspace_library(tmp_path):
    builder = load_script("build_cli_release")
    for name, dependency in [("app", "middle"), ("middle", "leaf"), ("leaf", None)]:
        member = tmp_path / "packages" / name
        member.mkdir(parents=True)
        text = f'[project]\nname = "{name}"\nversion = "2026.1.1.1"\n'
        if dependency:
            text += f'dependencies = ["{dependency}"]\n'
            text += f'[tool.uv.sources]\n{dependency} = {{ workspace = true }}\n'
        (member / "pyproject.toml").write_text(text)
    assert set(builder.workspace_closure(tmp_path, "app")) == {"app", "middle", "leaf"}


def test_a_tag_for_another_version_is_rejected_before_building(tmp_path, monkeypatch):
    builder = load_script("build_cli_release")
    monkeypatch.setattr(builder.subprocess, "run", lambda *a, **kw: pytest.fail("ran uv"))
    with pytest.raises(ValueError, match="tag"):
        builder.build_bundle(ROOT, "automixer", tmp_path, tag="automixer-v1900.1.1.1")


def test_release_is_portable_and_records_the_commit(tmp_path, monkeypatch):
    builder = load_script("build_cli_release")

    def run(command, **kwargs):
        if command[:2] == ["git", "rev-parse"]:
            return type("Result", (), {"stdout": "a" * 40 + "\n"})()
        if command[:2] == ["uv", "build"]:
            name = command[command.index("--package") + 1]
            output = Path(command[command.index("--out-dir") + 1])
            (output / f"{name.replace('-', '_')}-2026.1.1.1-py3-none-any.whl").write_bytes(
                name.encode()
            )
        elif command[:2] == ["uv", "export"]:
            output = Path(command[command.index("--output-file") + 1])
            output.write_text("numpy==2.5.4\n")
            assert "--locked" in command
            assert "--no-emit-workspace" in command
        else:
            pytest.fail(f"Unexpected command: {command}")
        return None

    monkeypatch.setattr(builder.subprocess, "run", run)
    archive = builder.build_bundle(ROOT, "automixer", tmp_path)
    with tarfile.open(archive) as bundle:
        files = {p.name: bundle.extractfile(p).read() for p in bundle if p.isfile()}
    manifest = json.loads(files["manifest.json"])
    assert manifest["commit"] == "a" * 40
    assert manifest["app"] == "automixer"
    requirements = files["requirements.txt"].decode()
    assert "numpy==2.5.4" in requirements
    assert str(tmp_path) not in requirements
    for wheel in [name for name in files if name.endswith(".whl")]:
        assert f"./{wheel}" in requirements
        assert manifest["sha256"][wheel] == hashlib.sha256(files[wheel]).hexdigest()
    assert "install.py" in files


def fixture_bundle(tmp_path):
    (tmp_path / "requirements.txt").write_text("numpy==2.5.4\n")
    manifest = {
        "platform": platform.system().lower(),
        "machine": platform.machine().lower(),
        "python": "3.13",
        "sha256": {
            "requirements.txt": hashlib.sha256(
                (tmp_path / "requirements.txt").read_bytes()
            ).hexdigest(),
        },
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    return manifest


def test_installer_rejects_a_changed_requirement_before_creating_environment(tmp_path):
    installer = load_script("install_cli_release")
    fixture_bundle(tmp_path)
    (tmp_path / "requirements.txt").write_text("untrusted-package\n")
    with pytest.raises(ValueError, match="checksum"):
        installer.verify_bundle(tmp_path)


def test_installer_rejects_another_platform(tmp_path):
    installer = load_script("install_cli_release")
    manifest = fixture_bundle(tmp_path)
    manifest["machine"] = "some-other-architecture"
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="platform"):
        installer.verify_bundle(tmp_path)


def test_installer_uses_bundle_paths_and_a_fresh_environment(tmp_path, monkeypatch):
    installer = load_script("install_cli_release")
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    fixture_bundle(bundle)
    commands = []
    monkeypatch.setattr(
        installer.subprocess, "run", lambda cmd, **kwargs: commands.append((cmd, kwargs))
    )
    target = tmp_path / "installed"
    installer.install(bundle, target)
    assert commands[0][0] == ["uv", "venv", "--python", "3.13", str(target)]
    assert commands[1][0][:3] == ["uv", "pip", "sync"]
    assert commands[1][1]["cwd"] == bundle
    assert commands[-1][0][:3] == ["uv", "pip", "check"]
    target.mkdir()
    with pytest.raises(ValueError, match="exists"):
        installer.install(bundle, target)


def test_tag_publication_waits_for_all_platform_builds():
    workflow = ROOT / ".github/workflows/build-cli.yml"
    assert workflow.is_file(), "CLI releases have no workflow"
    text = workflow.read_text()
    assert '"automixer-v*"' in text and '"colab-transcribe-v*"' in text
    assert "pull_request:" in text
    assert "needs: [select, build]" in text
    assert "if: startsWith(github.ref, 'refs/tags/')" in text
    assert "ubuntu-latest" in text and "macos-15" in text
    assert "--locked" in text
    assert "continue-on-error" not in text
    assert "scripts/smoke_cli_release.py" in text
