"""``json-to-text``: Whisperin raaka-JSON luettavaksi markdowniksi.

Lähde on se sama JSON joka litteroinnissa jää istunnon viereen
välimuistiin — ja sama muoto jota Colab-muistikirjan ajot tuottivat.
"""

from __future__ import annotations

import json
from pathlib import Path

from podcastmagic.transcribe import json_to_text as module


def whisper_json(tmp_path: Path, segments: list[dict]) -> Path:
    path = tmp_path / "litterointi.json"
    path.write_text(
        json.dumps({"segments": segments}, ensure_ascii=False), encoding="utf-8"
    )
    return path


def test_segments_become_stamped_paragraphs():
    text = module.json_to_text(
        {
            "segments": [
                {"start": 3661.5, "text": " Toinen tunti alkaa. "},
                {"start": 3663.0, "text": "Ja siitä eteenpäin."},
            ]
        }
    )
    # Tunti, minuutti, sekunti — ja kappalevälit tyhjinä riveinä.
    assert text == (
        "**01:01:01** Toinen tunti alkaa.\n\n"
        "**01:01:03** Ja siitä eteenpäin.\n"
    )


def test_an_empty_segment_is_not_a_line():
    """Whisperin segmentin teksti voi olla pelkkää välilyöntiä."""
    text = module.json_to_text(
        {"segments": [{"start": 1.0, "text": "  "}, {"start": 2.0, "text": "Sana"}]}
    )
    assert text == "**00:00:02** Sana\n"


def test_missing_segments_are_an_empty_document_not_a_crash():
    assert module.json_to_text({}) == ""


def test_run_writes_markdown_next_to_the_json(tmp_path, capsys):
    path = whisper_json(tmp_path, [{"start": 5.0, "text": "Hei"}])
    assert module.main([str(path)]) == 0
    written = tmp_path / "litterointi.md"
    assert "Hei" in written.read_text(encoding="utf-8")


def test_the_output_never_overwrites(tmp_path):
    path = whisper_json(tmp_path, [{"start": 5.0, "text": "Hei"}])
    (tmp_path / "litterointi.md").write_text("vanha", encoding="utf-8")
    module.main([str(path)])
    assert (tmp_path / "litterointi.md").read_text(encoding="utf-8") == "vanha"
    assert "Hei" in (tmp_path / "litterointi v2.md").read_text(encoding="utf-8")


def test_a_broken_json_is_a_stated_error(tmp_path, capsys):
    broken = tmp_path / "rikki.json"
    broken.write_text("{ei ole", encoding="utf-8")
    assert module.main([str(broken)]) == 2
    assert "JSON" in capsys.readouterr().err


def test_a_missing_file_is_a_stated_error(tmp_path, capsys):
    assert module.main([str(tmp_path / "ei ole.json")]) == 2
