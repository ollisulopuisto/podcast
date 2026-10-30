"""Exercise the workflow's real selector without GitHub or workspace dependencies."""
from __future__ import annotations

import json
import os
import re
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/build-cli.yml"


def select(paths=(), event="pull_request", ref="149/merge", requested=""):
    source = WORKFLOW.read_text()
    match = re.search(r"          python - <<'PY'\n(.*?)\n          PY", source, re.S)
    assert match, "real workflow selector missing"
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / "outputs"
        environment = {
            "EVENT_NAME": event, "REF_NAME": ref, "BASE_REF": "main",
            "REQUESTED_APP": requested, "GITHUB_OUTPUT": str(output),
        }
        with patch.dict(os.environ, environment), patch("subprocess.run") as fetch, patch(
            "subprocess.check_output", return_value="\n".join(paths)
        ):
            exec(compile(textwrap.dedent(match[1]), str(WORKFLOW), "exec"), {})
        if event == "pull_request":
            fetch.assert_called_once_with(["git", "fetch", "origin", "main"], check=True)
        return json.loads(output.read_text().removeprefix("matrix="))


class WorkflowSelectionTests(unittest.TestCase):
    def test_empty_selection_has_job_guard_before_matrix_expansion(self):
        build = WORKFLOW.read_text().split("\n  build:\n", 1)[1].split("\n  release:", 1)[0]
        guard = "    if: needs.select.outputs.apps != '[]'"
        self.assertIn(guard, build)
        self.assertLess(build.index(guard), build.index("    strategy:"))
        self.assertIn("app: ${{ fromJSON(needs.select.outputs.apps) }}", build)

    def test_unrelated_changes_select_no_dummy_cli(self):
        for paths in [("apps/podcast-magic/pyproject.toml",), ("docs/README.md",), ()]:
            with self.subTest(paths=paths):
                self.assertEqual(select(paths), [])

    def test_affected_apps_still_run_their_real_checks(self):
        fixtures = [
            (("apps/automixer/src/app.py",), ["automixer"]),
            (("packages/speechmix/src/chain.py",), ["automixer"]),
            (("colab-transcribe/src/cli.py",), ["colab-transcribe"]),
            (("packages/wordalign/src/align.py",), ["colab-transcribe"]),
            (("uv.lock",), ["automixer", "colab-transcribe"]),
            ((".github/workflows/build-cli.yml",), ["automixer", "colab-transcribe"]),
            (("tests/test_cli_workflow_selection.py",), ["automixer", "colab-transcribe"]),
        ]
        for paths, expected in fixtures:
            with self.subTest(paths=paths):
                self.assertEqual(select(paths), expected)

    def test_release_tags_and_manual_selection_stay_nonempty(self):
        for ref, expected in [("automixer-v2026.10.30.1", "automixer"),
                              ("colab-transcribe-v2026.10.30.1", "colab-transcribe")]:
            with self.subTest(ref=ref):
                self.assertEqual(select(event="push", ref=ref), [expected])
        self.assertEqual(select(event="workflow_dispatch", requested="all"),
                         ["automixer", "colab-transcribe"])
        self.assertEqual(select(event="workflow_dispatch", requested="automixer"), ["automixer"])


if __name__ == "__main__":
    unittest.main()
