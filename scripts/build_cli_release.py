"""Build a CLI and its workspace libraries from one commit into a pinned bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import tarfile
import tempfile
import tomllib
from pathlib import Path

APPS = ("automixer", "colab-transcribe")


def workspace_closure(root: Path, app: str) -> dict[str, Path]:
    members = {}
    for pattern in ("apps/*/pyproject.toml", "packages/*/pyproject.toml", "*/pyproject.toml"):
        for path in root.glob(pattern):
            data = tomllib.loads(path.read_text())
            members[data["project"]["name"]] = (path.parent, data)
    result = {}

    def visit(name):
        if name in result:
            return
        member, data = members[name]
        result[name] = member
        for dependency, source in data.get("tool", {}).get("uv", {}).get("sources", {}).items():
            if isinstance(source, dict) and source.get("workspace"):
                visit(dependency)

    visit(app)
    return result


def build_bundle(root: Path, app: str, output: Path, *, tag: str = "") -> Path:
    members = workspace_closure(root, app)
    metadata = {
        name: tomllib.loads((member / "pyproject.toml").read_text())["project"]
        for name, member in members.items()
    }
    version = metadata[app]["version"]
    if tag and tag != f"{app}-v{version}":
        raise ValueError(f"Release tag {tag!r} must match {app}-v{version}")
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, text=True, capture_output=True
    ).stdout.strip()
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    system, machine = platform.system().lower(), platform.machine().lower()
    name = f"{app}-{version}-{system}-{machine}"
    with tempfile.TemporaryDirectory(prefix="cli-release-", dir=output) as temporary:
        bundle = Path(temporary)
        for member in members:
            subprocess.run(
                ["uv", "build", "--package", member, "--wheel", "--no-sources",
                 "--out-dir", str(bundle)],
                cwd=root, check=True,
            )
        requirements = bundle / "requirements.txt"
        subprocess.run(
            ["uv", "export", "--locked", "--package", app, "--no-dev",
             "--no-emit-workspace", "--no-hashes", "--no-header", "--no-annotate",
             "--output-file", str(requirements)],
            cwd=root, check=True,
        )
        wheels = sorted(bundle.glob("*.whl"))
        if len(wheels) != len(members):
            raise ValueError("Expected one wheel for every workspace member")
        with requirements.open("a") as stream:
            for wheel in wheels:
                stream.write(f"\n./{wheel.name}\n")
        shutil.copyfile(root / "scripts" / "install_cli_release.py", bundle / "install.py")
        manifest = {
            "app": app, "version": version, "commit": commit, "tag": tag,
            "platform": system, "machine": machine,
            "python": (root / ".python-version").read_text().strip(),
            "packages": {name: project["version"] for name, project in metadata.items()},
            "sha256": {
                path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(bundle.iterdir()) if path.is_file()
            },
        }
        (bundle / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        archive = output / f"{name}.tar.gz"
        with tarfile.open(archive, "w:gz") as stream:
            for path in sorted(bundle.iterdir()):
                if path.is_file():
                    stream.add(path, arcname=path.name)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(archive.suffix + ".sha256").write_text(f"{digest}  {archive.name}\n")
    return archive


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app", choices=APPS)
    parser.add_argument("--output", type=Path, default=Path("dist"))
    parser.add_argument("--tag", default="")
    args = parser.parse_args()
    try:
        print(build_bundle(Path(__file__).resolve().parents[1], args.app,
                           args.output, tag=args.tag))
    except ValueError as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
