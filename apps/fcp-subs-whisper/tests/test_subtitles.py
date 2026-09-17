from fcp_subs_whisper.main import (
    assign_speakers,
    format_timestamp,
    write_srt,
    write_ssa,
)


def test_format_timestamp_ssa():
    assert format_timestamp(0, "ssa") == "0:00:00.00"
    assert format_timestamp(61.5, "ssa") == "0:01:01.50"
    assert format_timestamp(3661.05, "ssa") == "1:01:01.05"


def test_format_timestamp_srt():
    assert format_timestamp(0, "srt") == "00:00:00,000"
    assert format_timestamp(61.5, "srt") == "00:01:01,500"
    assert format_timestamp(3661.055, "srt") == "01:01:01,055"


def test_write_files(tmp_path):
    segments = [
        {"start": 0.0, "end": 2.0, "text": "Hello world"},
        {"start": 2.5, "end": 4.5, "text": "Testing 123"},
    ]

    ssa_file = tmp_path / "test.ssa"
    srt_file = tmp_path / "test.srt"

    write_ssa(segments, str(ssa_file))
    write_srt(segments, str(srt_file))

    assert ssa_file.exists()
    assert srt_file.exists()

    ssa_content = ssa_file.read_text()
    assert "Dialogue: 0,0:00:00.00,0:00:02.00,Default,,0,0,0,,Hello world" in ssa_content

    srt_content = srt_file.read_text()
    assert "00:00:00,000 --> 00:00:02,000" in srt_content
    assert "Hello world" in srt_content


def test_write_files_with_speakers(tmp_path):
    segments = [
        {"start": 0.0, "end": 2.0, "text": "Hello world", "speaker": "Alice"},
    ]
    ssa_file = tmp_path / "test_spk.ssa"
    srt_file = tmp_path / "test_spk.srt"

    write_ssa(segments, str(ssa_file))
    write_srt(segments, str(srt_file))

    assert "Dialogue: 0,0:00:00.00,0:00:02.00,Default,Alice,0,0,0,,Alice: Hello world" in ssa_file.read_text()
    assert "[Alice] Hello world" in srt_file.read_text()


def test_assign_speakers():
    transcript = [
        {"start": 0.0, "end": 2.0, "text": "Hello"},
        {"start": 3.0, "end": 5.0, "text": "Hi there"},
        {"start": 7.0, "end": 8.0, "text": "Nobody"},
    ]
    speaker_segments = [
        {"start": 0.0, "end": 2.5, "speaker": "Speaker 1"},
        {"start": 2.8, "end": 6.0, "speaker": "Speaker 2"},
    ]
    assigned = assign_speakers(transcript, speaker_segments)
    assert assigned[0]["speaker"] == "Speaker 1"
    assert assigned[1]["speaker"] == "Speaker 2"
    assert assigned[2]["speaker"] == "Unknown"

