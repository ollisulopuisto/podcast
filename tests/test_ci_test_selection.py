from __future__ import annotations

import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
select_suites = runpy.run_path(str(ROOT / "scripts/ci_test_selection.py"))["select_suites"]


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


def test_lock_only_automixer_version_and_private_dependency_select_no_other_apps():
    choose = runpy.run_path(str(ROOT / 'scripts/ci_test_selection.py'))['select_lock_suites']
    before = {'version': 1, 'package': [
        {'name': 'automixer', 'version': '1', 'source': {'editable': 'apps/automixer'}, 'dependencies': [{'name': 'watchdog'}]},
        {'name': 'watchdog', 'version': '6'},
        {'name': 'autoraffkat', 'version': '1', 'source': {'editable': 'apps/autoraffkat'}},
    ]}
    import copy
    after = copy.deepcopy(before)
    after['package'][0]['version'] = '2'
    after['package'][1]['version'] = '7'
    assert choose(before, after) == {'linux': ['automixer'], 'macos': ['automixer']}


def test_lock_shared_transitive_change_runs_every_consumer_before_and_after():
    choose = runpy.run_path(str(ROOT / 'scripts/ci_test_selection.py'))['select_lock_suites']
    before = {'version': 1, 'package': [
        {'name': 'speechmix', 'source': {'editable': 'packages/speechmix'}, 'dependencies': [{'name': 'numpy'}]},
        {'name': 'automixer', 'source': {'editable': 'apps/automixer'}, 'dependencies': [{'name': 'speechmix'}]},
        {'name': 'numpy', 'version': '1'},
    ]}
    import copy
    after = copy.deepcopy(before)
    after['package'][2]['version'] = '2'
    assert choose(before, after) == {
        'linux': ['automixer', 'podcast-magic', 'speechmix'],
        'macos': ['automixer', 'autoraffkat', 'podcast-magic', 'speechmix'],
    }


def test_lock_unknown_or_resolution_change_fails_closed():
    choose = runpy.run_path(str(ROOT / 'scripts/ci_test_selection.py'))['select_lock_suites']
    assert choose({'package': []}, {'package': [{'name': 'unknown'}]}) == {'linux': ['all'], 'macos': ['all']}
    assert choose({'package': [], 'revision': 1}, {'package': [], 'revision': 2}) == {'linux': ['all'], 'macos': ['all']}


def test_macos_jobs_are_isolated_and_aggregate_rejects_failure():
    workflow = (ROOT / '.github/workflows/tests.yml').read_text()
    for name in ('automixer', 'autoraffkat', 'podcast-magic', 'speechmix'):
        assert f'\n  {name}:\n' in workflow
    assert '--all-packages' not in workflow
    assert 'always()' in workflow
    assert "needs.select.result == 'success'" in workflow
    assert 'failure' in workflow and 'cancelled' in workflow


def test_cli_pr_builds_do_not_repeat_suites_but_releases_keep_validation():
    workflow = (ROOT / '.github/workflows/build-cli.yml').read_text()
    section = workflow.split('- name: App and shared library tests', 1)[1].split('- name:', 1)[0]
    assert "if: github.event_name != 'pull_request'" in section
    assert '--package "$CLI_APP"' in workflow
    release_install = workflow.split('- name: Install full release validation dependencies', 1)[1].split('- name:', 1)[0]
    assert "if: github.event_name != 'pull_request'" in release_install
    assert 'scripts/smoke_cli_release.py' in workflow


def test_lock_removed_optional_edge_still_tests_former_consumer():
    choose = runpy.run_path(str(ROOT / 'scripts/ci_test_selection.py'))['select_lock_suites']
    before = {'package': [
        {'name': 'podcast-magic', 'source': {'editable': 'apps/podcast-magic'},
         'optional-dependencies': {'faster': [{'name': 'whisper'}]}},
        {'name': 'whisper', 'version': '1'},
    ]}
    after = {'package': [{'name': 'podcast-magic', 'source': {'editable': 'apps/podcast-magic'}}]}
    assert choose(before, after) == {'linux': ['podcast-magic'], 'macos': ['podcast-magic']}


def test_lock_shared_package_edges_do_not_loop_and_record_reorders_are_safe():
    choose = runpy.run_path(str(ROOT / 'scripts/ci_test_selection.py'))['select_lock_suites']
    before = {'package': [
        {'name': 'automixer', 'source': {'editable': 'apps/automixer'},
         'dev-dependencies': {'dev': [{'name': 'tool'}]}},
        {'name': 'tool', 'version': '1', 'dependencies': [{'name': 'automixer'}]},
    ]}
    import copy
    after = copy.deepcopy(before)
    after['package'][1]['version'] = '2'
    assert choose(before, after) == {'linux': ['automixer'], 'macos': ['automixer']}
    assert choose(before, {'package': list(reversed(before['package']))}) == {'linux': [], 'macos': []}


def test_aggregate_executes_and_catches_unexpected_skip_failure_and_cancel():
    import json
    import os
    import re
    import textwrap
    from unittest.mock import patch

    import pytest

    source = (ROOT / '.github/workflows/tests.yml').read_text().split('\n  test:', 1)[1]
    code = textwrap.dedent(re.search(r"          python - <<'PY'\n(.*?)\n          PY", source, re.S)[1])
    def check(selected, statuses, ok='true'):
        with patch.dict(os.environ, {'SELECT_OK': ok, 'SELECTION': json.dumps(selected),
                        'RESULTS': json.dumps({name: {'result': value} for name, value in statuses.items()})}):
            exec(compile(code, '<aggregate>', 'exec'), {})
    statuses = {'speechmix': 'skipped', 'automixer': 'success', 'autoraffkat': 'skipped', 'podcast-magic': 'skipped'}
    check(['automixer'], statuses)
    check([], dict.fromkeys(statuses, 'skipped'))
    check(['all'], dict.fromkeys(statuses, 'success'))
    for value in ('failure', 'cancelled', 'skipped'):
        with pytest.raises(AssertionError):
            check(['automixer'], {**statuses, 'automixer': value})
    with pytest.raises(AssertionError):
        check([], dict.fromkeys(statuses, 'skipped'), 'false')


def test_scoped_jobs_keep_root_tools_and_do_not_resync_selected_environment():
    workflow = (ROOT / '.github/workflows/tests.yml').read_text()
    assert workflow.count('UV_NO_SYNC: true') == 4
    assert workflow.count('uv sync --locked --only-group dev') == 4
    assert workflow.count('uv sync --locked --inexact --package') == 4


def test_real_workspace_lock_version_only_uses_dependency_scope(tmp_path, monkeypatch):
    import subprocess
    from unittest.mock import patch

    choose = runpy.run_path(str(ROOT / 'scripts/ci_test_selection.py'))['select_changes']
    original = (ROOT / 'uv.lock').read_text()
    import tomllib
    version = next(package['version'] for package in tomllib.loads(original)['package']
                   if package['name'] == 'automixer')
    changed = original.replace(
        f'name = "automixer"\nversion = "{version}"',
        f'name = "automixer"\nversion = "{version}.1"',
    )
    assert original != changed
    (tmp_path / 'uv.lock').write_text(changed)
    monkeypatch.chdir(tmp_path)
    with patch.object(subprocess, 'check_output', return_value=original):
        assert choose(['uv.lock', 'apps/automixer/pyproject.toml'], 'base') == {
            'linux': ['automixer'], 'macos': ['automixer']}
    with patch.object(subprocess, 'check_output', side_effect=subprocess.CalledProcessError(128, 'git')):
        assert choose(['uv.lock'], 'missing') == {'linux': ['all'], 'macos': ['all']}


def test_piped_pytest_failures_are_not_hidden_by_tee():
    for name in ('tests.yml', 'tests-linux.yml'):
        workflow = (ROOT / '.github/workflows' / name).read_text()
        assert 'defaults:\n  run:\n    shell: bash' in workflow


def test_autoraffkat_undeclared_musicbed_import_is_installed_and_selected():
    # package.py imports nhsx.musicbed although its manifest omits nhsx.
    assert 'autoraffkat' in select_suites(['packages/nhsx/src/nhsx/musicbed.py'])['macos']
    workflow = (ROOT / '.github/workflows/tests.yml').read_text()
    job = workflow.split('\n  autoraffkat:', 1)[1].split('\n  automixer:', 1)[0]
    assert '--package autoraffkat --package nhsx' in job
