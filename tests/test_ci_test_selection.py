from __future__ import annotations

from scripts.ci_test_selection import select_suites


def test_app_only_changes_run_that_app_on_supported_platforms():
    selection = select_suites(["apps/automixer/src/automixer/cli.py"])

    assert selection == {
        "linux": ["automixer"],
        "macos": ["automixer"],
    }


def test_shared_library_changes_run_library_and_consumers():
    selection = select_suites(["packages/speechmix/src/speechmix/mix.py"])

    assert selection == {
        "linux": ["automixer", "podcast-magic", "speechmix"],
        "macos": ["automixer", "autoraffkat", "podcast-magic", "speechmix"],
    }


def test_colab_alignment_change_runs_transcriber_and_shared_aligner():
    selection = select_suites(["packages/wordalign/src/wordalign/align.py"])

    assert selection == {
        "linux": ["colab-transcribe", "podcast-magic", "wordalign"],
        "macos": ["podcast-magic"],
    }


def test_workspace_and_ci_contract_changes_run_every_suite():
    selection = select_suites(["uv.lock"])

    assert selection == {"linux": ["all"], "macos": ["all"]}


def test_documentation_only_changes_run_no_member_suites():
    selection = select_suites(["docs/README.md", "CONTRIBUTING.md"])

    assert selection == {"linux": [], "macos": []}


def test_manual_run_selects_every_suite():
    assert select_suites([], full=True) == {
        "linux": ["all"],
        "macos": ["all"],
    }
