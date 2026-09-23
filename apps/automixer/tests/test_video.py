"""Yhden videotiedoston äänen korjaus, oikealla ffmpegillä.

Lupaus on kolmiosainen, ja jokainen osa on hiljainen vika jos se pettää:
kuva on **tavu tavulta** sama (ei uudelleenkoodausta), ääni on tavoitetasossa
riippumattomalla mittarilla mitattuna, ja ääni on **samassa kohdassa** kuvaa
kuin ennenkin. Viimeinen mitataan sisällöstä eikä metatiedosta: ffmpeg
siirtää syötteen alkuhetken nollaan, ja uusi WAV alkaa aina nollasta, joten
myöhässä alkava ääniraita aikaistuisi hiljaa.
"""

from __future__ import annotations

import json
import subprocess

import numpy as np
import pytest
import soundfile as sf

from automixer import cli_video

RATE = 48000
# Purske alkaa äänen omalla aikajanalla tässä, ja ääniraita alkaa videon
# aikajanalla OFFSET sekuntia myöhässä.
BURST_AT = 2.0
OFFSET = 0.25


def speechy(seconds: float = 8.0, level: float = 0.03) -> np.ndarray:
    """Hiljaa alkava puhemainen signaali, jossa terävä alku kohdassa BURST_AT."""
    rng = np.random.default_rng(20260923)
    t = np.arange(int(seconds * RATE)) / RATE
    # Laajakaistainen eikä sini: siirtymän tarkistus korreloi verhokäyriä, ja
    # 130 Hz:n sinillä se näki identiteettiliitännäisessä -4 ms siirtymän,
    # jota ketjussa ei ole (kohinalla mitattuna jokainen vaihe 0 näytettä).
    voice = rng.normal(size=t.size)
    # Tavut satunnaisin pituuksin ja tauoin. Säännöllinen verhokäyrä tekisi
    # siirtymän mittauksesta monitulkintaisen: korrelaatiolla olisi huippu
    # joka jaksolla, ja väärä huippu näyttää liitännäisen siirtymältä.
    envelope = np.zeros_like(t)
    at = BURST_AT
    while at < seconds - 0.5:
        length = rng.uniform(0.08, 0.4)
        envelope[int(at * RATE) : int((at + length) * RATE)] = rng.uniform(0.5, 1.0)
        at += length + rng.uniform(0.03, 0.3)
    envelope[int(BURST_AT * RATE) : int((BURST_AT + 0.2) * RATE)] = 1.0
    return voice * envelope * level + 0.0005 * rng.normal(size=t.size)


def run(*args: str) -> str:
    return subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args],
        check=True, capture_output=True, text=True,
    ).stdout


def make_video(tmp_path, channels: int = 2):
    """H.264 + AAC, ääni OFFSET sekuntia kuvan jälkeen."""
    wav = tmp_path / "voice.wav"
    sf.write(wav, np.stack([speechy()] * channels, axis=1).astype(np.float32), RATE)
    path = tmp_path / f"in{channels}.mp4"
    run(
        "-f", "lavfi", "-i", "testsrc=size=160x120:rate=25:duration=8.5",
        "-itsoffset", str(OFFSET), "-i", str(wav),
        "-map", "0:v", "-map", "1:a",
        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-b:a", "192k",
        str(path),
    )
    return path


@pytest.fixture
def video(tmp_path):
    return make_video(tmp_path)


def video_md5(path) -> str:
    """Kuvaraidan pakettien tiiviste — muuttuu, jos kuva koodataan uudestaan."""
    return subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path),
         "-map", "0:v", "-c", "copy", "-f", "md5", "-"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()


def integrated_lufs(path) -> float:
    """ffmpegin oma ebur128 — ei sama mittari kuin ketjun pyloudnorm."""
    err = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-map", "0:a",
         "-af", "ebur128=framelog=quiet", "-f", "null", "-"],
        check=True, capture_output=True, text=True,
    ).stderr
    line = [x for x in err.splitlines() if x.strip().startswith("I:")][-1]
    return float(line.split()[1])


def onset(path) -> float:
    """Purskeen alku videon aikajanalla sekunteina.

    ``first_pts=0`` täyttää äänen alun hiljaisuudella tiedoston nollahetkeen
    asti, joten paikka on aikajanan eikä ääniraidan oma.
    """
    out = path.parent / (path.stem + ".onset.wav")
    run("-i", str(path), "-map", "0:a", "-af", "aresample=async=1:first_pts=0",
        "-ac", "1", str(out))
    audio, rate = sf.read(out)
    loud = np.flatnonzero(np.abs(audio) > 0.25 * np.abs(audio).max())
    return loud[0] / rate


def streams(path) -> list[dict]:
    return json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout)["streams"]


def test_video_is_copied_audio_hits_target_and_stays_in_sync(video, tmp_path):
    out = tmp_path / "out.mp4"
    result = cli_video.fix_video(video, out, target_lufs=-16.0, plugin=None)

    assert video_md5(out) == video_md5(video)
    assert abs(integrated_lufs(out) - -16.0) < 0.5
    assert abs(integrated_lufs(video) - -16.0) > 5  # lähtö oli oikeasti hiljaa
    # Yksi AAC-kehys on 21 ms; synkan on pysyttävä sen alle.
    assert abs(onset(out) - onset(video)) < 0.005
    assert abs(onset(video) - (BURST_AT + OFFSET)) < 0.03
    assert [s["codec_type"] for s in streams(out)] == ["video", "audio"]
    assert streams(out)[1]["channels"] == 2
    assert result.reached_target


def test_mono_source_stays_mono_at_target(tmp_path):
    """Ketju mittaa kanavien keskiarvon. Stereona BS.1770 summaa kanavat,
    joten sama signaali kahdessa kanavassa mittaa 3 dB enemmän — ja mono
    ei saa periä stereon korjausta."""
    source = make_video(tmp_path, channels=1)
    out = tmp_path / "out.mp4"
    cli_video.fix_video(source, out, target_lufs=-16.0, plugin=None)
    assert streams(out)[1]["channels"] == 1
    assert abs(integrated_lufs(out) - -16.0) < 0.5


def test_plugin_runs_on_the_audio(video, tmp_path):
    seen = []

    class Recorder:
        def process(self, audio, rate, reset=True):
            seen.append((audio.shape, rate, reset))
            return audio

    cli_video.fix_video(video, tmp_path / "out.mp4", target_lufs=-16.0,
                        plugin=Recorder())
    assert len(seen) == 1
    (channels, _), rate, reset = seen[0]
    # Puhe käsitellään monona: liitännäinen saa yhden kanavan.
    assert (channels, rate, reset) == (1, RATE, True)


def test_shifting_plugin_is_refused_and_nothing_is_written(video, tmp_path):
    class Shifter:
        """Ilmoittaa viiveensä väärin: 2 ms myöhässä, pituus sama."""

        def process(self, audio, rate, reset=True):
            n = int(0.002 * rate)
            return np.concatenate([np.zeros_like(audio[:, :n]), audio[:, :-n]], axis=1)

    out = tmp_path / "out.mp4"
    with pytest.raises(cli_video.VideoError, match="shift"):
        cli_video.fix_video(video, out, target_lufs=-16.0, plugin=Shifter())
    assert not out.exists()


def test_refuses_to_overwrite_the_source(video):
    with pytest.raises(cli_video.VideoError, match="overwrite"):
        cli_video.fix_video(video, video, target_lufs=-16.0, plugin=None)


def with_second_audio(video, tmp_path, default: int):
    """iPhone-muoto: stereo-AAC ja toinen ääniraita (siellä APAC-tilaääni).

    Toinen raita on 1 kHz:n sini alusta asti, joten väärän raidan
    käsittely näkyy purskeen paikassa eikä vain raitojen määrässä.
    """
    tone = tmp_path / "tone.wav"
    t = np.arange(int(8.5 * RATE)) / RATE
    sf.write(tone, (0.3 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32), RATE)
    # Matroska, koska mov-muxeri merkitsee ensimmäisen raidan oletukseksi,
    # jos mikään ei ole — raidatonta tapausta ei saisi muuten tehtyä.
    two = tmp_path / f"two{default}.mkv"
    run("-i", str(video), "-i", str(tone),
        "-map", "0:v", "-map", "0:a", "-map", "1:a",
        "-c:v", "copy", "-c:a", "aac",
        "-disposition:a:0", "default" if default == 0 else "0",
        "-disposition:a:1", "default" if default == 1 else "0",
        "-default_mode", "passthrough",
        str(two))
    return two


def test_default_audio_stream_is_the_one_processed(video, tmp_path):
    two = with_second_audio(video, tmp_path, default=0)
    out = tmp_path / "out.mkv"
    cli_video.fix_video(two, out, target_lufs=-16.0, plugin=None)

    # Toista raitaa ei kopioida: Applen soittimet valitsisivat tilaäänen,
    # eli käsittelemättömän äänen, korjatun sijaan.
    assert [s["codec_type"] for s in streams(out)] == ["video", "audio"]
    assert abs(onset(out) - (BURST_AT + OFFSET)) < 0.03
    assert abs(integrated_lufs(out) - -16.0) < 0.5


def test_refuses_several_audio_streams_without_one_default(video, tmp_path):
    two = with_second_audio(video, tmp_path, default=-1)
    with pytest.raises(cli_video.VideoError, match="audio streams"):
        cli_video.fix_video(two, tmp_path / "out.mkv", target_lufs=-16.0,
                            plugin=None)
    assert not (tmp_path / "out.mkv").exists()


def test_default_output_sits_next_to_the_source(tmp_path):
    assert cli_video.default_output(tmp_path / "ep 12.mov") == tmp_path / "ep 12 [-16 LUFS].mov"


def test_dolby_vision_mov_defaults_to_mp4(tmp_path, monkeypatch):
    """ffmpeg 9:n mov-muxeri ei kirjoita DV-konfiguraatiota (dvcC/dvvC)
    lainkaan, mp4-muxeri kirjoittaa sen ``-strict unofficial``:lla. iPhonen
    DV 8.4 -tiedoston remux .mov:ksi menetti sen, .mp4:ksi ei."""
    monkeypatch.setattr(cli_video, "_probe", lambda path: {"streams": [
        {"codec_type": "video",
         "side_data_list": [{"side_data_type": "DOVI configuration record"}]},
    ]})
    (tmp_path / "clip.MOV").touch()
    assert cli_video.default_output(tmp_path / "clip.MOV") == tmp_path / "clip [-16 LUFS].mp4"


def test_missing_dxrevive_is_an_error_not_a_silent_skip(monkeypatch):
    monkeypatch.setattr(cli_video.chain, "plugins",
                        lambda: [{"name": "AppleAES3Audio", "path": "/x.component"}])
    with pytest.raises(cli_video.VideoError, match="dxRevive"):
        cli_video.find_plugin("dxRevive")


def test_finds_dxrevive_by_name(monkeypatch):
    monkeypatch.setattr(cli_video.chain, "plugins", lambda: [
        {"name": "AppleAES3Audio", "path": "/a.component"},
        {"name": "dxRevive", "path": "/b/dxRevive.vst3"},
    ])
    assert cli_video.find_plugin("dxrevive") == "/b/dxRevive.vst3"


def make_hdr(tmp_path):
    """HDR10 HEVC: PQ, BT.2020, mastering display ja MaxCLL, hvc1-tagi."""
    path = tmp_path / "hdr.mov"
    run(
        "-f", "lavfi", "-i", "testsrc2=size=160x120:rate=25:duration=4",
        "-f", "lavfi", "-i", "anoisesrc=d=4:a=0.02",
        "-c:v", "libx265", "-pix_fmt", "yuv420p10le", "-tag:v", "hvc1",
        "-x265-params",
        "colorprim=bt2020:transfer=smpte2084:colormatrix=bt2020nc:hdr10=1:"
        "repeat-headers=1:master-display=G(13250,34500)B(7500,3000)"
        "R(34000,16000)WP(15635,16450)L(10000000,1):max-cll=1000,400:"
        "log-level=error",
        "-c:a", "aac", str(path),
    )
    return path


def test_hdr10_metadata_survives(tmp_path):
    source = make_hdr(tmp_path)
    out = tmp_path / "out.mov"
    cli_video.fix_video(source, out, target_lufs=-16.0, plugin=None)
    before, after = streams(source)[0], streams(out)[0]
    for key in ("codec_tag_string", "color_transfer", "color_primaries", "color_space"):
        assert after[key] == before[key]
    assert before["color_transfer"] == "smpte2084"  # lähde oli oikeasti HDR
    assert video_md5(out) == video_md5(source)


def test_lost_video_metadata_is_refused(video, tmp_path, monkeypatch):
    """Kuvan metatieto kontissa (Dolby Visionin dvcC, värimerkinnät, tagi)
    ei ole bittivirrassa, joten tavu tavulta sama kuva ei takaa sitä. Jos
    uudelleenpakkaus pudottaa jotain, tulosta ei kirjoiteta."""
    real = cli_video._probe

    def lossy(path):
        info = real(path)
        if ".partial" in str(path):
            info["streams"][0]["side_data_list"] = []
            info["streams"][0]["color_transfer"] = "unknown"
        else:
            info["streams"][0]["side_data_list"] = [
                {"side_data_type": "DOVI configuration record"}]
        return info

    monkeypatch.setattr(cli_video, "_probe", lossy)
    out = tmp_path / "out.mp4"
    with pytest.raises(cli_video.VideoError, match="DOVI configuration record"):
        cli_video.fix_video(video, out, target_lufs=-16.0, plugin=None)
    assert not out.exists()
    assert not list(tmp_path.glob(".*partial*"))
