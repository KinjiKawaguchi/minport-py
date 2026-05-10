"""Read a Python file and parse it to an AST."""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def safe_parse(path: Path) -> ast.Module | None:
    """Read and parse a Python file, returning None on any parse failure."""
    try:
        source = path.read_text(encoding="utf-8")
        return ast.parse(source)
    except (OSError, UnicodeDecodeError, SyntaxError):
        return None
