"""Kohdistimen asennus käyttää ladattavan yhden tiedoston samoja pinnejä."""

from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
ALIGN = ROOT / "packages/wordalign/src/wordalign.py"
PIPELINE = ROOT / "colab-transcribe/src/colabtranscribe/colab/pipeline.py"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AlignerPackagesContract(unittest.TestCase):
    def test_pip_argv_and_install_hint_follow_the_shared_tuple(self):
        align = load("wordalign", ALIGN)
        self.assertEqual(align.INSTALL, "pip install " + " ".join(align.ALIGN_PACKAGES))
        pipeline = load("align_contract_pipeline", PIPELINE)
        with patch.dict(sys.modules, {"wordalign": align}):
            with patch.object(pipeline.subprocess, "run") as run:
                pipeline.install_aligner()
            run.assert_called_once_with(
                ["pip", "install", "-q", "--target", pipeline.ALIGN_SITE, *align.ALIGN_PACKAGES],
                check=True,
                timeout=pipeline.ALIGN_PIP_TIMEOUT,
            )
            # Eri arvot todistavat, ettei asentimessa ole omaa kovakoodattua kopiota.
            with patch.object(align, "ALIGN_PACKAGES", ("torch==0.0.1", "torchaudio==0.0.2")):
                with patch.object(pipeline.subprocess, "run") as run:
                    pipeline.install_aligner()
                self.assertEqual(run.call_args.args[0][-2:], list(align.ALIGN_PACKAGES))

    def test_install_hint_is_derived_when_tuple_changes(self):
        source = ALIGN.read_text()
        tree = ast.parse(source)
        assignments = [node for node in tree.body if isinstance(node, ast.Assign)
                       and any(isinstance(target, ast.Name) and target.id == "ALIGN_PACKAGES"
                               for target in node.targets)]
        self.assertEqual(len(assignments), 1)
        assignments[0].value = ast.Tuple(
            elts=[ast.Constant("torch==0.0.1"), ast.Constant("torchaudio==0.0.2")],
            ctx=ast.Load(),
        )
        source = ast.unparse(ast.fix_missing_locations(tree))
        with tempfile.TemporaryDirectory() as folder:
            changed = Path(folder) / "wordalign.py"
            changed.write_text(source)
            align = load("changed_wordalign", changed)
        self.assertEqual(align.INSTALL, "pip install " + " ".join(align.ALIGN_PACKAGES))
        self.assertIn("torch==0.0.1", align.INSTALL)

    def test_unaligned_remote_script_never_imports_wordalign(self):
        # Vastaa etäkonetta: vain pipeline.py, ei työtilaa eikä wordalign.py:tä.
        with tempfile.TemporaryDirectory() as folder:
            script = Path(folder) / "pipeline.py"
            script.write_bytes(PIPELINE.read_bytes())
            code = '''
import builtins, runpy, sys
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name == "wordalign":
        raise AssertionError("unaligned run imported wordalign")
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
scope = runpy.run_path(sys.argv[1])
seen = []
scope["os"].makedirs = lambda *a, **k: None
scope["main"].__globals__["install_dependencies"] = lambda *a, **k: None
scope["main"].__globals__["run_audio"] = lambda *a, **k: seen.append(k)
sys.argv = [sys.argv[1], "--source", "audio"]
scope["main"]()
assert seen == [{"align": False}], seen
'''
            result = subprocess.run(
                [sys.executable, "-I", "-c", code, str(script)],
                cwd=folder,
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

if __name__ == "__main__":
    unittest.main()
