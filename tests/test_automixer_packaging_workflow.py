"""Release boundaries for the new Mac-only workflow."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_automixer_packaging_is_arm64_and_separates_pr_from_release():
    workflow = (ROOT / '.github/workflows/build-automixer-macos.yml').read_text()
    assert 'runs-on: macos-latest' in workflow
    assert 'windows' not in workflow
    assert "if: github.event_name != 'pull_request'" in workflow
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
