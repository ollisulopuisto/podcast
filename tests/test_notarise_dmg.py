"""Notarisation step of build-podcast-magic.yml, run against stubbed Apple tools.

No Mac, Apple account or network: `xcrun`, `spctl` and the credential helper are
stubs that log their calls. Covers the credential gate, accepted and rejected
submissions, and the order of steps around the DMG.
"""
from __future__ import annotations

import os
import re
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/notarise_dmg.sh"
WORKFLOW = ROOT / ".github/workflows/build-podcast-magic.yml"

XCRUN = """#!/usr/bin/env bash
echo "xcrun $*" >> "$STUB_LOG"
case "$1 $2" in
  "notarytool submit") echo "{\\"id\\": \\"abc-123\\", \\"status\\": \\"${STUB_STATUS:-Accepted}\\"}" ;;
  "notarytool log") echo "stub notary log" ;;
esac
exit 0
"""
SPCTL = '#!/usr/bin/env bash\necho "spctl $*" >> "$STUB_LOG"\n'
CREDS = '#!/usr/bin/env python3\nimport os, sys\nopen(os.environ["STUB_LOG"], "a").write("creds " + " ".join(sys.argv[1:]) + "\\n")\n'


def run(status="Accepted", apple_id="id", password="pw", ref_type="tag"):
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        for name, body in (("xcrun", XCRUN), ("spctl", SPCTL), ("creds.py", CREDS)):
            p = d / name
            p.write_text(body)
            p.chmod(p.stat().st_mode | stat.S_IEXEC)
        log = d / "log"
        log.write_text("")
        env = {
            "PATH": f"{d}:{os.environ['PATH']}", "STUB_LOG": str(log), "STUB_STATUS": status,
            "APPLE_ID": apple_id, "APPLE_APP_PASSWORD": password, "APPLE_TEAM_ID": "TEAM",
            "GITHUB_REF_TYPE": ref_type, "RUNNER_TEMP": str(d), "CREDENTIALS_SCRIPT": str(d / "creds.py"),
        }
        proc = subprocess.run(["bash", str(SCRIPT), "dist/Podcast Magic.dmg"], env=env,
                              capture_output=True, text=True)
        return proc, log.read_text().splitlines()


class Notarise(unittest.TestCase):
    def test_accepted_submits_then_staples_then_validates(self):
        proc, calls = run()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        joined = "\n".join(calls)
        self.assertLess(joined.index("notarytool submit"), joined.index("stapler staple"))
        self.assertLess(joined.index("stapler staple"), joined.index("stapler validate"))
        self.assertIn("spctl", joined)
        self.assertIn("creds store-notary-credentials", joined)

    def test_rejected_submission_fails_and_prints_log_without_stapling(self):
        proc, calls = run(status="Invalid")
        self.assertNotEqual(proc.returncode, 0)
        joined = "\n".join(calls)
        self.assertIn("notarytool log", joined)
        self.assertNotIn("stapler", joined)

    def test_tag_build_without_credentials_fails_and_does_not_call_apple(self):
        proc, calls = run(apple_id="", ref_type="tag")
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(calls, [])

    def test_manual_build_without_credentials_warns_and_succeeds(self):
        proc, calls = run(password="", ref_type="branch")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("::warning::", proc.stdout)
        self.assertEqual(calls, [])


class WorkflowOrder(unittest.TestCase):
    def positions(self):
        text = WORKFLOW.read_text()
        def at(marker):
            i = text.find(marker)
            self.assertNotEqual(i, -1, marker)
            return i
        return at

    def test_sign_then_notarise_then_report_then_rename_then_upload(self):
        at = self.positions()
        order = [
            at("- name: Verify macOS app and sign DMG"),
            at("- name: Notarise and staple DMG (macOS)"),
            at("- name: Report what is inside (macOS)"),
            at("- name: Name the package"),
            at("- uses: actions/upload-artifact"),
        ]
        self.assertEqual(order, sorted(order))

    def test_notarise_step_is_macos_only_and_calls_the_script(self):
        text = WORKFLOW.read_text()
        step = re.search(r"- name: Notarise and staple DMG \(macOS\)\n(.*?)\n      (?:#|- )", text, re.S).group(1)
        self.assertIn("matrix.platform == 'macos'", step)
        self.assertIn("scripts/notarise_dmg.sh", step)
        self.assertIn("secrets.APPLE_ID", step)

    def test_notarises_before_the_dmg_is_renamed(self):
        text = WORKFLOW.read_text()
        self.assertIn('"dist/Podcast Magic.dmg"', text.split("- name: Name the package")[0].split("Notarise and staple DMG (macOS)")[1])


if __name__ == "__main__":
    unittest.main()
