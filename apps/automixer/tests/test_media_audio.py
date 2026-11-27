"""Audio-only files use the same chain without needing Apple MLX."""
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf

from automixer import cli_video


def identity(audio, _rate, _settings, **kwargs):
    return audio, SimpleNamespace(lag=0, measured_lufs=-16, gain_db=0,
        limiter_db=0, psr_lu=12, reached_target=True)


@pytest.mark.parametrize('suffix', ['.wav', '.mp3', '.m4a', '.flac'])
def test_audio_only_chain_and_container(tmp_path, monkeypatch, suffix):
    source = tmp_path / 'source.wav'
    wave = np.random.default_rng(42).normal(0, 0.02, (48000, 1)).astype('float32')
    sf.write(source, wave, 48000)
    monkeypatch.setattr(cli_video.chain, 'process', identity)
    target = tmp_path / ('out' + suffix)
    cli_video.fix_video(source, target, plugin=None, log=lambda _line: None)
    streams = cli_video._probe(target)['streams']
    assert [s['codec_type'] for s in streams] == ['audio']
    assert int(streams[0]['channels']) == 1
    assert abs(float(streams[0]['duration']) - 1) < 0.1


def test_existing_target_refused_before_probe(tmp_path, monkeypatch):
    source, target = tmp_path / 'source.wav', tmp_path / 'out.wav'
    source.write_bytes(b'source')
    target.write_bytes(b'keep')
    monkeypatch.setattr(cli_video, '_probe', lambda _path: pytest.fail('probed after collision'))
    with pytest.raises(cli_video.VideoError, match='exist'):
        cli_video.fix_video(source, target)
    assert target.read_bytes() == b'keep'


def test_target_created_during_processing_is_not_replaced(tmp_path, monkeypatch):
    source, target = tmp_path / 'source.wav', tmp_path / 'out.wav'
    sf.write(source, np.ones((48000, 1), dtype='float32') * 0.01, 48000)

    def process(audio, rate, settings, **kwargs):
        target.write_bytes(b'other job')
        return identity(audio, rate, settings, **kwargs)

    monkeypatch.setattr(cli_video.chain, 'process', process)
    with pytest.raises(cli_video.VideoError, match='exist'):
        cli_video.fix_video(source, target, log=lambda _line: None)
    assert target.read_bytes() == b'other job'
    assert not list(tmp_path.glob('.*partial*'))


@pytest.mark.parametrize('channels', [1, 2])
def test_real_chain_keeps_source_and_audio_length(tmp_path, channels):
    source, target = tmp_path / 'source.wav', tmp_path / 'out.wav'
    samples = np.random.default_rng(42).normal(0, 0.04, (48000 * 4, channels))
    sf.write(source, samples, 48000)
    original = source.read_bytes()
    cli_video.fix_video(source, target, log=lambda _line: None)
    audio, rate = sf.read(target, always_2d=True)
    assert audio.shape == samples.shape
    assert rate == 48000
    assert source.read_bytes() == original
    import pyloudnorm as pyln
    assert abs(pyln.Meter(rate).integrated_loudness(audio) + 16) < 1.0


def test_multichannel_refused_without_output(tmp_path):
    source, target = tmp_path / 'source.wav', tmp_path / 'out.wav'
    sf.write(source, np.ones((48000, 3)) * 0.01, 48000)
    with pytest.raises(cli_video.VideoError, match='not 3 channels'):
        cli_video.fix_video(source, target, log=lambda _line: None)
    assert not target.exists()


def test_encode_failure_removes_only_own_partial(tmp_path, monkeypatch):
    source, target = tmp_path / 'source.wav', tmp_path / 'out.wav'
    sf.write(source, np.ones((48000, 1)) * 0.01, 48000)
    monkeypatch.setattr(cli_video.chain, 'process', identity)
    original_ffmpeg = cli_video._ffmpeg

    def fail_encoding(*args):
        if 'partial-' in args[-1]:
            raise cli_video.VideoError('encode failed')
        original_ffmpeg(*args)

    monkeypatch.setattr(cli_video, '_ffmpeg', fail_encoding)
    with pytest.raises(cli_video.VideoError, match='encode failed'):
        cli_video.fix_video(source, target, log=lambda _line: None)
    assert sorted(p.name for p in tmp_path.iterdir()) == ['source.wav']


def test_unsupported_audio_container_refused(tmp_path, monkeypatch):
    source, target = tmp_path / 'source.wav', tmp_path / 'out.xyz'
    sf.write(source, np.ones((48000, 1)) * 0.01, 48000)
    monkeypatch.setattr(cli_video.chain, 'process', identity)
    with pytest.raises(cli_video.VideoError, match='Unsupported audio'):
        cli_video.fix_video(source, target, log=lambda _line: None)
    assert not target.exists()
