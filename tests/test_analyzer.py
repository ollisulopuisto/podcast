import numpy as np
from automixer.analyzer import SpotAnalyzer


def generate_mock_audio(duration_sec, sr, silences):
    """
    silences: list of (start_sec, end_sec)
    """
    n_samples = int(duration_sec * sr)
    audio = np.random.normal(0, 0.1, n_samples)
    for start, end in silences:
        audio[int(start * sr) : int(end * sr)] = 0.0
    return audio


def test_find_silences():
    sr = 100
    duration = 1000  # 1000 seconds
    # Silences: one before 50%, one after
    silences = [(100, 105), (600, 605)]
    audio = generate_mock_audio(duration, sr, silences)

    analyzer = SpotAnalyzer(sr=sr, skip_first_percent=50)
    spots = analyzer.find_spots(audio)

    # Should only find the silence after 500s
    assert len(spots) >= 1
    # Check if any spot is around 600s
    found_600 = any(600 <= s <= 605 for s in spots)
    assert found_600

    # Check if any spot is around 100s (should be skipped)
    found_100 = any(100 <= s <= 105 for s in spots)
    assert not found_100
