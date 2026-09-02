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
    for node in elem.iter():
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


# 1. Asennetaan tarvittavat kirjastot pilviympäristössä
def install_dependencies():
    packages = ["CTranslate2", "whisper-ctranslate2", "lxml", "pydub"]
    subprocess.run(["apt-get", "update", "-qq"], check=True, timeout=APT_TIMEOUT)
    subprocess.run(["apt-get", "install", "-y", "-qq", "libcublas11", "ffmpeg"], check=True, timeout=APT_TIMEOUT)
    subprocess.run(["pip", "install", "-q", "-U", *packages], check=True, timeout=PIP_TIMEOUT)

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
    for dirpath, _, filenames in os.walk(input_dir):
        for filename in filenames:
            if filename.lower().endswith(AUDIO_EXTENSIONS):
                full_path = os.path.join(dirpath, filename)
                output_path = os.path.join(
                    transcripts_dir, _swap_audio_ext(filename, ".json")
                )

                if not os.path.isfile(output_path):
                    print(f"Litteroidaan tiedostoa: {full_path}")
                    cmd = [
                        "whisper-ctranslate2", full_path,
                        "--batched", "True",
                        "--compute_type", "auto",
                        "--word_timestamps", "True",
                        "--max_line_width", "33",
                        "--max_line_count", "2",
                        "--vad_filter", "True",
                        "--model", "turbo",
                        "--language", "fi",
                        "--initial_prompt", initial_prompt,
                        "--output_dir", transcripts_dir,
                        "--suppress_tokens", "",
                        "--suppress_blank", "False",
                        "--condition_on_previous_text", "False"
                    ]
                    subprocess.run(cmd, check=True, timeout=WHISPER_TIMEOUT)
                else:
                    print(f"Ohitetaan '{output_path}', se on jo litteroitu.")

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
                inside = os.path.commonpath([transcripts_root, srt_path]) == transcripts_root
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
        etree.ElementTree(xml_elems).write(out_file_path, encoding="UTF-8", xml_declaration=True)
        print(f"Litteroitu .nhsx luotu: {out_file_path}")
        generated_nhsx.append(out_file_path)

    return generated_nhsx

# 5. Auto-Silence -käsittely
def get_speech_intervals_for_track(tree, track_elem, audio_folder, rms_enabled, threshold):
    speech_on_timeline = []
    audio_pool = _first_named(tree, "AudioPool")
    if audio_pool is None:
        return []

    loaded_audio = {}
    if rms_enabled:
        from pydub import AudioSegment
    files_by_id = {fe.get("Id"): fe for fe in _iter_named(audio_pool, "File") if fe.get("Id")}
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
                        file_path = file_elem.get("Path", "")
                        abs_path = os.path.join(audio_folder, os.path.basename(file_path))
                        if abs_path not in loaded_audio and os.path.exists(abs_path):
                            print(f"      Analysoidaan audiota: {os.path.basename(abs_path)}...")
                            loaded_audio[abs_path] = AudioSegment.from_file(abs_path)

                        audio = loaded_audio.get(abs_path)
                        if audio is not None:
                            chunk = audio[int(ws * 1000): int((ws + wl) * 1000)]
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
        cuts = sorted({rs, re} | {z[0] for z in audible_zones if rs < z[0] < re} | {z[1] for z in audible_zones if rs < z[1] < re})

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
    print(f"RMS-tarkistus: {rms_enabled} (Kynnys: {threshold} dB) | Häntä: {tail}s | Tauko: {gap}s")

    for track in _iter_named(tree, "Track"):
        track_name = track.get("Name", "Nimetön")
        print(f"  Raita: {track_name}...")
        intervals = get_speech_intervals_for_track(tree, track, audio_folder, rms_enabled, threshold)
        print(f"    Säilytetty {len(intervals)} puhejaksoa.")
        process_track(track, intervals, tail, gap)

    tree.write(output_path, encoding="UTF-8", xml_declaration=True)
    print(f"Valmis käsitelty projekti: {output_path}")

def main():
    parser = argparse.ArgumentParser(description="Hindenburg Litterointi ja Auto-Silence CLI")
    parser.add_argument("--preset", choices=["remote", "intra-mic"], default="remote", help="Valmis esiasetus leikkaukselle")
    parser.add_argument("--rms", action="store_true", help="Käytä äänenvoimakkuuden RMS-tarkistusta")
    parser.add_argument("--thr", type=int, default=-35, help="RMS-kynnysarvo desibeleinä (oletus: -35)")
    parser.add_argument("--tail", type=float, default=1.0, help="Häntäaika sekunteina (oletus: 1.0)")
    parser.add_argument("--gap", type=float, default=1.0, help="Minimitauko sekunteina (oletus: 1.0)")
    parser.add_argument("--prompt", type=str, default="öö, tota, niinku, mhm, joo, silleen, vähän, niinkun, ööh, ömm.", help="Whisper initial prompt täytesanoille")
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

    install_dependencies()
    run_transcription(input_dir, output_dir, args.prompt)
    generated_files = inject_transcriptions_to_nhsx(input_dir, output_dir)

    for nhsx_file in generated_files:
        run_auto_silence(nhsx_file, input_dir, rms_enabled, thr, tail, gap)

    print("\nKoko putki suoritettu onnistuneesti.")

if __name__ == "__main__":
    main()
