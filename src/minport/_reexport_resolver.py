"""Resolve re-export chains to find the shortest import path for a name."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


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

        names = self._resolve_exports(module_path, visited=frozenset())
        self._cache[module_path] = names
        return names

    def _resolve_exports(
        self,
        module_path: str,
        visited: frozenset[str],
    ) -> set[str]:
        """Resolve exports for *module_path* while guarding against cycles."""
        if module_path in visited:
            return set()

        module_file = self._find_module_file(module_path)
        if module_file is None:
            return set()

        try:
            tree = ast.parse(module_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError):
            return set()

        current_package = _current_package(module_path, module_file)
        direct_names = _collect_reexported_names(tree) | _collect_top_level_names(tree)
        wildcard_names = self._resolve_wildcards(
            tree,
            current_package,
            visited | {module_path},
        )
        combined = direct_names | wildcard_names

        all_names = _collect_all_names(tree)
        if all_names is not None:
            return combined & all_names
        return {n for n in combined if not n.startswith("_")}

    def _resolve_wildcards(
        self,
        tree: ast.Module,
        current_package: str,
        visited: frozenset[str],
    ) -> set[str]:
        """Recursively resolve ``from .x import *`` targets."""
        collected: set[str] = set()
        for node in ast.iter_child_nodes(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            if not any(alias.name == "*" for alias in node.names):
                continue
            target = _resolve_relative_module(
                current_package,
                node.level or 0,
                node.module,
            )
            if target is None:
                continue
            collected |= self._resolve_exports(target, visited)
        return collected

    def _find_module_file(self, module_path: str) -> Path | None:
        """Find the source file for a module — package ``__init__.py`` or ``.py``."""
        parts = module_path.split(".")
        for root in self._src_roots:
            init = root / Path(*parts) / "__init__.py"
            if init.is_file():
                return init
            if parts:
                module_file = root / Path(*parts[:-1]) / f"{parts[-1]}.py"
                if module_file.is_file():
                    return module_file

        return _find_installed_module_file(module_path)


def _current_package(module_path: str, module_file: Path) -> str:
    """Return the dotted package containing *module_path*."""
    if module_file.name == "__init__.py":
        return module_path
    parts = module_path.split(".")
    return ".".join(parts[:-1])


def _resolve_relative_module(
    current_package: str,
    level: int,
    module: str | None,
) -> str | None:
    """Resolve a relative import to an absolute dotted module path."""
    if level == 0:
        return module
    parts = current_package.split(".") if current_package else []
    drop = level - 1
    if drop > len(parts):
        return None
    base = parts[: len(parts) - drop]
    if module:
        base = [*base, *module.split(".")]
    if not base:
        return None
    return ".".join(base)


def _find_installed_module_file(module_path: str) -> Path | None:
    """Find the source file of an installed package/module via importlib."""
    try:
        spec = importlib.util.find_spec(module_path)
    except (ModuleNotFoundError, ValueError, ImportError):
        return None
    if spec is None or spec.origin is None:
        return None
    origin = Path(spec.origin)
    if origin.suffix != ".py":
        return None
    return origin


def _collect_reexported_names(tree: ast.Module) -> set[str]:
    """Collect names from ``from ... import ...`` statements (excluding ``*``)."""
    names: set[str] = set()
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name != "*":
                    names.add(alias.asname or alias.name)
    return names


def _collect_top_level_names(tree: ast.Module) -> set[str]:
    """Collect top-level class/function/assignment names defined in *tree*."""
    names: set[str] = set()
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


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
