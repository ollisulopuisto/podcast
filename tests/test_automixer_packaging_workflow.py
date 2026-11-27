"""Release boundaries for the new Mac-only workflow."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_automixer_packaging_is_arm64_and_separates_pr_from_release():
    workflow = (ROOT / '.github/workflows/build-automixer-macos.yml').read_text()
    assert 'runs-on: macos-latest' in workflow
    assert 'windows' not in workflow
    assert "github.ref == 'refs/heads/main'" in workflow
    assert 'scripts/smoke_automixer_macos.py' in workflow
    assert '--no-project' in workflow
    assert 'stapler validate' in workflow
    assert '--verify --deep --strict' in workflow
    assert 'APPLE_APP_PASSWORD' in workflow
    assert '--draft' in workflow
    assert 'gh release edit' in workflow


def test_frozen_worker_retains_stdio_for_piped_progress():
    spec = (ROOT / 'apps/automixer/packaging/automixer.spec').read_text()
    assert 'console=True' in spec
    assert "'automixer'" in spec and "'speechmix'" in spec


def test_pr_has_read_only_token_and_no_secrets_or_release_operations():
    workflow = (ROOT / '.github/workflows/build-automixer-macos.yml').read_text()
    pr, release = workflow.split('  release:\n', 1)
    assert 'contents: write' not in pr
    assert 'secrets.' not in pr
    assert 'gh release' not in pr
    assert 'contents: write' in release
    assert "if: github.event_name == 'workflow_dispatch' && github.ref == 'refs/heads/main'" in release
    for block in release.split('      - name:')[1:]:
        if 'secrets.' in block:
            assert "if: github.ref == 'refs/heads/main'" in block
    assert 'gh release list --limit 1000 --json tagName,isDraft' in release
    assert '--with pyinstaller' not in workflow
    assert '--group automixer-build' in workflow
    assert 'name = "pyinstaller"' in (ROOT / 'uv.lock').read_text()
