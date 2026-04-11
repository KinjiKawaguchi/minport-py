"""Resolve re-export chains to find the shortest import path for a name."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence


class ReexportResolver:
    """Find the shortest ``from X import Name`` path by walking re-exports."""

    def __init__(self, src_roots: Sequence[Path]) -> None:
        self._src_roots = list(src_roots)
        self._cache: dict[str, set[str]] = {}

    def find_shortest_path(self, module_path: str, name: str) -> str | None:
        """Return the shortest module path that re-exports *name*, or None.

        Returns None if the current path is already the shortest, or if
        a shorter path cannot be determined with confidence.
        """
        parts = module_path.split(".")
        if len(parts) <= 1:
            return None

        candidates = [".".join(parts[:i]) for i in range(1, len(parts))]

        for candidate in candidates:
            exported = self._get_exported_names(candidate)
            if name in exported:
                return candidate

        return None

    def has_name_conflict(self, name: str, module_path: str) -> bool:
        """Check if *name* is exported by multiple candidate paths."""
        parts = module_path.split(".")
        candidates = [".".join(parts[:i]) for i in range(1, len(parts))]
        found_count = sum(1 for c in candidates if name in self._get_exported_names(c))
        return found_count > 1

    def _get_exported_names(self, module_path: str) -> set[str]:
        """Return the set of names exported by the module at *module_path*."""
        if module_path in self._cache:
            return self._cache[module_path]

        names = self._resolve_names(module_path)
        self._cache[module_path] = names
        return names

    def _resolve_names(self, module_path: str) -> set[str]:
        """Resolve exported names by finding and parsing the module's __init__.py."""
        init_file = self._find_init_file(module_path)
        if init_file is None:
            return set()

        try:
            source = init_file.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (OSError, UnicodeDecodeError, SyntaxError):
            return set()

        return _extract_exported_names(tree)

    def _find_init_file(self, module_path: str) -> Path | None:
        """Find the __init__.py for a dotted module path."""
        parts = module_path.split(".")
        for root in self._src_roots:
            init = root / Path(*parts) / "__init__.py"
            if init.is_file():
                return init

        return _find_installed_init(module_path)


def _find_installed_init(module_path: str) -> Path | None:
    """Find __init__.py of an installed package via importlib."""
    try:
        spec = importlib.util.find_spec(module_path)
    except (ModuleNotFoundError, ValueError):
        return None
    if spec is None or spec.origin is None:
        return None
    origin = Path(spec.origin)
    if origin.name == "__init__.py":
        return origin
    return None


def _extract_exported_names(tree: ast.Module) -> set[str]:
    """Extract names that a module exports via re-export or __all__."""
    reexported_names = _collect_reexported_names(tree)
    all_names = _collect_all_names(tree)

    if all_names is not None:
        return reexported_names & all_names

    return reexported_names


def _collect_reexported_names(tree: ast.Module) -> set[str]:
    """Collect names from ``from ... import ...`` statements.

    Walks nested bodies so that imports guarded by ``try/except`` or runtime
    ``if`` blocks are recognized as re-exports. Imports under
    ``if TYPE_CHECKING`` are skipped because they are not available at runtime.
    """
    names: set[str] = set()
    for node in _iter_runtime_nodes(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name != "*":
                    names.add(alias.asname or alias.name)
    return names


def _iter_runtime_nodes(tree: ast.Module) -> Iterator[ast.stmt]:
    """Yield statements reachable at runtime, skipping TYPE_CHECKING blocks."""
    yield from _walk_stmts(tree.body)


def _walk_stmts(stmts: Sequence[ast.stmt]) -> Iterator[ast.stmt]:
    for stmt in stmts:
        if isinstance(stmt, ast.If) and _is_type_checking_guard(stmt.test):
            yield from _walk_stmts(stmt.orelse)
            continue
        yield stmt
        for child in _child_stmt_blocks(stmt):
            yield from _walk_stmts(child)


def _child_stmt_blocks(stmt: ast.stmt) -> Iterator[Sequence[ast.stmt]]:
    if isinstance(stmt, ast.If):
        yield stmt.body
        yield stmt.orelse
    elif isinstance(stmt, ast.Try):
        yield stmt.body
        for handler in stmt.handlers:
            yield handler.body
        yield stmt.orelse
        yield stmt.finalbody
    elif isinstance(stmt, (ast.With, ast.AsyncWith)):
        yield stmt.body


def _is_type_checking_guard(test: ast.expr) -> bool:
    """Return True for ``if TYPE_CHECKING`` / ``if typing.TYPE_CHECKING``."""
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    if isinstance(test, ast.Attribute):
        return test.attr == "TYPE_CHECKING"
    return False


def _collect_all_names(tree: ast.Module) -> set[str] | None:
    """Parse ``__all__ = [...]`` if present. Returns None if __all__ is absent."""
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Assign):
            parsed = _parse_all_assignment(node)
            if parsed is not None:
                return parsed
    return None


def _parse_all_assignment(node: ast.Assign) -> set[str] | None:
    """Parse ``__all__ = ["Name", ...]`` and return the names, or None."""
    if len(node.targets) != 1:
        return None
    target = node.targets[0]
    if not isinstance(target, ast.Name) or target.id != "__all__":
        return None
    if not isinstance(node.value, (ast.List, ast.Tuple)):
        return None
    names: set[str] = set()
    for elt in node.value.elts:
        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
            names.add(elt.value)
    return names
