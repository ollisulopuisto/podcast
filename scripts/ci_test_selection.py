"""Choose test suites affected by a set of changed repository paths."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tomllib
from collections.abc import Iterable
from pathlib import Path

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


def select_lock_suites(before: dict, after: dict) -> dict[str, list[str]]:
    """Trace changed records through both dependency graphs, failing closed.

    Include optional/dev dependencies and all marker alternatives. A removed
    edge must still reach its former consumer, hence traversal of both locks.
    """
    if {k: v for k, v in before.items() if k != "package"} != {
        k: v for k, v in after.items() if k != "package"
    }:
        return select_suites([], full=True)

    def records(lock):
        result = {}
        for package in lock.get("package", []):
            result.setdefault(package["name"], []).append(package)
        return result

    old, new = records(before), records(after)
    changed = {name for name in old.keys() | new.keys() if old.get(name) != new.get(name)}
    reverse = {}
    workspace = {}
    for lock in (before, after):
        for package in lock.get("package", []):
            name = package["name"]
            source = package.get("source", {})
            path = source.get("editable") or source.get("virtual")
            if path:
                workspace[name] = path.rstrip("/") + "/"
            dependencies = list(package.get("dependencies", []))
            for group in ("optional-dependencies", "dev-dependencies"):
                for entries in package.get(group, {}).values():
                    dependencies.extend(entries)
            for dependency in dependencies:
                reverse.setdefault(dependency["name"], set()).add(name)
    paths = set()
    for name in changed:
        pending, visited, reached = [name], set(), False
        while pending:
            current = pending.pop()
            if current in visited:
                continue
            visited.add(current)
            if current in workspace:
                paths.add(workspace[current])
                reached = True
            pending.extend(reverse.get(current, ()))
        if not reached:
            return select_suites([], full=True)
    return select_suites(paths)


def select_changes(paths, base=None):
    """Use lock semantics only when both revisions can be read safely."""
    paths = list(paths)
    if "uv.lock" not in paths or not base:
        return select_suites(paths)
    try:
        before = tomllib.loads(subprocess.check_output(
            ["git", "show", f"{base}:uv.lock"], text=True
        ))
        after = tomllib.loads(Path("uv.lock").read_text())
        locked = select_lock_suites(before, after)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        return select_suites([], full=True)
    other = select_suites(path for path in paths if path != "uv.lock")
    return {
        platform: ["all"] if "all" in locked[platform] + other[platform]
        else sorted(set(locked[platform] + other[platform]))
        for platform in ALL
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", help="base commit used for semantic lock comparison")
    parser.add_argument("--all", action="store_true", help="select every suite")
    args = parser.parse_args()
    selection = select_suites([], full=True) if args.all else select_changes(
        sys.stdin.read().splitlines(), args.base
    )
    encoded = json.dumps(selection, separators=(",", ":"))
    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a", encoding="utf-8") as output:
            for platform, suites in selection.items():
                output.write(f"{platform}={json.dumps(suites, separators=(',', ':'))}\n")
    print(encoded)


if __name__ == "__main__":
    main()
