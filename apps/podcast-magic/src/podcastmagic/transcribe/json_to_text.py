"""Whisperin JSON litteroinnista luettava markdown.

Podcast Magic tallentaa litteroinnin raakana Whisper-JSONina istunnon
viereen — se on levyltä luettava välimuisti, mutta sellaisenaan se on
koneelle. Tämä tekee siitä ihmisen: segmentit riveinä, aikaleima
``hh:mm:ss`` ja teksti perässä.

Lähde on sama muoto jota ``whisper-timestamped`` ja molemmat moottorit
tuottavat, joten tämä lukee myös vanhat Colab-ajojen JSONit.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..nhsx.write import next_free_path


def json_to_text(data: dict) -> str:
    """Segmentit markdown-riveinä. Tyhjä teksti ei ole rivi."""
    out: list[str] = []
    for segment in data.get("segments") or ():
        text = str(segment.get("text", "")).strip()
        if not text:
            continue
        start = int(segment.get("start", 0.0))
        stamp = f"**{start // 3600:02d}:{(start // 60) % 60:02d}:{start % 60:02d}**"
        # Kappalevälit: kaksi rivinvaihtoa, kuten vanhassa skriptissä.
        out.append(f"{stamp} {text}\n")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="json-to-text",
        description="Whisperin JSON-litterointi luettavaksi markdowniksi.",
    )
    parser.add_argument("json_file", help="Whisperin JSON-tiedosto")
    parser.add_argument(
        "-o", "--output", help="kohdetiedosto (oletus: JSONin viereen .md:nä)"
    )
    args = parser.parse_args(argv)

    try:
        data = json.loads(Path(args.json_file).read_text(encoding="utf-8"))
    except OSError as exc:
        print(f"Tiedostoa ei voi lukea: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"Ei ole JSONia: {exc}", file=sys.stderr)
        return 2

    text = json_to_text(data)
    target = Path(args.output) if args.output else next_free_path(
        Path(args.json_file).with_suffix(".md")
    )
    target.write_text(text, encoding="utf-8")
    print(f"{target.name}: {len([line for line in text.splitlines() if line])} segmenttiä")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
