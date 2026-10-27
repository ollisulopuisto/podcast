"""Install a verified CLI release into a new, dedicated virtual environment."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
from pathlib import Path


def verify_bundle(bundle: Path) -> dict:
    manifest = json.loads((bundle / "manifest.json").read_text())
    if (manifest["platform"], manifest["machine"]) != (
        platform.system().lower(), platform.machine().lower()
    ):
        raise ValueError("This bundle was tested on a different platform/architecture")
    for name, expected in manifest["sha256"].items():
        if Path(name).name != name:
            raise ValueError(f"Invalid bundle path: {name}")
        path = bundle / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"Bundle checksum mismatch: {name}")
    return manifest


def install(bundle: Path, target: Path):
    bundle, target = bundle.resolve(), target.expanduser().resolve()
    manifest = verify_bundle(bundle)
    if target.exists():
        raise ValueError(f"Environment already exists: {target}; choose a new directory")
    subprocess.run(["uv", "venv", "--python", manifest["python"], str(target)], check=True)
    python = target / "bin" / "python"
    subprocess.run(
        ["uv", "pip", "sync", "--python", str(python), "requirements.txt"],
        cwd=bundle, check=True,
    )
    subprocess.run(["uv", "pip", "check", "--python", str(python)], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--venv", required=True, type=Path)
    args = parser.parse_args()
    try:
        install(Path(__file__).resolve().parent, args.venv)
    except ValueError as error:
        parser.exit(1, f"{error}\n")
    print(f"Installed. Commands are in {args.venv.expanduser().resolve() / 'bin'}")


if __name__ == "__main__":
    main()
