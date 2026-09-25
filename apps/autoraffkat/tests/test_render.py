"""Renderöinti: sama kuva ja ääni kuin Final Cutin vienti samasta XML:stä.

Geometria testataan merkillä: lähteessä valkoinen pystyviiva tunnetussa
kohdassa, ja renderöidyssä kuvassa sen on oltava siellä minne kehys sen
laskee. Leikkaus testataan fixturen väreillä (laaja harmaa, lähikuvat
laivastonsininen ja viininpunainen) ja ääni sen siniäänipurskeilla.
"""

import subprocess

import numpy as np
import pytest
from conftest import needs_ffmpeg

from autoraffkat import reframe, render
from autoraffkat.render import Shot

FFMPEG = "ffmpeg"


def _bar_source(path, x=1300, seconds=2):
    """1920×1080, musta, valkoinen 20 px pystyviiva keskipisteenä ``x``."""
    subprocess.run(
        [FFMPEG, "-y", "-v", "error", "-f", "lavfi",
         "-i", f"color=black:s=1920x1080:r=25:d={seconds}",
         "-vf", f"drawbox=x={x - 10}:y=0:w=20:h=1080:color=white:t=fill",
         "-c:v", "libx264", "-g", "25", "-pix_fmt", "yuv420p", str(path)],
        check=True, capture_output=True)


def _frame(path, index, width=1080, height=1920):
    raw = subprocess.run(
        [FFMPEG, "-v", "error", "-i", str(path), "-vf", f"select=eq(n\\,{index})",
         "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.uint8).reshape(height, width)


def _bar_x(frame):
    columns = frame[frame.shape[0] // 2]
    lit = np.flatnonzero(columns > 128)
    return float(lit.mean()) if len(lit) else None


def _expected(shot, source_x, scale):
    width, _h, x, _y = render.window(shot, 1080, 1920, scale)
    return source_x * width / shot.width - x


def _backend(name):
    """ffmpeg kaikkialla, AVFoundation macOS:llä (CI ajaa macOS:llä, joten
    kumpikin testataan siellä; ohitus on alustan tosiasia, ei puuttuva työkalu)."""
    if name == "ffmpeg":
        return render.render_video
    import sys

    if sys.platform != "darwin":
        pytest.skip("AVFoundation on macOS:n")
    from autoraffkat import render_av

    return render_av.render_video


@needs_ffmpeg
@pytest.mark.parametrize("backend", ["ffmpeg", "av"])
@pytest.mark.parametrize("extra, scale1", [(1.0, 1.0), (1.12, 1.12), (1.0, 1.08)],
                         ids=["kehys", "punch", "pusku"])
def test_the_bar_lands_where_the_framing_puts_it(tmp_path, extra, scale1, backend):
    """Kehys joka keskittää kohdan 1300 px: viiva ruudun keskelle (540 px)
    — ja zoomatessa sinne minne Final Cutin keskipisteskaalaus sen vie."""
    source = tmp_path / "bar.mp4"
    _bar_source(source)
    plan = reframe.plan_shot(1300 / 1920, 0.5, 1920, 1080, zoom=extra)
    shot = Shot(0, 50, str(source), 0.0, 1920, 1080, scale0=plan.scale,
                scale1=plan.scale * scale1 / extra if scale1 != extra else plan.scale,
                pos_x=plan.pos_x, pos_y=plan.pos_y, fill=True)
    out = tmp_path / "out.mp4"
    _backend(backend)([shot], 1080, 1920, render.Fraction(1, 25), 50, str(out))
    first, last = _frame(out, 0), _frame(out, 49)
    assert abs(_bar_x(first) - _expected(shot, 1300, shot.scale0)) < 3
    assert abs(_bar_x(last) - _expected(shot, 1300, shot.scale1)) < 3
    if shot.scale0 == shot.scale1:
        assert abs(_bar_x(first) - 540) < 3


def _tone(path, freq, seconds, rate=48000):
    subprocess.run(
        [FFMPEG, "-y", "-v", "error", "-f", "lavfi",
         "-i", f"sine=f={freq}:d={seconds}:r={rate}", "-ac", "1", str(path)],
        check=True, capture_output=True)


def _read(path):
    from pedalboard.io import AudioFile

    with AudioFile(str(path)) as f:
        return f.read(f.frames), f.samplerate


def _rms_db(x):
    return 20 * np.log10(np.sqrt(np.mean(x.astype(np.float64) ** 2)) + 1e-12)


@needs_ffmpeg
def test_the_audio_mix_places_ducks_and_pans_like_the_export(tmp_path):
    """Ääni samoista tiedostoista samoilla käyrillä kuin vienti.

    Mikki A on tiedostossa kohdassa 2 s, aikajanalla 12 s (ohjelma alkaa
    10 s:sta), panoroitu kokonaan vasemmalle, ja vaimennus -20 dB
    ohjelman sekunnista 3 alkaen. Mikki B keskellä. Pituus on ohjelman.
    """
    from autoraffkat.render import AudioSource, render_audio

    a, b = tmp_path / "a.wav", tmp_path / "b.wav"
    _tone(a, 440, 6)
    _tone(b, 880, 6)
    sources = [
        AudioSource(str(a), [(12.0, 15.0, 2.0)], duck=[(12.99, 0.0), (13.0, -20.0)], pan=-100),
        AudioSource(str(b), [(10.0, 11.0, 0.0)]),
    ]
    out = tmp_path / "mix.wav"
    render_audio(sources, 10.0, 6.0, str(out))
    mix, rate = _read(out)
    assert mix.shape == (2, 6 * rate)
    left, right = mix
    second = rate
    assert _rms_db(right[2 * second:3 * second]) < -80          # A vain vasemmalla
    loud = _rms_db(left[int(2.1 * second):int(2.9 * second)])
    ducked = _rms_db(left[int(3.1 * second):int(4.9 * second)])
    assert abs((loud - ducked) - 20) < 0.5
    assert _rms_db(left[:second]) > -30 and abs(_rms_db(left[:second]) - _rms_db(right[:second])) < 0.1
    assert _rms_db(mix[:, int(1.1 * second):int(1.9 * second)]) < -80   # hiljaisuus välissä


def test_the_hardware_encoder_is_used_when_it_works(monkeypatch):
    """VideoToolbox kun se toimii, muuten x264 — ja kumpi, se kerrotaan.

    Mitattuna 60 s:n 1080p-kuvalla pystyyn: x264 5,0 s ja 30,6 s
    suoritinaikaa, VideoToolbox 4,4 s ja 14,9 s. Kello liikkuu vähän
    (skaalaus on hitain osa), mutta suoritin puolittuu, ja kolme kuvaa
    koodataan rinnakkain.
    """
    monkeypatch.setattr(render, "_ENCODER", None)
    monkeypatch.setattr(render, "_trial", lambda args: True)
    assert render.encoder()[0] == "h264_videotoolbox"
    monkeypatch.setattr(render, "_ENCODER", None)
    monkeypatch.setattr(render, "_trial", lambda args: False)
    name, args = render.encoder()
    assert name == "libx264" and "libx264" in args


@needs_ffmpeg
def test_a_render_can_be_stopped_and_leaves_no_file(tmp_path):
    """Pysäytys kesken: ffmpegit lopetetaan, eikä puolikasta videota jää.

    Puolikas MP4 joka näyttää valmiilta olisi pahempi kuin ei mitään: se
    menisi shortsien poimijalle ja puuttuva loppu huomattaisiin vasta siellä.
    """
    import threading

    source = tmp_path / "bar.mp4"
    _bar_source(source, seconds=4)
    shots = [Shot(i * 20, (i + 1) * 20, str(source), 0.0, 1920, 1080, fill=True)
             for i in range(5)]
    stop = threading.Event()
    out = tmp_path / "out.mp4"
    with pytest.raises(render.Stopped):
        render.render_program(shots, [], 1080, 1920, render.Fraction(1, 25), 100, 0.0,
                              str(out), progress=lambda f: stop.set(), stop=stop)
    assert not out.exists()
    assert not list(tmp_path.glob("out.mp4*"))


@needs_ffmpeg
def test_a_picture_smaller_than_the_frame_is_letterboxed(tmp_path):
    """Varapolku: kuva joka ei täytä projektia saa mustat reunat eikä kaadu."""
    source = tmp_path / "bar.mp4"
    _bar_source(source)
    shot = Shot(0, 10, str(source), 0.0, 1920, 1080, scale0=0.5, scale1=0.5)
    out = tmp_path / "out.mp4"
    render.render_video([shot], 1920, 1080, render.Fraction(1, 25), 10, str(out))
    frame = _frame(out, 0, width=1920, height=1080)
    assert frame[:200].max() < 30            # yläreuna mustaa
    assert frame[540].max() > 200            # viiva näkyy keskellä


@needs_ffmpeg
def test_a_render_reports_its_timings_in_the_terminal(tmp_path, capsys):
    """Renderöinti kertoo terminaaliin koodaimen, vaiheiden ajat ja kokonaisajan.

    Käyttäjä kysyi ensimmäisen oikean renderöinnin aikana, näkyykö kesto
    lopuksi — ei näkynyt, eikä hidasta ajoa voinut jälkikäteen purkaa
    vaiheiksi.
    """
    source = tmp_path / "bar.mp4"
    _bar_source(source)
    shot = Shot(0, 25, str(source), 0.0, 1920, 1080, fill=True)
    render.render_program([shot], [], 1080, 1920, render.Fraction(1, 25), 25, 0.0,
                          str(tmp_path / "out.mp4"))
    lines = [line for line in capsys.readouterr().out.splitlines()
             if line.startswith("[video]")]
    text = "\n".join(lines)
    assert render.video_backend()[0] in text
    for word in ("kuva", "ääni", "valmis"):
        assert word in text, text


@needs_ffmpeg
def test_the_av_render_cuts_on_the_exact_frame_and_has_the_exact_length(tmp_path):
    """AVFoundation: kaksi kuvaa eri kohdista samaa tiedostoa ja musta aukko
    välissä — leikkaus osuu ruudulleen ja pituus on ruutujen summa."""
    backend = _backend("av")
    source = tmp_path / "bar.mp4"
    _bar_source(source, x=900, seconds=4)      # keskitetty rajaus näyttää 656–1264
    other = tmp_path / "bar2.mp4"
    _bar_source(other, x=1100, seconds=4)
    shots = [Shot(0, 30, str(source), 0.0, 1920, 1080, fill=True),
             Shot(30, 40, ""),
             Shot(40, 75, str(other), 1.0, 1920, 1080, fill=True)]
    out = tmp_path / "out.mp4"
    backend(shots, 1080, 1920, render.Fraction(1, 25), 75, str(out))
    frames = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
         "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", str(out)],
        check=True, capture_output=True, text=True).stdout.strip()
    assert int(frames) == 75
    assert _frame(out, 29).max() > 200 and _frame(out, 30).max() < 30   # aukko alkaa
    assert _frame(out, 39).max() < 30 and _frame(out, 40).max() > 200


@needs_ffmpeg
def test_the_av_render_in_two_halves_joins_on_the_exact_frame(tmp_path):
    """Kaksi vientiä rinnakkain (M1 Maxissa kaksi koodainta: 11× -> 16×
    reaaliaika, neljä ei enää auta) ja liitos kopiona: pituus ja leikkaukset
    pysyvät ruudun tarkkuudella myös liitoksen yli."""
    from autoraffkat import render_av

    if not hasattr(render_av, "HALVES"):
        pytest.fail("ei jakoa")
    source = tmp_path / "bar.mp4"
    _bar_source(source, x=900, seconds=6)
    other = tmp_path / "bar2.mp4"
    _bar_source(other, x=1100, seconds=6)
    # Jako osuu kahden oikean kuvan väliin (ruutu 90): mustan aukon viereen
    # ei jaeta, koska AVFoundation pudottaa viennin lopun tyhjän jakson.
    shots = [Shot(0, 40, str(source), 0.0, 1920, 1080, fill=True),
             Shot(40, 50, ""),
             Shot(50, 90, str(source), 2.0, 1920, 1080, fill=True),
             Shot(90, 140, str(other), 1.0, 1920, 1080, fill=True)]
    out = tmp_path / "out.mp4"
    render_av.render_video(shots, 1080, 1920, render.Fraction(1, 25), 140, str(out))
    frames = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
         "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", str(out)],
        check=True, capture_output=True, text=True).stdout.strip()
    assert int(frames) == 140
    assert _frame(out, 39).max() > 200 and _frame(out, 40).max() < 30
    assert _frame(out, 49).max() < 30 and _frame(out, 50).max() > 200
    # Liitos: viiva vaihtaa paikkaa täsmälleen ruudulla 90.
    assert abs(_bar_x(_frame(out, 89)) - _bar_x(_frame(out, 50))) < 3
    assert _bar_x(_frame(out, 90)) - _bar_x(_frame(out, 89)) > 300
