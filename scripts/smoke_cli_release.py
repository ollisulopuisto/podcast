"""Run with the installed Python in isolated mode, outside the checkout."""

from __future__ import annotations

import importlib
import importlib.metadata
import json
import subprocess
import sys
from pathlib import Path


def main():
    manifest = json.loads(Path(sys.argv[1]).read_text())
    prefix = Path(sys.prefix).resolve()
    for name, version in manifest["packages"].items():
        distribution = importlib.metadata.distribution(name)
        assert distribution.version == version, (name, distribution.version, version)
        assert distribution.locate_file("").resolve().is_relative_to(prefix), name
        module = importlib.import_module(name.replace("colab-transcribe", "colabtranscribe"))
        assert Path(module.__file__).resolve().is_relative_to(prefix), module.__file__
    if manifest["app"] == "automixer":
        importlib.import_module("automixer.stems_mix")
    else:
        driver = importlib.import_module("colabtranscribe.driver")
        for path in (driver.PIPELINE_SCRIPT, driver.LEARN_MODULE, driver.ALIGN_MODULE):
            assert path.is_file() and path.resolve().is_relative_to(prefix), path
        # The Colab CLI is a pinned Git dependency; it must ship its entry point too.
        assert (prefix / "bin" / "colab").is_file()
    subprocess.run([str(prefix / "bin" / manifest["app"]), "--help"], check=True)
    print(f"Installed {manifest['app']} {manifest['version']} from {manifest['commit']}")


if __name__ == "__main__":
    main()
