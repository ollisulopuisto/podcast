import mlx.core as mx
import numpy as np
import pytest
import soundfile as sf

from automixer.domain import shared
from automixer.domain.processor import CeilingProcessor, GainProcessor
from automixer.domain.track import Track


def test_the_ceiling_is_a_brickwall():
    """Sama väite kuin ennen, mutta vaiheesta joka on oikeasti ketjussa.

    Oli `LimiterProcessor(threshold_db=0.0)`, joka laski näytehuipuista ja
    on korvattu jaetulla true peak -rajoittimella. Katto on nyt kirjaston
    `CEILING_DB`, ja se koskee ylinäytteistettyä huippua — joten
    näytehuipun on jäätävä sen alle, ei osuttava siihen.
    """
    sr = 8000
    sig_np = np.ones((sr, 1), dtype=np.float32) * 0.5
    sig_np[4000, 0] = 2.0
    signal = mx.array(sig_np)

    processed = CeilingProcessor().process(signal, sr)

    ceiling = 10 ** (shared.CEILING_DB / 20)
    assert mx.max(mx.abs(processed)).item() <= ceiling + 1e-4
    # Huippua kaukana oleva osa jää paikalleen: rajoitin koskee huippuihin,
    # ei koko tiedostoon. Juuri tämä erotti sen staattisesta vaimennuksesta.
    assert processed[0, 0].item() == pytest.approx(0.5, rel=1e-2)


def test_gain_processor():
    signal = mx.ones((100, 1))
    gain = GainProcessor(gain_db=6.0)  # ~2x
    processed = gain.process(signal, 100)
    assert processed[0, 0].item() == pytest.approx(2.0, rel=1e-2)


def test_track_loudness_analysis(tmp_path):
    # Create a mock wav file
    sr = 44100
    duration = 2
    # Sine wave at 0.1 peak
    t = np.linspace(0, duration, sr * duration)
    data = 0.1 * np.sin(2 * np.pi * 440 * t)

    wav_path = tmp_path / "test.wav"
    sf.write(wav_path, data, sr)

    track = Track("test", str(wav_path))
    track.load()

    assert track.loudness is not None
    # A sine wave at 0.1 peak is roughly -23 LUFS
    assert -30 < track.loudness < -10
