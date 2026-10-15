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


def _file_digest(path):
    """Sisällön SHA-256, luettuna paloittain (tiedostot ovat satoja megoja)."""
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(8 * 1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def _duplicates_of(audio_items):
    """``{(hakemisto, nimi): (hakemisto, nimi)}`` jokaiselle tiedostolle jonka
    sisältö on sama kuin aiemmalla. Luetaan vain samankokoiset: koko on halpa
    ja riittää sulkemaan pois suurimman osan."""
    by_size = {}
    for item in audio_items:
        try:
            by_size.setdefault(os.path.getsize(os.path.join(*item)), []).append(item)
        except OSError:
            continue
    dupes = {}
    for group in by_size.values():
        if len(group) < 2:
            continue
        seen = {}
        for item in group:
            digest = _file_digest(os.path.join(*item))
            if digest in seen:
                dupes[item] = seen[digest]
            else:
                seen[digest] = item
    return dupes


# 3. Litterointi Faster-Whisperillä
def run_transcription(input_dir, output_dir, initial_prompt):
    transcripts_dir = os.path.join(output_dir, "transcripts")
    os.makedirs(transcripts_dir, exist_ok=True)
    audio_items = []
    for dirpath, _, filenames in os.walk(input_dir):
        for filename in filenames:
            if filename.lower().endswith(AUDIO_EXTENSIONS):
                audio_items.append((dirpath, filename))

    dupes = _duplicates_of(audio_items)
    total = len(audio_items)
    print(
        f"[vaihe 2/4] Litteroidaan äänitiedostot ({total} kpl, "
        f"{len(dupes)} samaa sisältöä uudelleen)...",
        flush=True,
    )

    for idx, (dirpath, filename) in enumerate(audio_items, 1):
        full_path = os.path.join(dirpath, filename)
        output_path = os.path.join(
            transcripts_dir, _swap_audio_ext(filename, ".json")
        )

        original = dupes.get((dirpath, filename))
        if original is not None:
            source_json = os.path.join(
                transcripts_dir, _swap_audio_ext(original[1], ".json")
            )
            if os.path.isfile(source_json) and not os.path.isfile(output_path):
                import shutil

                shutil.copyfile(source_json, output_path)
                print(
                    f"[vaihe 2/4 ({idx}/{total})] '{filename}' on sama äänitys kuin "
                    f"'{original[1]}': litterointi kopioitu.",
                    flush=True,
                )
                print(f"Litterointi luotu: {output_path}", flush=True)
                continue

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



def _injection_bleed(tree, pending, nhsx_path, input_dir):
    """Injektoitavista sanoista ``{(tiedosto-indeksi, sana-indeksi)}`` jotka ovat vuotoa.

    Tiedoston sana siirretään aikajanalle sen alueen kautta jonka ikkunassa se
    on; sana joka ei ole millään alueella (leikattu pois) jää, koska sitä ei
    voi verrata mihinkään. Vain litteroidut tiedostot ovat vertailussa, joten
    musiikkiraita ei tuki puhetta.
    """
    by_id = {fe.get("Id"): k for k, (fe, _) in enumerate(pending) if fe.get("Id")}
    regions = {}
    for track in _iter_named(tree, "Track"):
        name = track.get("Name", "")
        for region in _children_named(track, "Region"):
            k = by_id.get(region.get("Ref", ""))
            if k is None:
                continue
            regions.setdefault(name, []).append((
                time_to_seconds(region.get("Start", "0")),
                time_to_seconds(region.get("Length")),
                time_to_seconds(region.get("Offset", "0")),
                pending[k][0],
            ))
    items, where = [], []
    for name, regs in regions.items():
        for r_start, r_len, r_offset, file_elem in regs:
            k = by_id[file_elem.get("Id")]
            for n, (ws, we, _) in enumerate(pending[k][1]):
                if r_offset <= ws < r_offset + r_len:
                    items.append((name, file_elem, ws, we, r_start + ws - r_offset, r_start + we - r_offset))
                    where.append((k, n))
    if not items:
        return set()
    levels = _Levels(tree, _audio_dirs(tree, nhsx_path, input_dir))
    return {where[i] for i in _bleed_dropped(items, regions, levels)}


# 4. Injektoidaan litteroinnit .nhsx-rakenteeseen
def inject_transcriptions_to_nhsx(input_dir, output_dir, bleed_filter=True):
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

        pending = []  # (tiedosto, [(alku, loppu, teksti)])
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

            words = []
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
                    words.append((start, end, text))
            pending.append((file_elem, words))

        dropped = set()
        if bleed_filter:
            dropped = _injection_bleed(xml_elems, pending, nhsx_in_path, input_dir)
        for k, (file_elem, words) in enumerate(pending):
            transcription_elem = etree.SubElement(file_elem, "Transcription")
            p_elem = etree.SubElement(transcription_elem, "p")
            for n, (start, end, text) in enumerate(words):
                if (k, n) in dropped:
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
    tree, track_elem, audio_folder, rms_enabled, threshold,
    learn=False, calibration=None, audio_dirs=None, levels=None,
):
    """Raidan puhejaksot aikajanalla.

    ``learn``: käsin vaimennetun alueen sanat eivät avaa sitä (käyttäjän oma
    vaimennus on tosi, eikä Whisperin kuulema sana ole sitä vastaan), ja taso
    mitataan samalla mittarilla jolla kynnys opittiin (``_Levels``), ei
    pydubilla. ``calibration.threshold`` korvaa ``threshold``in; ilman sitä
    (ei opittu) raita ajetaan kiinteällä kynnyksellä.
    """
    speech_on_timeline = []
    audio_pool = _first_named(tree, "AudioPool")
    if audio_pool is None:
        return []

    loaded_audio = {}
    if learn:
        levels = levels or _Levels(tree, audio_dirs or [audio_folder])
        learned = calibration.threshold if calibration is not None else None
        limit = learned if learned is not None else threshold
    if rms_enabled and not learn:
        from pydub import AudioSegment
    files_by_id = {
        fe.get("Id"): fe for fe in _iter_named(audio_pool, "File") if fe.get("Id")
    }
    for region in _children_named(track_elem, "Region"):
        file_elem = files_by_id.get(region.get("Ref"))
        if file_elem is None:
            continue

        transcription = _first_named(file_elem, "Transcription")
        if learn and _hand_muted(region):
            continue
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

                    if learn:
                        level = levels.dbfs(file_elem, ws, ws + wl)
                        # Ääntä ei löydy: tiedon puute ei ole päätös vaientaa.
                        if level is not None and level < limit:
                            continue
                    elif rms_enabled:
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


def run_auto_silence(nhsx_path, audio_folder, rms_enabled, threshold, tail, gap,
                     learn=False):
    output_path = _swap_suffix(nhsx_path, ".nhsx", "_processed.nhsx")
    with open(nhsx_path, "r", encoding="utf-8") as f:
        raw = f.read()
    _reject_doctype(raw, os.path.basename(nhsx_path))
    tree = etree.ElementTree(etree.fromstring(raw.encode("utf-8"), _SAFE_PARSER))
    print(f"\nSuoritetaan Auto-Silence: {os.path.basename(nhsx_path)}")
    print(
        f"RMS-tarkistus: {rms_enabled} (Kynnys: {threshold} dB) | Häntä: {tail}s | Tauko: {gap}s"
    )

    levels = None
    calibrations = {}
    audio_dirs = _audio_dirs(tree, nhsx_path, audio_folder)
    if learn:
        rms_enabled = True
        levels = _Levels(tree, audio_dirs)
        calibrations = calibrate_tree(tree, audio_dirs, levels=levels)
        # Ilman yhtään vaimennettua aluetta ei ole mitä oppia, ja se sanotaan:
        # tulos olisi muuten tavallinen ajo vaikka valittu esiasetus lupasi
        # opitun kynnyksen.
        if not any(c.muted_seconds > 0 for c in calibrations.values()):
            raise RuntimeError(
                "Istunnossa ei ole yhtään käsin vaimennettua aluetta, josta "
                "kynnyksen voisi oppia. Avaa istunto Hindenburgissa, vaimenna "
                "alun minuutin tai parin kohdat joissa kukaan ei puhu, tallenna, "
                "ja aja uudestaan. Mitään ei kirjoitettu."
            )
        for name, found in calibrations.items():
            if found.threshold is not None:
                print(f"  {name}: kynnys {found.threshold:.1f} dBFS opittu "
                      f"{found.muted_seconds:.0f} sekunnista vaimennettua ääntä")
                if found.clamp_note:
                    print(f"    {found.clamp_note}")
            else:
                print(f"  {name}: kynnystä ei opittu ({found.reason}) — "
                      f"käytetään kiinteää {threshold} dB")

    for track in list(_iter_named(tree, "Track")):
        track_name = track.get("Name", "Nimetön")
        print(f"  Raita: {track_name}...")
        intervals = get_speech_intervals_for_track(
            tree, track, audio_folder, rms_enabled, threshold,
            learn=learn, calibration=calibrations.get(track_name),
            audio_dirs=audio_dirs, levels=levels,
        )
        print(f"    Säilytetty {len(intervals)} puhejaksoa.")
        process_track(track, intervals, tail, gap)

    tree.write(output_path, encoding="UTF-8", xml_declaration=True)
    print(f"Valmis käsitelty projekti: {output_path}")
    return output_path


# 5b. Opittu kynnys
#
# Kynnys opitaan siitä, mitä käyttäjä on istunnossa itse vaimentanut: ne
# alueet mitataan sanan mittaisilla ikkunoilla, ja kynnys on niiden tason
# korkea persentiili. Käyttäjä vaimentaa istunnon alun hiljaiset kohdat
# Hindenburgissa ENNEN ajoa — litterointi ei ole siihen tarpeen, koska ne
# luetaan vain äänestä.
#
# **Laskenta ei ole tässä tiedostossa.** Se on ``silencelearn``-kirjastossa,
# yksi tiedosto ja pelkkä standardikirjasto, jonka ajuri lataa tämän skriptin
# viereen (``driver.LEARN_MODULE``) ja jonka myös podcast-magic tuo. Tässä on
# vain se mikä on tämän skriptin: lxml-puu kirjaston syötteeksi ja ffmpeg
# sen tasokyselyille.
#
# Käyttöön otettu kirjasto laskee myös ero-rajan raitojen välillä
# (``Calibration.dominance``), mutta **tämä skripti ei käytä sitä**: täällä ei
# ole sanakohtaista vertailua toisiin raitoihin, joten rajalle ei ole
# paikkaa. Se on oma ominaisuutensa.
LEARN_RATE = 16000


def _hand_muted(region):
    """``Muted="True"`` alueella: käsin tai aiemmasta ajosta."""
    return str(region.get("Muted") or "").strip().lower() in ("1", "true")


def _decode_pcm16(path):
    """Tiedosto monoksi 16 kHz int16-taulukoksi, kuten podcast-magicin ``audio.decode_pcm``."""
    import numpy as np

    cmd = [
        "ffmpeg", "-nostdin", "-v", "error", "-i", str(path),
        "-f", "s16le", "-ac", "1", "-acodec", "pcm_s16le",
        "-ar", str(LEARN_RATE), "-",
    ]
    out = subprocess.run(cmd, check=True, capture_output=True, timeout=WHISPER_TIMEOUT).stdout
    return np.frombuffer(out, np.int16)


def _dbfs(samples, start, end):
    """Jakson RMS desibeleinä täydestä asteikosta; tyhjä jakso on -inf."""
    import numpy as np

    a = max(0, int(start * LEARN_RATE))
    b = min(len(samples), int(end * LEARN_RATE))
    if b <= a:
        return float("-inf")
    chunk = samples[a:b].astype(np.float64)
    if samples.dtype == np.int16:
        chunk /= 32768.0
    rms = float(np.sqrt(np.mean(np.square(chunk))))
    if rms <= 0.0:
        return float("-inf")
    return 20.0 * float(np.log10(rms))


def _audio_dirs(tree, nhsx_path, audio_folder):
    """Hakemistot joista äänitiedostoja etsitään: annettu, äänipooli, istunto."""
    pool = _first_named(tree, "AudioPool")
    session_dir = os.path.dirname(os.path.abspath(nhsx_path))
    pool_path = (pool.get("Path") or "").strip() if pool is not None else ""
    pool_dir = os.path.join(session_dir, pool_path) if pool_path else session_dir
    return [d for d in (audio_folder, pool_dir, session_dir) if d]


class _Levels:
    """Sanat ja tasot tiedostoittain: ``silencelearn.Source`` tälle skriptille.

    Jokainen tiedosto puretaan kerran ja pidetään muistissa, ilman kattoa:
    kynnys vertaa jokaisen ikkunan kohdalla myös muita raitoja, ja kolmella
    raidalla kahden tiedoston katto purkaisi joka haun uudestaan. Colabissa
    on muistia: tunti 16 kHz:llä on 115 MB int16:na.
    """

    def __init__(self, tree, audio_dirs):
        pool = _first_named(tree, "AudioPool")
        self.files = {}
        if pool is not None:
            self.files = {fe.get("Id"): fe for fe in _iter_named(pool, "File")
                          if fe.get("Id")}
        self.audio_dirs = audio_dirs
        self._samples = {}
        self._missing = set()

    def samples(self, file_elem):
        key = file_elem.get("Id")
        if key not in self._samples:
            raw = file_elem.get("Path") or file_elem.get("Name", "")
            name = os.path.basename(raw) or file_elem.get("Name", "")
            path = _locate(raw, name, self.audio_dirs)
            found = None
            if path:
                try:
                    found = _decode_pcm16(path)
                except Exception:
                    # Rikki tai puuttuva ääni ei kaada ajoa: muut raidat
                    # käsitellään silti.
                    found = None
            if found is None:
                self._missing.add(name)
            self._samples[key] = found
        return self._samples[key]

    def dbfs(self, file_elem, start, end):
        """Taso tiedoston ajassa; ``None`` jos ääntä ei ole. Lattia on kirjaston."""
        samples = self.samples(file_elem)
        if samples is None:
            return None
        return _dbfs(samples, start, end)

    # silencelearn.Source
    def words(self, ref):
        file_elem = self.files.get(ref)
        transcription = (_first_named(file_elem, "Transcription")
                         if file_elem is not None else None)
        if transcription is None:
            return []
        return [(time_to_seconds(w.get("s")), time_to_seconds(w.get("l")))
                for w in _iter_named(transcription, "w") if (w.text or "").strip()]

    def level(self, ref, start, end):
        file_elem = self.files.get(ref)
        return None if file_elem is None else self.dbfs(file_elem, start, end)

    def missing(self):
        return bool(self._missing)


def calibrate_tree(tree, audio_dirs, levels=None):
    """Raita -> ``silencelearn.Calibration``. Raidalla jolla ei ole opittavaa on syy."""
    import silencelearn

    levels = levels or _Levels(tree, audio_dirs)
    tracks = [
        silencelearn.Track(
            track.get("Name", "Nimetön"),
            [silencelearn.Region(
                region.get("Ref", ""),
                time_to_seconds(region.get("Start")),
                time_to_seconds(region.get("Length")),
                time_to_seconds(region.get("Offset", "0")),
                _hand_muted(region),
            ) for region in _children_named(track, "Region")],
        )
        for track in _iter_named(tree, "Track")
    ]
    return silencelearn.calibrate(tracks, levels)


# 6. Käsikirjoitus valmiista istunnosta
def _stamp(seconds):
    total = int(seconds)
    return f"[{total // 60:02d}:{total % 60:02d}]"


def _script_lines(entries):
    """Alueet kappaleiksi. Snapshot podcast-magicin `script/core.py`:n
    `_render`istä (sama koodi, ei muuta).

    Toisen puhujan alue, joka alkaa tämän sisällä ja päättyy ennen sen
    loppua, katkaisee kappaleen; kappale jatkuu jatkuvan sanan aikaleimalla.
    Saman puhujan peräkkäiset palat yhtyvät.
    """
    entries = sorted(entries, key=lambda entry: entry[0])
    pieces = []
    for start, name, words in entries:
        first, last = words[0][0], words[-1][1]
        cuts = sorted(
            other[0][0]
            for _, other_name, other in entries
            if other_name != name and first < other[0][0] and other[-1][1] <= last
        )
        position = 0
        for cut in [*cuts, float("inf")]:
            end = position
            while end < len(words) and words[end][0] < cut:
                end += 1
            bit = words[position:end]
            if bit:
                pieces.append((start if position == 0 else bit[0][0], name,
                               [w[2] for w in bit]))
            position = end
    pieces.sort(key=lambda piece: piece[0])

    merged = []
    for start, name, texts in pieces:
        if merged and merged[-1][1] == name:
            merged[-1][2].extend(texts)
        else:
            merged.append((start, name, list(texts)))
    return [f"{_stamp(start)} **{name}:** {' '.join(texts)}" for start, name, texts in merged]


#: Sana kuuluu toiselle raidalle, jos se on omaan puhetasoonsa nähden vähintään
#: näin monta dB kovempi kuin sanan oma raita. Mitattu (2 mikkiä, 47 min,
#: ``08 alma kai telanne``): A–B-ero suhteutettuna kahden raidan p90-tasoon on
#: kaksihuippuinen, vain 1,7 % puheruuduista on alle ±8 dB:n sisällä ja vuoto
#: on 27–28 dB oman puheen alla. 6 dB on keskellä leveää laaksoa, ei tarkka luku.
BLEED_MARGIN_DB = 6.0
#: Raja lasketaan ajossa: neljäsosa siitä kuinka paljon kovempaa oma puhe on
#: kuin vuoto (mediaani selvistä sanoista), 3-12 dB:n väliin. Jakaja 4 on se
#: jolla mitattu 27 dB antaa lähes saman kuin ylläoleva 6 dB (6,8 dB); kiinteä
#: luku jää varaksi kun mittaukseen ei ole tarpeeksi sanoja.
BLEED_DEPTH_DIVISOR = 4.0
BLEED_MARGIN_MIN_DB = 3.0
BLEED_MARGIN_MAX_DB = 12.0


def _bleed_dropped(items, regions, levels):
    """Indeksit joiden sana on toisen mikin vuotoa.

    Kaksi mikkiä kuulee molemmat puhujat, ja Whisper litteroi vuodon kummallakin
    raidalla: sama puhe näkyisi jokaisen puhujan alla. ``items`` on
    ``(raita, tiedosto, tiedosto-alku, tiedosto-loppu, aikajana-alku,
    aikajana-loppu)``; taso mitataan sanan ajalta ja suhteutetaan raidan omaan
    puhetasoon (p90 omista sanoista), koska mikit ovat eri vahvistuksella.
    Sana pudotetaan vain jos toinen raita on selvästi kovempi; päällekkäinen
    puhe jää kummallekin.
    """
    import numpy as np

    if len({it[0] for it in items}) < 2:
        return set()
    own = [levels.dbfs(it[1], it[2], it[3]) for it in items]
    by_track = {}
    for it, db in zip(items, own, strict=True):
        if db is not None and np.isfinite(db):
            by_track.setdefault(it[0], []).append(db)
    baseline = {n: float(np.percentile(v, 90)) for n, v in by_track.items() if len(v) >= 3}
    if len(baseline) < 2:
        return set()

    def other_level(track, t0, t1):
        best = float("-inf")
        mid = (t0 + t1) / 2
        for name, regs in regions.items():
            if name == track or name not in baseline:
                continue
            for r_start, r_len, r_offset, file_elem in regs:
                if r_start <= mid < r_start + r_len:
                    db = levels.dbfs(file_elem, r_offset + t0 - r_start, r_offset + t1 - r_start)
                    if db is not None and np.isfinite(db):
                        best = max(best, db - baseline[name])
                    break
        return best

    # Jokaiselle sanalle: kuinka paljon oma taso ylittää kovimman muun raidan
    # (suhteutettuna). Oma puhe on selvästi positiivista, vuoto yhtä selvästi
    # negatiivista; sama etäisyys kertoo kuinka syvä vuoto on.
    spread = {}
    for i, (it, db) in enumerate(zip(items, own, strict=True)):
        if it[0] not in baseline or db is None or not np.isfinite(db):
            continue
        other = other_level(it[0], it[4], it[5])
        if np.isfinite(other):
            spread[i] = (db - baseline[it[0]]) - other
    clear = [x for x in spread.values() if x > 2.0]
    if len(clear) >= 2:
        depth = float(np.median(clear))
        margin = min(max(depth / BLEED_DEPTH_DIVISOR, BLEED_MARGIN_MIN_DB), BLEED_MARGIN_MAX_DB)
        print(f"Vuodon raja: oma puhe {depth:.1f} dB vuotoa kovempaa, raja {margin:.1f} dB.",
              flush=True)
    else:
        margin = BLEED_MARGIN_DB
        print(f"Vuodon raja: liian vähän selviä sanoja mittaukseen, käytetään {margin:.1f} dB.",
              flush=True)
    return {i for i, x in spread.items() if -x > margin}


def _drop_bleed(entries, meta, regions, tree, audio_dirs):
    """Skriptin sanat ilman vuotoa: ``entries`` samassa muodossa kuin ennen."""
    items, where = [], []
    for i, (_, name, words) in enumerate(entries):
        file_elem, start, offset = meta[i]
        for j, (ws, we, _) in enumerate(words):
            items.append((name, file_elem, offset + ws - start, offset + we - start, ws, we))
            where.append((i, j))
    dropped = {where[k] for k in _bleed_dropped(items, regions, _Levels(tree, audio_dirs))}
    kept = []
    for i, (start, name, words) in enumerate(entries):
        words = [w for j, w in enumerate(words) if (i, j) not in dropped]
        if words:
            kept.append((start, name, words))
    return kept


def write_script(nhsx_path, audio_dirs=None):
    """Istunnosta luettava `.md` sen viereen: yksi kappale per puheenvuoro.

    **Snapshot** podcast-magicin `script/core.py`:stä, koska tämä skripti ei
    voi tuoda työtilaa (ks. CLAUDE.md). Raidan nimi on puhujan nimi,
    peräkkäiset alueet samalta raidalta ovat yksi vuoro (toisen puhujan
    lyhyt huomautus katkaisee vuoron, ks. `_script_lines`), aikaleima on vuoron
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
    meta = []  # entries-rivin tiedosto, alue-alku ja offset: tasomittausta varten
    regions = {}
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
            regions.setdefault(name, []).append((start, length, offset, file_elem))
            words = []
            for word in _iter_named(transcription, "w"):
                text = (word.text or "").strip()
                if not text:
                    continue
                ws = time_to_seconds(word.get("s"))
                we = ws + time_to_seconds(word.get("l"))
                if ws < offset + length and we > offset:
                    words.append((start + ws - offset, start + we - offset, text))
            if words:  # musiikkiraita ja tyhjä alue eivät ole käsikirjoitusta
                entries.append((start, name, words))
                meta.append((file_elem, start, offset))

    if audio_dirs:
        entries = _drop_bleed(entries, meta, regions, tree, audio_dirs)
    lines = _script_lines(entries)
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
        choices=["remote", "intra-mic", "learned"],
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
        "--no-bleed-filter",
        action="store_true",
        help="kirjoita istuntoon myös toisen mikin vuoto",
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
    learn = False
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
    elif args.preset == "learned":
        # Kynnys opitaan käsin vaimennetuista alueista (``--thr`` on varalla
        # raidalle jolta opittavaa ei löydy).
        rms_enabled = True
        learn = True
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
    generated_files = inject_transcriptions_to_nhsx(
        input_dir, output_dir, bleed_filter=not args.no_bleed_filter
    )

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
        run_auto_silence(nhsx_file, input_dir, rms_enabled, thr, tail, gap,
                         **({"learn": True} if learn else {}))
        finished[idx - 1] = _swap_suffix(nhsx_file, ".nhsx", "_processed.nhsx")
    for nhsx_file in finished:
        write_script(nhsx_file)

    print("\nKoko putki suoritettu onnistuneesti.", flush=True)


if __name__ == "__main__":
    main()
