"""Colabissa ajettava ketju: litterointi, injektio, Auto-Silence.

Tämä tiedosto ei ole työtilan koodia vaan **lähetettävä resurssi**: ajuri
 lataa sen `/content/pipeline.py`ksi ja Colabin Python ajaa sen. Se ei voi
tuoda `speechmix`ia eikä mitään muuta työtilasta — pilvessä asennetaan
omiksi pip-paketeiksi mitä tarvitaan (`install_dependencies`). Se on myös
syyny sille, ettei tämä sovellus seiso `apps/`issa: jaettu ketju ei yletä
tänne, joten tämä on oma snapshotkinsa ja driftin vaara kirjoitetaan
sovelluksen CLAUDE.mdiin, ei vaaneta.
"""

import argparse
import json
import os
import subprocess
from itertools import pairwise

from lxml import etree

# Oletusaikarajat (sekunteina) aliprosesseille. Colabissa asennus ja
# litterointi voivat kestään kauan, joten rajat ovat ydinsä.
APT_TIMEOUT = 600  # 10 min apt-get:lle
PIP_TIMEOUT = 600  # 10 min pip:lle
WHISPER_TIMEOUT = 7200  # 2 h whisper-ctranslate2:lle (pitkät tiedostot)

AUDIO_EXTENSIONS = (".wav", ".aiff", ".flac", ".m4a", ".mp4", ".mp3")

# Istunto on käyttäjän tiedosto ja se jäsennetään aina tällä jäsentimellä:
# ei DTD:tä, ei entiteettien ratkaisua, ei verkkoa. Samat rajat molemmissa
# paikoissa, joissa .nhsx luetaan (injektio ja Auto-Silence), jotta kumpikaan
# ei ehdi tulla löysäksi toista silmämääräämättä.
_SAFE_PARSER = etree.XMLParser(
    recover=False,
    resolve_entities=False,
    no_network=True,
    dtd_validation=False,
    load_dtd=False,
)


def _reject_doctype(raw: str, filename: str) -> None:
    """Kielii DTD:n: kelvollinen istunto ei julista sitä koskaan.

    ``<!DOCTYPE>`` avaisi ovi entiteettejä — tiedostojen luku (XXE) ja
    laajennus — joten julistava tiedosto hylätään ennen jäsennystä.
    """
    if "<!doctype" in raw.lower():
        raise ValueError(f"Istunto julistaa DTD:n, hylätään: {filename}")


def _local(tag):
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1]


def _iter_named(root, name):
    elem = root.getroot() if hasattr(root, "getroot") else root
    for node in list(elem.iter()):
        if _local(node.tag) == name:
            yield node


def _first_named(root, name):
    return next(_iter_named(root, name), None)


def _children_named(elem, name):
    return [child for child in elem if _local(child.tag) == name]


def _swap_audio_ext(filename, new_ext=".json"):
    lower = filename.lower()
    for ext in AUDIO_EXTENSIONS:
        if lower.endswith(ext):
            return filename[: len(filename) - len(ext)] + new_ext
    return filename


def _swap_suffix(path, old, new):
    lower = path.lower()
    if lower.endswith(old):
        return path[: len(path) - len(old)] + new
    return path + new


LD_SO_CONF_PATH = "/etc/ld.so.conf.d/00-nvidia-pip.conf"


def configure_cuda_libs():
    """Varmistaa että pipin asentamat nvidia-kirjastot (libcublas ym.) löytyvät."""
    import glob

    nvidia_dirs = glob.glob("/usr/local/lib/python*/dist-packages/nvidia/*/lib")
    if nvidia_dirs:
        try:
            with open(LD_SO_CONF_PATH, "w") as f:
                f.write("\n".join(nvidia_dirs) + "\n")
            subprocess.run(["ldconfig"], check=False)
        except Exception:
            pass
        existing = os.environ.get("LD_LIBRARY_PATH", "")
        paths = nvidia_dirs + ([existing] if existing else [])
        os.environ["LD_LIBRARY_PATH"] = ":".join(paths)


# 1. Asennetaan tarvittavat kirjastot pilviympäristössä
def install_dependencies():
    packages = [
        "CTranslate2==4.8.2",
        "faster-whisper==1.2.1",
        "whisper-ctranslate2==0.5.7",
        "av==18.1.0",
        "lxml==6.1.3",
        "pydub==0.25.1",
    ]
    subprocess.run(["apt-get", "update", "-qq"], check=True, timeout=APT_TIMEOUT)
    subprocess.run(
        ["apt-get", "install", "-y", "-qq", "ffmpeg"], check=True, timeout=APT_TIMEOUT
    )
    subprocess.run(
        ["pip", "install", "-q", *packages], check=True, timeout=PIP_TIMEOUT
    )
    configure_cuda_libs()


# 2. Aikaleimojen apufunktiot
def time_to_seconds(time_str):
    if time_str is None:
        # Hindenburg jättää Startin kirjoittamatta kun alue alkaa nollasta.
        return 0.0
    if not time_str:
        raise ValueError("tyhjä aikaleima")
    try:
        parts = time_str.split(":")
        if len(parts) > 3:
            raise ValueError(f"liian monta osaa aikaleimassa: {time_str}")
        return sum(float(x) * 60**i for i, x in enumerate(reversed(parts)))
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"virheellinen aikaleima: {time_str}") from e


def seconds_to_time(s):
    return f"{s:.3f}"


def merge_intervals_with_gap(intervals, max_gap=0.0):
    if not intervals:
        return []
    # Kopioi ja järjestä, älä muokkaa alkuperäistä
    sorted_intervals = sorted(intervals)
    merged = [list(sorted_intervals[0])]
    for curr in sorted_intervals[1:]:
        if curr[0] <= merged[-1][1] + max_gap:
            merged[-1][1] = max(merged[-1][1], curr[1])
        else:
            merged.append(list(curr))
    return [tuple(i) for i in merged]


# 3. Litterointi Faster-Whisperillä
def run_transcription(input_dir, output_dir, initial_prompt):
    transcripts_dir = os.path.join(output_dir, "transcripts")
    os.makedirs(transcripts_dir, exist_ok=True)
    audio_items = []
    for dirpath, _, filenames in os.walk(input_dir):
        for filename in filenames:
            if filename.lower().endswith(AUDIO_EXTENSIONS):
                audio_items.append((dirpath, filename))

    total = len(audio_items)
    print(f"[vaihe 2/4] Litteroidaan äänitiedostot ({total} kpl)...", flush=True)

    for idx, (dirpath, filename) in enumerate(audio_items, 1):
        full_path = os.path.join(dirpath, filename)
        output_path = os.path.join(
            transcripts_dir, _swap_audio_ext(filename, ".json")
        )

        if not os.path.isfile(output_path):
            print(f"[vaihe 2/4 ({idx}/{total})] Litteroidaan: {filename}", flush=True)
            print(f"Litteroidaan tiedostoa: {full_path}", flush=True)
            cmd = [
                "whisper-ctranslate2",
                full_path,
                "--batched",
                "True",
                "--compute_type",
                "auto",
                "--word_timestamps",
                "True",
                "--max_line_width",
                "33",
                "--max_line_count",
                "2",
                "--vad_filter",
                "True",
                "--model",
                "turbo",
                "--language",
                "fi",
                "--initial_prompt",
                initial_prompt,
                "--output_dir",
                transcripts_dir,
                "--suppress_tokens",
                "",
                "--suppress_blank",
                "False",
                "--condition_on_previous_text",
                "False",
            ]
            subprocess.run(cmd, check=True, timeout=WHISPER_TIMEOUT)
            print(f"Litterointi luotu: {output_path}", flush=True)
        else:
            print(
                f"[vaihe 2/4 ({idx}/{total})] Ohitetaan '{filename}', se on jo litteroitu.",
                flush=True,
            )
            print(f"Ohitetaan '{output_path}', se on jo litteroitu.", flush=True)
            print(f"Litterointi luotu: {output_path}", flush=True)



# 4. Injektoidaan litteroinnit .nhsx-rakenteeseen
def inject_transcriptions_to_nhsx(input_dir, output_dir):
    transcripts_dir = os.path.join(output_dir, "transcripts")
    transcripts_root = os.path.realpath(transcripts_dir)
    generated_nhsx = []

    for filename in os.listdir(input_dir):
        lower = filename.lower()
        if not lower.endswith(".nhsx") or lower.endswith("_processed.nhsx"):
            continue
        nhsx_in_path = os.path.join(input_dir, filename)
        with open(nhsx_in_path, "r", encoding="utf-8") as f:
            raw = f.read()
        _reject_doctype(raw, filename)
        xml_elems = etree.fromstring(raw.encode("utf-8"), _SAFE_PARSER)

        for file_elem in _iter_named(xml_elems, "File"):
            file_elem_name = file_elem.get("Name")
            if not file_elem_name:
                continue
            json_name = _swap_audio_ext(os.path.basename(file_elem_name), ".json")
            srt_path = os.path.realpath(os.path.join(transcripts_dir, json_name))
            try:
                inside = (
                    os.path.commonpath([transcripts_root, srt_path]) == transcripts_root
                )
            except ValueError:
                inside = False
            if not inside or not os.path.isfile(srt_path):
                continue

            try:
                with open(srt_path, "r", encoding="utf-8") as sf:
                    srt_data = json.load(sf)
            except (OSError, ValueError):
                continue

            if _first_named(file_elem, "Transcription") is not None:
                continue

            transcription_elem = etree.SubElement(file_elem, "Transcription")
            p_elem = etree.SubElement(transcription_elem, "p")

            for segment in srt_data.get("segments", []):
                for word in segment.get("words", []):
                    try:
                        start = float(word["start"])
                        end = float(word["end"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    text = (word.get("word") or "").strip()
                    if not text:
                        continue
                    word_elem = etree.SubElement(p_elem, "w")
                    word_elem.set("l", str(end - start))
                    word_elem.set("s", str(start))
                    word_elem.set("sp", "UU")
                    word_elem.text = text

        out_name = _swap_suffix(filename, ".nhsx", " litteroitu.nhsx")
        out_file_path = os.path.join(output_dir, out_name)
        etree.ElementTree(xml_elems).write(
            out_file_path, encoding="UTF-8", xml_declaration=True
        )
        print(f"Litteroitu .nhsx luotu: {out_file_path}")
        generated_nhsx.append(out_file_path)

    return generated_nhsx


# 5. Auto-Silence -käsittely
def get_speech_intervals_for_track(
    tree, track_elem, audio_folder, rms_enabled, threshold
):
    speech_on_timeline = []
    audio_pool = _first_named(tree, "AudioPool")
    if audio_pool is None:
        return []

    loaded_audio = {}
    if rms_enabled:
        from pydub import AudioSegment
    files_by_id = {
        fe.get("Id"): fe for fe in _iter_named(audio_pool, "File") if fe.get("Id")
    }
    for region in _children_named(track_elem, "Region"):
        file_elem = files_by_id.get(region.get("Ref"))
        if file_elem is None:
            continue

        transcription = _first_named(file_elem, "Transcription")
        if transcription is not None:
            r_start = time_to_seconds(region.get("Start"))
            r_offset = time_to_seconds(region.get("Offset", "0"))
            r_len = time_to_seconds(region.get("Length"))

            for word in _iter_named(transcription, "w"):
                # Sanan aika on tiedoston aikaa ja voi olla muodossa MM:SS
                # (vanhemmat istunnot); float() kaataisi kaksoispisteen.
                ws = time_to_seconds(word.get("s"))
                wl = time_to_seconds(word.get("l"))

                if r_offset <= ws < (r_offset + r_len):
                    timeline_s = r_start + (ws - r_offset)
                    timeline_e = timeline_s + wl

                    if rms_enabled:
                        file_name = file_elem.get("Name") or file_elem.get("Path", "")
                        pool_path = audio_pool.get("Path", "")
                        candidate_paths = [
                            os.path.join(
                                audio_folder, pool_path, os.path.basename(file_name)
                            ),
                            os.path.join(audio_folder, os.path.basename(file_name)),
                        ]
                        abs_path = None
                        for cand in candidate_paths:
                            if os.path.isfile(cand):
                                abs_path = cand
                                break

                        if abs_path and abs_path not in loaded_audio:
                            print(
                                f"      Analysoidaan audiota: {os.path.basename(abs_path)}..."
                            )
                            loaded_audio[abs_path] = AudioSegment.from_file(abs_path)

                        audio = loaded_audio.get(abs_path) if abs_path else None
                        if audio is not None:
                            chunk = audio[int(ws * 1000) : int((ws + wl) * 1000)]
                            if chunk.dBFS < threshold:
                                continue

                    speech_on_timeline.append((timeline_s, timeline_e))

    return sorted(speech_on_timeline)


def process_track(track_elem, intervals, tail, gap):
    if not intervals:
        return
    groups = merge_intervals_with_gap(intervals, gap)
    padded = [(max(0, s - tail), e + tail) for s, e in groups]
    audible_zones = merge_intervals_with_gap(padded, 0)
    original_regions = _children_named(track_elem, "Region")
    parent = track_elem

    for r in original_regions:
        rs = time_to_seconds(r.get("Start"))
        rl = time_to_seconds(r.get("Length"))
        re = rs + rl
        ro = time_to_seconds(r.get("Offset", "0"))
        cuts = sorted(
            {rs, re}
            | {z[0] for z in audible_zones if rs < z[0] < re}
            | {z[1] for z in audible_zones if rs < z[1] < re}
        )

        for i in range(len(cuts) - 1):
            mid = (cuts[i] + cuts[i + 1]) / 2
            is_aud = any(z[0] <= mid <= z[1] for z in audible_zones)
            el = etree.SubElement(parent, "Region", dict(r.attrib))
            el.set("Start", seconds_to_time(cuts[i]))
            el.set("Length", seconds_to_time(cuts[i + 1] - cuts[i]))
            el.set("Offset", seconds_to_time(ro + (cuts[i] - rs)))
            if not is_aud:
                el.set("Muted", "True")
            elif "Muted" in el.attrib:
                del el.attrib["Muted"]
        parent.remove(r)


def run_auto_silence(nhsx_path, audio_folder, rms_enabled, threshold, tail, gap):
    output_path = _swap_suffix(nhsx_path, ".nhsx", "_processed.nhsx")
    with open(nhsx_path, "r", encoding="utf-8") as f:
        raw = f.read()
    _reject_doctype(raw, os.path.basename(nhsx_path))
    tree = etree.ElementTree(etree.fromstring(raw.encode("utf-8"), _SAFE_PARSER))
    print(f"\nSuoritetaan Auto-Silence: {os.path.basename(nhsx_path)}")
    print(
        f"RMS-tarkistus: {rms_enabled} (Kynnys: {threshold} dB) | Häntä: {tail}s | Tauko: {gap}s"
    )

    for track in list(_iter_named(tree, "Track")):
        track_name = track.get("Name", "Nimetön")
        print(f"  Raita: {track_name}...")
        intervals = get_speech_intervals_for_track(
            tree, track, audio_folder, rms_enabled, threshold
        )
        print(f"    Säilytetty {len(intervals)} puhejaksoa.")
        process_track(track, intervals, tail, gap)

    tree.write(output_path, encoding="UTF-8", xml_declaration=True)
    print(f"Valmis käsitelty projekti: {output_path}")
    return output_path


# 6. Käsikirjoitus valmiista istunnosta
def _stamp(seconds):
    total = int(seconds)
    return f"[{total // 60:02d}:{total % 60:02d}]"


def write_script(nhsx_path):
    """Istunnosta luettava `.md` sen viereen: yksi kappale per puheenvuoro.

    **Snapshot** podcast-magicin `script/core.py`:stä, koska tämä skripti ei
    voi tuoda työtilaa (ks. CLAUDE.md). Raidan nimi on puhujan nimi,
    peräkkäiset alueet samalta raidalta ovat yksi vuoro, aikaleima on vuoron
    ensimmäisen alueen paikka aikajanalla ja tekstin antavat sanat joiden
    tiedostoaika osuu alueen ikkunaan. `test_the_snapshot_script_matches_
    podcast_magics` vertaa tulosta alkuperäiseen.
    """
    with open(nhsx_path, "r", encoding="utf-8") as f:
        raw = f.read()
    _reject_doctype(raw, os.path.basename(nhsx_path))
    tree = etree.ElementTree(etree.fromstring(raw.encode("utf-8"), _SAFE_PARSER))

    pool = _first_named(tree, "AudioPool")
    files = {}
    if pool is not None:
        for file_elem in _children_named(pool, "File"):
            files.setdefault(file_elem.get("Id", ""), file_elem)

    entries = []
    for track in _iter_named(tree, "Track"):
        name = track.get("Name", "")
        for region in _children_named(track, "Region"):
            file_elem = files.get(region.get("Ref", ""))
            if file_elem is None:
                continue
            transcription = _first_named(file_elem, "Transcription")
            if transcription is None:
                continue
            start = time_to_seconds(region.get("Start", "0"))
            offset = time_to_seconds(region.get("Offset", "0"))
            length = time_to_seconds(region.get("Length"))
            words = []
            for word in _iter_named(transcription, "w"):
                text = (word.text or "").strip()
                if not text:
                    continue
                ws = time_to_seconds(word.get("s"))
                we = ws + time_to_seconds(word.get("l"))
                if ws < offset + length and we > offset:
                    words.append(text)
            if words:  # musiikkiraita ja tyhjä alue eivät ole käsikirjoitusta
                entries.append((start, name, " ".join(words)))

    entries.sort(key=lambda entry: entry[0])
    turns = []
    for start, name, text in entries:
        if turns and turns[-1][1] == name:
            turns[-1][2].append(text)
        else:
            turns.append((start, name, [text]))
    lines = [f"{_stamp(start)} **{name}:** {' '.join(parts)}" for start, name, parts in turns]
    output_path = _swap_suffix(nhsx_path, ".nhsx", ".md")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n\n".join(lines) + ("\n" if lines else ""))
    print(f"Käsikirjoitus luotu: {output_path} ({len(lines)} vuoroa)")
    return output_path


# 7. Koko miksauksen litterointi ilman puhujia (--source downmix)
#
# DRIFT: tämä osio on käsin tehty snapshot kolmesta lähteestä, koska skripti
# ei voi tuoda työtilaa (ks. CLAUDE.md, "Downmix on snapshot"):
#   - podcast-magicin transcribe/downmix.py (gain_mix, paragraph_lines, run)
#   - packages/nhsx mix.py (Gain/ClipGain/Volume/Muted, ohjelman kesto)
#   - packages/nhsx read.py `locate` (äänipoolin tiedoston haku levyltä)
#   - podcast-magicin nhsx/write.py `paragraphs` (PARAGRAPH_GAP, _MAX_WORDS)
# Vain gain-summaus: ei panorointia, ramppeja eikä häivytyksiä. Yhtäläisyys
# podcast-magicin kanssa on testattu vain kappalejaon ja tekstin osalta.
DOWNMIX_RATE = 16000  # Whisperin oma näytteenottotaajuus
PARAGRAPH_GAP = 1.2  # s; sama kuin podcast-magicin nhsx/write.py
PARAGRAPH_MAX_WORDS = 80


class _Word:
    """Sana: teksti sekä alku- ja loppuaika sekunteina."""

    def __init__(self, text, start, end):
        self.text = text
        self.start = start
        self.end = end


def _truthy(value):
    return (value or "").strip().lower() in {"true", "1", "yes"}


def _number(value, default):
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _db_to_linear(db):
    return 10 ** (db / 20.0)


def _level(elem):
    """``ClipGain`` voittaa ``Gain``in eikä summaudu sen kanssa (mitattu)."""
    level = elem.get("ClipGain")
    if level is None:
        level = elem.get("Gain")
    return _db_to_linear(_number(level, 0.0))


def _locate(raw, name, audio_dirs):
    """Äänipoolin tiedosto levyltä: absoluuttinen, juuri+polku, juuri+nimi, haku."""
    if os.path.isabs(raw) and os.path.isfile(raw):
        return raw
    for root_dir in audio_dirs:
        for candidate in (os.path.join(root_dir, raw), os.path.join(root_dir, name)):
            if os.path.isfile(candidate):
                return candidate
    for root_dir in audio_dirs:
        for dirpath, _, filenames in os.walk(root_dir):
            if name in filenames:
                return os.path.join(dirpath, name)
    return ""


def read_mix(nhsx_path, audio_dir):
    """Istunnon kuultavat leikkeet: ``(clips, duration, missing)``.

    Leike on ``(polku, start, length, offset, gain)``. Kesto lasketaan
    **kaikista** alueista, myös mykistetyistä, jotta aikajana on yhtä pitkä
    kuin Hindenburgissa.
    """
    with open(nhsx_path, "r", encoding="utf-8") as f:
        raw = f.read()
    _reject_doctype(raw, os.path.basename(nhsx_path))
    tree = etree.ElementTree(etree.fromstring(raw.encode("utf-8"), _SAFE_PARSER))

    pool = _first_named(tree, "AudioPool")
    files = {}
    if pool is not None:
        for file_elem in _children_named(pool, "File"):
            files.setdefault(file_elem.get("Id", ""), file_elem)

    session_dir = os.path.dirname(os.path.abspath(nhsx_path))
    pool_path = (pool.get("Path") or "").strip() if pool is not None else ""
    pool_dir = os.path.join(session_dir, pool_path) if pool_path else session_dir
    audio_dirs = [d for d in (audio_dir, pool_dir, session_dir) if d]

    clips, missing, duration = [], [], 0.0
    for track in _iter_named(tree, "Track"):
        track_gain = _level(track) * _db_to_linear(_number(track.get("Volume"), 0.0))
        track_muted = _truthy(track.get("Muted"))
        for region in _children_named(track, "Region"):
            start = time_to_seconds(region.get("Start"))
            length = time_to_seconds(region.get("Length"))
            offset = time_to_seconds(region.get("Offset"))
            duration = max(duration, start + length)
            if length <= 0 or track_muted or _truthy(region.get("Muted")):
                continue
            file_elem = files.get(region.get("Ref", ""))
            if file_elem is None:
                continue
            raw_path = file_elem.get("Path") or file_elem.get("Name", "")
            name = os.path.basename(raw_path) or file_elem.get("Name", "")
            path = _locate(raw_path, name, audio_dirs)
            if not path:
                if name not in missing:
                    missing.append(name)
                continue
            clips.append((path, start, length, offset, _level(region) * track_gain))
    return clips, duration, missing


def decode_mono(path, offset, length, rate):
    """Leikkeen kohta monona float32-näytteinä ffmpegillä (``-ss`` ennen ``-i``:tä)."""
    import numpy as np

    cmd = [
        "ffmpeg", "-v", "error", "-ss", f"{offset:.6f}", "-t", f"{length:.6f}",
        "-i", path, "-vn", "-ac", "1", "-ar", str(rate), "-f", "f32le", "-",
    ]
    result = subprocess.run(cmd, check=True, capture_output=True, timeout=WHISPER_TIMEOUT)
    return np.frombuffer(result.stdout, dtype="<f4")


def gain_mix(clips, duration, rate=DOWNMIX_RATE, decode=None):
    """Monomiksaus: leikkeen näytteet kerrottuna gainilla ja summattuna.

    Ei panorointia, ramppeja eikä häivytyksiä. Lyhyt lähde täytetään
    hiljaisuudella. numpy on mukana jo faster-whisperin riippuvuutena.
    """
    import numpy as np

    decode = decode or decode_mono  # haetaan kutsuhetkellä, jotta testi voi korvata sen
    total = int(round(duration * rate))
    out = np.zeros(total, dtype=np.float32)
    for path, start, length, offset, gain in clips:
        first = int(round(start * rate))
        count = int(round(length * rate))
        if count <= 0 or first >= total:
            continue
        samples = np.asarray(decode(path, offset, length, rate), dtype=np.float32)
        samples = samples.reshape(-1)[:count]
        end = min(total, first + count)
        n = min(samples.shape[0], end - first)
        out[first : first + n] += samples[:n] * np.float32(gain)
    return out


def paragraphs(words, gap=PARAGRAPH_GAP, max_words=PARAGRAPH_MAX_WORDS):
    if not words:
        return []
    groups = [[words[0]]]
    for previous, word in pairwise(words):
        if word.start - previous.end >= gap or len(groups[-1]) >= max_words:
            groups.append([word])
        else:
            groups[-1].append(word)
    return groups


def paragraph_lines(words):
    """``[MM:SS] teksti`` per kappale, kappaleet tyhjällä rivillä erotettuna."""
    lines = [
        f"{_stamp(group[0].start)} " + " ".join(w.text.strip() for w in group)
        for group in paragraphs(list(words))
    ]
    if not lines:
        return ""
    return "\n\n".join(lines) + "\n"


def transcribe_samples(samples, rate, initial_prompt):
    """Litteroi näytteet samalla whisper-ctranslate2-kutsulla kuin raidat."""
    import tempfile
    import wave

    import numpy as np

    with tempfile.TemporaryDirectory() as tmp:
        wav_path = os.path.join(tmp, "downmix.wav")
        pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2")
        with wave.open(wav_path, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(rate)
            wav.writeframes(pcm.tobytes())
        cmd = [
            "whisper-ctranslate2", wav_path, "--batched", "True",
            "--compute_type", "auto", "--word_timestamps", "True",
            "--vad_filter", "True", "--model", "turbo", "--language", "fi",
            "--initial_prompt", initial_prompt, "--output_dir", tmp,
            "--output_format", "json", "--suppress_tokens", "",
            "--suppress_blank", "False", "--condition_on_previous_text", "False",
        ]
        subprocess.run(cmd, check=True, timeout=WHISPER_TIMEOUT)
        with open(os.path.join(tmp, "downmix.json"), "r", encoding="utf-8") as f:
            data = json.load(f)
    words = []
    for segment in data.get("segments", []):
        for word in segment.get("words", []):
            try:
                start, end = float(word["start"]), float(word["end"])
            except (KeyError, TypeError, ValueError):
                continue
            text = (word.get("word") or "").strip()
            if text:
                words.append(_Word(text, start, end))
    return words


def run_downmix(input_dir, output_dir, initial_prompt):
    """Jokaisen ``.nhsx``:n miksaus kerran litteroituna: ``<nimi> downmix.md``."""
    found = sorted(f for f in os.listdir(input_dir) if f.lower().endswith(".nhsx"))
    # Alkuperäinen istunto ensin; vaimennettu vain jos muuta ei ole.
    sessions = [f for f in found if not f.lower().endswith("_processed.nhsx")] or found
    if not sessions:
        # Hiljainen onnistuminen ilman tulosta näyttäisi onnistuneelta ajolta.
        raise RuntimeError(
            f"Syötekansiosta {input_dir} ei löydy yhtään .nhsx-istuntoa. "
            "Downmix tarvitsee istunnon, ei pelkkiä äänitiedostoja."
        )
    for filename in sessions:
        path = os.path.join(input_dir, filename)
        clips, duration, missing = read_mix(path, input_dir)
        if missing:
            raise RuntimeError(
                "Miksaukseen tarvittavia äänitiedostoja ei löydy levyltä: "
                f"{', '.join(missing)}. Anna äänipoolin hakemisto."
            )
        print(f"Miksaus: {duration / 60:.1f} min — kootaan gaineilla…", flush=True)
        samples = gain_mix(clips, duration)
        print("Litteroidaan miksaus…", flush=True)
        words = transcribe_samples(samples, DOWNMIX_RATE, initial_prompt)
        if not words:
            print(
                "  VAROITUS: miksauksessa ei tunnistettu yhtään sanaa. "
                "Onko siinä puhetta, ja onko kieli oikein? Tiedostoa ei kirjoitettu.",
                flush=True,
            )
            continue
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, _swap_suffix(filename, ".nhsx", " downmix.md"))
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(paragraph_lines(words))
        print(f"Käsikirjoitus luotu: {output_path} ({len(words)} sanaa)", flush=True)


def main():
    parser = argparse.ArgumentParser(
        description="Hindenburg Litterointi ja Auto-Silence CLI"
    )
    parser.add_argument(
        "--preset",
        choices=["remote", "intra-mic"],
        default="remote",
        help="Valmis esiasetus leikkaukselle",
    )
    parser.add_argument(
        "--rms", action="store_true", help="Käytä äänenvoimakkuuden RMS-tarkistusta"
    )
    parser.add_argument(
        "--thr", type=int, default=-35, help="RMS-kynnysarvo desibeleinä (oletus: -35)"
    )
    parser.add_argument(
        "--tail", type=float, default=1.0, help="Häntäaika sekunteina (oletus: 1.0)"
    )
    parser.add_argument(
        "--gap", type=float, default=1.0, help="Minimitauko sekunteina (oletus: 1.0)"
    )
    parser.add_argument(
        "--prompt",
        type=str,
        default="öö, tota, niinku, mhm, joo, silleen, vähän, niinkun, ööh, ömm.",
        help="Whisper initial prompt täytesanoille",
    )
    parser.add_argument(
        "--no-silence",
        action="store_true",
        help="vain litterointi: Auto-Silence jätetään pois",
    )
    parser.add_argument(
        "--source",
        choices=["tracks", "downmix"],
        default="tracks",
        help="downmix: koko miksaus litteroidaan kerran ilman puhujia",
    )
    args = parser.parse_args()

    # Esiasetusten logiikka
    if args.preset == "remote":
        rms_enabled = args.rms if args.rms else False
        tail = args.tail if args.tail != 1.0 else 1.0
        gap = args.gap if args.gap != 1.0 else 1.0
        thr = args.thr
    elif args.preset == "intra-mic":
        rms_enabled = True
        tail = 0.4 if args.tail == 1.0 else args.tail
        gap = 0.4 if args.gap == 1.0 else args.gap
        thr = args.thr

    input_dir = "/content/input"
    output_dir = "/content/output"
    os.makedirs(input_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    print("[vaihe 1/4] Asennetaan riippuvuudet (apt ja pip)...", flush=True)
    install_dependencies()
    print("[vaihe 1/4] Riippuvuudet asennettu.", flush=True)
    if args.source == "downmix":
        run_downmix(input_dir, output_dir, args.prompt)
        print("\nKoko putki suoritettu onnistuneesti.", flush=True)
        return
    run_transcription(input_dir, output_dir, args.prompt)
    print("[vaihe 3/4] Injektoidaan litteroinnit .nhsx-rakenteeseen...", flush=True)
    generated_files = inject_transcriptions_to_nhsx(input_dir, output_dir)

    # Käsikirjoitus tehdään valmiista istunnosta: vaimennetusta, tai
    # litteroidusta kun vaimennus jätettiin pois.
    finished = list(generated_files)
    if args.no_silence:
        print("[vaihe 4/4] Auto-Silence ohitettu (vain litterointi).", flush=True)
        generated_files = []
    for idx, nhsx_file in enumerate(generated_files, 1):
        print(
            f"[vaihe 4/4 ({idx}/{len(generated_files)})] Suoritetaan Auto-Silence: {os.path.basename(nhsx_file)}...",
            flush=True,
        )
        run_auto_silence(nhsx_file, input_dir, rms_enabled, thr, tail, gap)
        finished[idx - 1] = _swap_suffix(nhsx_file, ".nhsx", "_processed.nhsx")
    for nhsx_file in finished:
        write_script(nhsx_file)

    print("\nKoko putki suoritettu onnistuneesti.", flush=True)


if __name__ == "__main__":
    main()
