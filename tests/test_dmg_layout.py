"""Collect stdlib DMG contracts in the existing workspace CI suite."""

import importlib.util
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "packaging/dmg/test_layout.py"
spec = importlib.util.spec_from_file_location("dmg_contracts", PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
Contract = module.Contract
CaptureContract = module.CaptureContract


class CustomBundleNames(__import__("unittest").TestCase):
    def test_both_packagers_forward_copied_app_name(self):
        import tempfile
        from unittest import mock

        root = Path(__file__).resolve().parents[1]
        for slug in ("autoraffkat", "podcast-magic"):
            with self.subTest(app=slug), tempfile.TemporaryDirectory() as td:
                path = root / "apps" / slug / "scripts/make_dmg.py"
                loader = importlib.util.spec_from_file_location(
                    slug.replace("-", "_"), path
                )
                packager = importlib.util.module_from_spec(loader)
                loader.loader.exec_module(packager)
                app = Path(td) / "Preview.app"
                app.mkdir()
                output = Path(td) / "Preview.dmg"
                commands = []

                def fake_run(command):
                    commands.append(command)
                    if command[0] == "hdiutil":
                        output.write_bytes(b"fixture")

                with (
                    mock.patch.object(packager.sys, "platform", "darwin"),
                    mock.patch.object(packager, "_run", fake_run),
                ):
                    self.assertEqual(packager.make_dmg(app, output), 0)
                styling = [
                    c for c in commands if len(c) > 1 and c[1].endswith("/restyle.py")
                ]
                self.assertEqual(len(styling), 1)
                self.assertEqual(styling[0][3], "Preview.app")
