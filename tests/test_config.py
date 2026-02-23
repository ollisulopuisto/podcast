import yaml
import pytest
from src.automixer.config import ConfigLoader
from src.automixer.domain.track import TrackType

@pytest.fixture
def sample_config_yaml(tmp_path):
    config_content = """
project: "Test Podcast"
target_lufs: -16.0

buses:
  speech_bus:
    processors:
      - type: compressor
        ratio: 4.0
        threshold: -20.0
  music_bus:
    processors:
      - type: eq
        low_cut: 100.0

tracks:
  - path: "host.wav"
    type: speech
    bus: speech_bus
  - path: "guest.wav"
    type: speech
    bus: speech_bus
  - path: "intro.wav"
    type: music
    bus: music_bus
"""
    config_file = tmp_path / "podcast.yaml"
    config_file.write_text(config_content)
    return config_file

def test_load_config_structure(sample_config_yaml):
    loader = ConfigLoader(sample_config_yaml)
    config = loader.load()

    assert config.project_name == "Test Podcast"
    assert config.target_lufs == -16.0
    
    # Check Buses
    assert "speech_bus" in config.buses
    assert "music_bus" in config.buses
    assert len(config.buses["speech_bus"].processors) == 1
    assert config.buses["speech_bus"].processors[0].type == "compressor"

    # Check Tracks
    assert len(config.tracks) == 3
    host_track = config.tracks[0]
    assert host_track.path == "host.wav"
    assert host_track.type == TrackType.SPEECH
    assert host_track.bus_name == "speech_bus"
