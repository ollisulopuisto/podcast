"""The reader installs into autoraffkat and into kuulas with nothing else.

Neither app may be forced to take the other's dependencies to read an export,
so this package imports the standard library and itself, and nothing more.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "src" / "fcpxml"


def _imported_roots(path: Path) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_the_library_imports_nothing_but_the_standard_library():
    modules = sorted(SOURCE.glob("*.py"))
    assert modules, "found no source to check"
    stray = {
        path.name: sorted(_imported_roots(path) - set(sys.stdlib_module_names) - {"fcpxml"})
        for path in modules
    }
    assert {name: roots for name, roots in stray.items() if roots} == {}
