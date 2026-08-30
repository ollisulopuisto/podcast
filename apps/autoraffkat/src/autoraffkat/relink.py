"""Puuttuvien mediatiedostojen uudelleenlinkitys (relinking).

Jos FCPXML osoittaa vanhoihin tai siirrettyihin polkuihin (esim. eri kone,
siirretty kansio tai Dropbox-polun muutos), etsitään vastaavat tiedostot
älykkäästi ja sumeasti (fuzzy matching) XML:n läheltä ja käyttäjän antamista
hakemistoista.
"""

from __future__ import annotations

import difflib
import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.request import pathname2url

if TYPE_CHECKING:
    from .fcpxml.read import Timeline
    from .model import MediaItem

# Mediatiedostojen tyypilliset päätteet
AUDIO_EXTENSIONS = {".wav", ".aif", ".aiff", ".m4a", ".mp3", ".flac", ".aac", ".ogg", ".caf"}
VIDEO_EXTENSIONS = {".mov", ".mp4", ".m4v", ".mkv", ".avi", ".mts", ".m2ts", ".braw", ".r3d"}
MEDIA_EXTENSIONS = AUDIO_EXTENSIONS | VIDEO_EXTENSIONS

# Hakemistot joita ei skannata
IGNORE_DIRS = {
    ".git", ".svn", ".hg", ".venv", "venv", "node_modules", "__pycache__",
    ".fcpbundle", ".Spotlight-V100", ".Trashes", ".cache", ".gemini"
}

# Poistettavat lisäkkeet ja tagit
VARIANT_SUFFIX_RE = re.compile(
    r"(\s*\[(mix|cut|master|raw|audio)\]|\s*\((mix|cut|master|raw|audio)\)|[_\-\s]+(mix|cut|master|raw|audio))",
    re.IGNORECASE
)


def file_url(path: str) -> str:
    """Tiedostopolku file-URLiksi."""
    url = pathname2url(os.path.abspath(path))
    return "file:" + url if url.startswith("//") else "file://" + url


def normalize_stem(stem: str) -> str:
    """Normalisoi tiedostonimen kanta vertailua varten."""
    text = unicodedata.normalize("NFKD", stem).casefold()
    text = VARIANT_SUFFIX_RE.sub("", text)
    # Korvaa erottimet välilyönnillä
    return re.sub(r"[\s_\.\-\[\]\(\)]+", " ", text).strip()


def extract_tokens_and_discriminators(stem: str) -> tuple[set[str], set[str]]:
    """Erottaa sanat ja kriittiset erottimet (kuten osakirjaimet a/b tai numerot 1/2)."""
    norm = normalize_stem(stem)
    tokens = set(norm.split())
    discriminators = set()
    for tok in tokens:
        # Yksittäiset kirjaimet (osat a, b, c) tai numerot (1, 2, 53)
        if (len(tok) == 1 and tok.isalpha()) or tok.isdigit() or (tok.startswith("track") and len(tok) <= 8):
            discriminators.add(tok)
    return tokens, discriminators


@dataclass
class IndexedFile:
    """Yksi indeksoitu tiedosto levyllä."""
    path: Path
    name: str
    stem: str
    ext: str
    norm_stem: str
    tokens: set[str]
    discriminators: set[str]


class DirectoryIndex:
    """Hakemistopuun välimuistillinen tiedostoindeksi."""

    def __init__(self, roots: list[Path], max_depth: int = 4) -> None:
        self.roots = [r.resolve() for r in roots if r.exists()]
        self.files: list[IndexedFile] = []
        self._by_name: dict[str, list[IndexedFile]] = {}
        self._by_norm: dict[str, list[IndexedFile]] = {}
        self._scanned = False
        self.max_depth = max_depth

    def scan(self) -> None:
        if self._scanned:
            return
        self._scanned = True
        seen_paths: set[Path] = set()

        for root in self.roots:
            if root.is_file():
                self._add_file(root, seen_paths)
                continue
            if not root.is_dir():
                continue

            root_depth = len(root.parts)
            try:
                for dirpath, dirnames, filenames in os.walk(root):
                    dp = Path(dirpath)
                    # Suodata pois ohitettavat hakemistot
                    dirnames[:] = [
                        d for d in dirnames
                        if not d.startswith(".") and d not in IGNORE_DIRS
                        and (len(Path(dirpath, d).parts) - root_depth) <= self.max_depth
                    ]
                    for fn in filenames:
                        if fn.startswith("."):
                            continue
                        fpath = dp / fn
                        self._add_file(fpath, seen_paths)
            except OSError:
                continue

    def _add_file(self, fpath: Path, seen_paths: set[Path]) -> None:
        resolved = fpath.resolve()
        if resolved in seen_paths:
            return
        seen_paths.add(resolved)
        ext = fpath.suffix.lower()
        # Otetaan huomioon mediatiedostot tai kaikki tiedostot
        name = fpath.name
        stem = fpath.stem
        norm = normalize_stem(stem)
        tokens, disc = extract_tokens_and_discriminators(stem)

        item = IndexedFile(
            path=resolved,
            name=name,
            stem=stem,
            ext=ext,
            norm_stem=norm,
            tokens=tokens,
            discriminators=disc,
        )
        self.files.append(item)
        self._by_name.setdefault(name.casefold(), []).append(item)
        self._by_norm.setdefault(norm, []).append(item)


def find_search_roots(
    xml_path: str = "",
    known_paths: list[str] | None = None,
    extra_dir: str | Path | None = None,
) -> list[Path]:
    """Kerää priorisoidun listan etsintähakemistoja."""
    roots: list[Path] = []
    seen: set[str] = set()

    def add(p: str | Path | None) -> None:
        if not p:
            return
        path = Path(p).resolve()
        # Käytetään casefoldia deduplikointiin macOS:llä
        s = str(path).casefold()
        if s not in seen and path.exists():
            seen.add(s)
            roots.append(path)

    if extra_dir:
        add(extra_dir)

    if xml_path:
        xp = Path(xml_path).resolve()
        xdir = xp.parent if xp.is_file() else xp
        add(xdir)

        # Jos XML on .fcpxmld-paketissa (esim. jakso.fcpxmld/Info.fcpxml),
        # lisätään paketin sisältävä jaksohakemisto
        if xdir.suffix.lower() == ".fcpxmld":
            add(xdir.parent)

    if known_paths:
        for kp in known_paths:
            if kp:
                p = Path(kp)
                if p.parent.exists():
                    add(p.parent)

    return roots


def score_candidate(
    cand: IndexedFile,
    target_name: str,
    target_stem: str,
    target_ext: str,
    target_norm: str,
    target_tokens: set[str],
    target_disc: set[str],
    target_rel_parts: list[str],
) -> float:
    """Laskee ehdokkaan yhteensopivuuspisteet (0.0 - 1.2)."""
    # 1. Kriittinen tarkistus: erottimet (part A/B, track 1/2) eivät saa olla ristiriidassa
    if target_disc:
        # Jos targetissa on erottimia, ehdokkaassa on oltava samat eikä ristiriitaisia
        # Esim. jos targetissa 'a', candissa ei saa olla 'b'
        for disc in target_disc:
            if disc not in cand.discriminators and disc not in cand.tokens:
                # Jos kriittinen erotin puuttuu kokonaan
                return 0.0
        # Ristiriitatarkistus:
        for disc in cand.discriminators:
            if len(disc) == 1 and disc.isalpha() and disc not in target_disc:
                # Kandidaatilla on eri osakirjain kuin targetilla
                return 0.0

    # 2. Tarkka nimitäsmäys
    if cand.name.casefold() == target_name.casefold():
        score = 1.0
    # 3. Tarkka kanta eri päätteellä
    elif cand.stem.casefold() == target_stem.casefold():
        score = 0.95
    # 4. Normalisoitu kanta (esim. [mix] poistettu tai lisätty)
    elif cand.norm_stem == target_norm:
        score = 0.90
    else:
        # 5. Sumea merkkijono- ja token-vertailu
        if not target_tokens:
            return 0.0
        common = target_tokens & cand.tokens
        if not common:
            return 0.0
        jaccard = len(common) / len(target_tokens | cand.tokens)
        seq_ratio = difflib.SequenceMatcher(None, target_norm, cand.norm_stem).ratio()
        fuzzy = 0.5 * jaccard + 0.5 * seq_ratio
        if fuzzy < 0.65:
            return 0.0
        score = 0.80 * fuzzy

    # Lisäpisteet:
    # Päätteen yhteensopivuus
    if cand.ext == target_ext:
        score += 0.05
    elif (cand.ext in AUDIO_EXTENSIONS and target_ext in AUDIO_EXTENSIONS) or (
        cand.ext in VIDEO_EXTENSIONS and target_ext in VIDEO_EXTENSIONS
    ):
        score += 0.02

    # Polkurakenteen sukulaisuus (esim. molemmat alihakemistossa 'vertailu' / 'B-lufs20')
    cand_parts = [p.casefold() for p in cand.path.parts]
    for rel_p in target_rel_parts:
        if rel_p.casefold() in cand_parts:
            score += 0.03

    return score


def relink_file(
    missing_path: str,
    search_roots: list[Path | str],
    index: DirectoryIndex | None = None,
) -> str | None:
    """Etsii puuttuvalle tiedostolle parhaan korvaavan polun levyltä."""
    if not missing_path:
        return None
    if os.path.exists(missing_path):
        return os.path.abspath(missing_path)

    roots = [Path(r) for r in search_roots]
    if index is None:
        index = DirectoryIndex(roots)
    index.scan()

    orig_p = Path(missing_path)
    target_name = orig_p.name
    target_stem = orig_p.stem
    target_ext = orig_p.suffix.lower()
    target_norm = normalize_stem(target_stem)
    target_tokens, target_disc = extract_tokens_and_discriminators(target_stem)
    target_rel_parts = [p for p in orig_p.parts[-4:-1] if p]

    # 1. Tarkista suorat suhteelliset polut kunkin juuren alta
    for root in index.roots:
        if root.is_dir():
            # Yritetään eri suhteellisia pituuksia (esim. vertailu/B-lufs20/file.wav, B-lufs20/file.wav, file.wav)
            for i in range(1, min(len(orig_p.parts), 5)):
                sub_rel = Path(*orig_p.parts[-i:])
                candidate_path = root / sub_rel
                if candidate_path.exists() and candidate_path.is_file():
                    return str(candidate_path.resolve())

    # 2. Etsi indeksistä parhaat ehdokkaat
    best_candidate: IndexedFile | None = None
    best_score = 0.70  # Minimitulos hyväksymiselle

    # Tarkistetaan ensin nopeat suorat indeksit
    direct_hits = index._by_name.get(target_name.casefold()) or []
    if not direct_hits:
        direct_hits = index._by_norm.get(target_norm) or []

    candidates_to_score = direct_hits if direct_hits else index.files

    for cand in candidates_to_score:
        score = score_candidate(
            cand,
            target_name=target_name,
            target_stem=target_stem,
            target_ext=target_ext,
            target_norm=target_norm,
            target_tokens=target_tokens,
            target_disc=target_disc,
            target_rel_parts=target_rel_parts,
        )
        if score > best_score:
            best_score = score
            best_candidate = cand

    if best_candidate is not None:
        return str(best_candidate.path)

    return None


def relink_timeline(
    timeline: "Timeline",
    search_dir: str | Path | None = None,
    xml_path: str = "",
) -> dict[str, str]:
    """Uudelleenlinkittää kaikki Timeline-olion puuttuvat mediat.

    Palauttaa sanakirjan {media_key: uusi_polku} onnistuneista linkityksistä.
    """
    missing_items: list[MediaItem] = [
        m for m in timeline.media
        if not m.path or not os.path.exists(m.path)
    ]
    if not missing_items:
        return {}

    source_path = xml_path or timeline.source_path
    known_paths = [m.path for m in timeline.media if m.path]
    roots = find_search_roots(
        xml_path=source_path,
        known_paths=known_paths,
        extra_dir=search_dir,
    )
    index = DirectoryIndex(roots)
    index.scan()

    relinked: dict[str, str] = {}
    for item in missing_items:
        found = relink_file(item.path or item.name, roots, index=index)
        if found and os.path.exists(found):
            relinked[item.key] = found
            item.path = found
            item.src = file_url(found)
            # Jos nimi oli tyhjä, päivitetään
            if not item.name:
                item.name = os.path.basename(found)
            print(f"[relink] {item.key} -> {found}", flush=True)

    return relinked
