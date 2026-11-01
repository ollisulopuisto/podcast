"""Choose test suites affected by a set of changed repository paths."""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Iterable

ALL = {"linux": ["all"], "macos": ["all"]}

APP_SUITES = {
    "apps/autoraffkat/": {"linux": set(), "macos": {"autoraffkat"}},
    "apps/automixer/": {"linux": {"automixer"}, "macos": {"automixer"}},
    "apps/podcast-magic/": {
        "linux": {"podcast-magic"},
        "macos": {"podcast-magic"},
    },
    "colab-transcribe/": {"linux": {"colab-transcribe"}, "macos": set()},
    "apps/fcp-subs-whisper/": {
        "linux": {"fcp-subs-whisper"},
        "macos": set(),
    },
}

LIBRARY_SUITES = {
    "packages/speechmix/": {
        "linux": {"speechmix", "automixer", "podcast-magic"},
        "macos": {"speechmix", "autoraffkat", "automixer", "podcast-magic"},
    },
    "packages/nhsx/": {
        "linux": {"nhsx", "automixer", "podcast-magic"},
        "macos": {"automixer", "podcast-magic"},
    },
    "packages/silencelearn/": {
        "linux": {"silencelearn", "colab-transcribe", "podcast-magic"},
        "macos": {"podcast-magic"},
    },
    "packages/wordalign/": {
        "linux": {"wordalign", "colab-transcribe", "podcast-magic"},
        "macos": {"podcast-magic"},
    },
    "packages/framescore/": {
        "linux": {"framescore"},
        "macos": set(),
    },
    "packages/fcpxml/": {
        "linux": {"fcpxml"},
        "macos": {"autoraffkat"},
    },
}

GLOBAL_PATHS = (
    ".github/workflows/",
    "pyproject.toml",
    "uv.lock",
    "tests/",
    "scripts/",
)
DOC_PATHS = (
    "docs/",
    "README.md",
    "CONTRIBUTING.md",
    "CLAUDE.md",
    "AGENTS.md",
    ".github/ISSUE_TEMPLATE/",
)


def select_suites(paths: Iterable[str], *, full: bool = False) -> dict[str, list[str]]:
    """Return sorted Linux and macOS suites required by ``paths``.

    Unknown non-documentation paths conservatively select all suites. Shared
    package changes also select their application consumers on each platform.
    """
    if full:
        return {platform: suites.copy() for platform, suites in ALL.items()}

    selected = {"linux": set(), "macos": set()}
    for path in paths:
        if path.startswith(GLOBAL_PATHS):
            return {platform: suites.copy() for platform, suites in ALL.items()}

        match = next(
            (mapping for prefix, mapping in APP_SUITES.items() if path.startswith(prefix)),
            None,
        )
        if match is None:
            match = next(
                (mapping for prefix, mapping in LIBRARY_SUITES.items() if path.startswith(prefix)),
                None,
            )
        if match is not None:
            for platform in selected:
                selected[platform].update(match[platform])
        elif not path.startswith(DOC_PATHS):
            return {platform: suites.copy() for platform, suites in ALL.items()}

    return {platform: sorted(suites) for platform, suites in selected.items()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true", help="select every suite")
    args = parser.parse_args()
    selection = select_suites(sys.stdin.read().splitlines(), full=args.all)
    encoded = json.dumps(selection, separators=(",", ":"))
    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a", encoding="utf-8") as output:
            for platform, suites in selection.items():
                output.write(f"{platform}={json.dumps(suites, separators=(',', ':'))}\n")
    print(encoded)


if __name__ == "__main__":
    main()
