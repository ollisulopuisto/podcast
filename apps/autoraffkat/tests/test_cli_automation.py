"""Tests for autoraffkat headless CLI automation commands (`inspect`, `edit`)."""

import json

from autoraffkat import __main__ as main_mod


def test_cli_inspect_text(scratch_xml, capsys):
    xml_path = scratch_xml("multicam.fcpxml")
    code = main_mod.main(["inspect", str(xml_path)])
    assert code == 0
    captured = capsys.readouterr().out
    assert "Tracks:" in captured or "Raidat:" in captured or "multicam" in captured or "Monikamera" in captured


def test_cli_inspect_json(scratch_xml, capsys):
    xml_path = scratch_xml("multicam.fcpxml")
    code = main_mod.main(["inspect", str(xml_path), "--json"])
    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert "xml_path" in data
    assert "tracks" in data
    assert len(data["tracks"]) > 0


def test_cli_edit_json_export(scratch_xml, capsys, tmp_path):
    xml_path = scratch_xml("multicam.fcpxml")
    out_xml = tmp_path / "custom_out.fcpxml"
    # Create custom settings file that configures closeups for speakers
    settings_file = tmp_path / "settings.json"
    settings_file.write_text(json.dumps({
        "tracks": {
            "WIDE": {"role": "shot", "covers": ["Host", "Guest"], "context": True},
            "CLOSE_A": {"role": "shot", "covers": ["Host"], "context": False},
            "CLOSE_B": {"role": "shot", "covers": ["Guest"], "context": False},
            "host Track1": {"role": "mic", "speaker": "Host"},
            "guest Track2": {"role": "mic", "speaker": "Guest"},
        },
        "globals": {"rhythm": "mellow"},
        "audio": {"enabled": False},
    }), encoding="utf-8")

    code = main_mod.main([
        "edit",
        str(xml_path),
        "--settings",
        str(settings_file),
        "--export",
        "--output",
        str(out_xml),
        "--progress",
        "--json",
    ])
    assert code == 0
    captured = capsys.readouterr()
    lines = captured.out.splitlines()
    progress_lines = [ln for ln in lines if ln.startswith("PROGRESS ")]
    assert len(progress_lines) > 0
    last_line = [ln for ln in lines if ln.startswith("{")][-1]
    result = json.loads(last_line)
    assert result["ok"] is True
    assert result["cuts"] > 0
    assert out_xml.exists()
