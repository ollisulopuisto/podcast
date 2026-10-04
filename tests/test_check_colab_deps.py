"""Testit Colabin riippuvuuksien tarkistusskriptille (scripts/check_colab_deps.py)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location(
    "check_colab_deps", ROOT / "scripts" / "check_colab_deps.py"
)
check_deps = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_deps)


def test_parse_locked_packages():
    sample_code = """
def install_dependencies():
    packages = [
        "CTranslate2==4.8.2",
        "faster-whisper==1.2.1",
        "whisper-ctranslate2==0.5.7",
        "av==18.1.0",
        "lxml==6.1.3",
        "pydub==0.25.1",
    ]
    subprocess.run(["pip", "install", *packages])
"""
    locked = check_deps.parse_locked_packages(sample_code)
    assert locked == {
        "CTranslate2": "4.8.2",
        "faster-whisper": "1.2.1",
        "whisper-ctranslate2": "0.5.7",
        "av": "18.1.0",
        "lxml": "6.1.3",
        "pydub": "0.25.1",
    }


def test_format_markdown_report_detects_outdated():
    locked = {"CTranslate2": "4.8.2", "av": "18.1.0"}
    latest = {"CTranslate2": "4.8.2", "av": "19.0.1"}

    report = check_deps.format_markdown_report(locked, latest)
    assert "| Paketti | Lukittu | Uusin PyPI | Tila |" in report
    assert "| CTranslate2 | 4.8.2 | 4.8.2 | ✅ Ajantasalla |" in report
    assert "| av | 18.1.0 | 19.0.1 | 🔄 Päivitettävissä |" in report
    assert "Päivityksiä saatavilla" in report


def test_format_markdown_report_all_up_to_date():
    locked = {"CTranslate2": "4.8.2"}
    latest = {"CTranslate2": "4.8.2"}

    report = check_deps.format_markdown_report(locked, latest)
    assert "Kaikki riippuvuudet ovat ajantasalla" in report
