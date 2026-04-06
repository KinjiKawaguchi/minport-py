"""Extract from-import statements from AST trees."""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

from minport._models import ImportStatement

if TYPE_CHECKING:
    from pathlib import Path

# Imports that should never be flagged.
_IGNORED_MODULES = frozenset({"__future__"})


def parse_imports(tree: ast.Module, file_path: Path) -> list[ImportStatement]:
    """Extract all ``from X.Y import Name`` statements from *tree*.

    Skips:
    - ``import X.Y`` (no ``from``)
    - Relative imports (``from . import ...``)
    - ``from __future__ import ...``
    - Single-segment imports (``from X import Name`` — already shortest)
    """
    results: list[ImportStatement] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.level and node.level > 0:
            continue
        module = node.module or ""
        if not module or "." not in module:
            continue
        if module.split(".")[0] in _IGNORED_MODULES:
            continue
        results.extend(
            ImportStatement(
                module_path=module,
                name=alias.name,
                alias=alias.asname,
                file_path=file_path,
                line=node.lineno,
                col=node.col_offset + 1,
            )
            for alias in node.names
        )
    return results
