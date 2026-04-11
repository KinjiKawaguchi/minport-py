"""Resolve re-export chains to find the shortest import path for a name."""

from __future__ import annotations

import ast
import importlib.util
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

Origin = tuple[Path, str]


@dataclass(frozen=True)
class _Binding:
    """A top-level binding of a name in a module.

    Either a local definition (class/def/assignment) or a re-export that
    forwards to ``target_module.target_name`` at the given relative ``level``.
    """

    is_definition: bool
    target_module: str = ""
    target_name: str = ""
    level: int = 0


class ReexportResolver:
    """Find the shortest ``from X import Name`` path by walking re-exports."""

    def __init__(self, src_roots: Sequence[Path]) -> None:
        self._src_roots = list(src_roots)
        self._names_cache: dict[str, set[str]] = {}
        self._origin_cache: dict[tuple[str, str], Origin | None] = {}

    def find_shortest_path(self, module_path: str, name: str) -> str | None:
        """Return the shortest candidate module that safely re-exports *name*.

        A candidate is safe when its terminal origin (the file and symbol that
        actually define *name*) equals the origin reached from *module_path*.
        That lets legitimate re-export chains through parent packages shorten,
        while rejecting candidates that would bind the same textual name to a
        different underlying entity.
        """
        parts = module_path.split(".")
        if len(parts) <= 1:
            return None

        original_origin = self._resolve_origin(module_path, name)
        if original_origin is None:
            return None

        for candidate in [".".join(parts[:i]) for i in range(1, len(parts))]:
            if self._resolve_origin(candidate, name) == original_origin:
                return candidate
        return None

    def has_name_conflict(self, name: str, module_path: str) -> bool:
        """Return True when a shorter candidate binds *name* to a different origin.

        Re-export chains that terminate at the same definition are not
        conflicts; only genuinely distinct symbols sharing the same textual
        name are reported.
        """
        original_origin = self._resolve_origin(module_path, name)
        if original_origin is None:
            return False

        parts = module_path.split(".")
        for candidate in [".".join(parts[:i]) for i in range(1, len(parts))]:
            other = self._resolve_origin(candidate, name)
            if other is not None and other != original_origin:
                return True
        return False

    def _get_exported_names(self, module_path: str) -> set[str]:
        """Return the set of names exported by the module at *module_path*."""
        if module_path in self._names_cache:
            return self._names_cache[module_path]

        init_file = self._find_init_file(module_path)
        names: set[str] = set()
        if init_file is not None:
            tree = _safe_parse(init_file)
            if tree is not None:
                names = _extract_exported_names(tree)
        self._names_cache[module_path] = names
        return names

    def _resolve_origin(self, module_path: str, name: str) -> Origin | None:
        """Trace *name* through re-export chains to its terminal definition."""
        key = (module_path, name)
        if key in self._origin_cache:
            return self._origin_cache[key]
        origin = self._walk_origin(module_path, name, frozenset())
        self._origin_cache[key] = origin
        return origin

    def _walk_origin(
        self,
        module_path: str,
        name: str,
        visited: frozenset[tuple[str, str]],
    ) -> Origin | None:
        key = (module_path, name)
        if key in visited:
            return None
        return self._compute_origin(module_path, name, visited | {key})

    def _compute_origin(
        self,
        module_path: str,
        name: str,
        visited: frozenset[tuple[str, str]],
    ) -> Origin | None:
        parsed = self._parse_for_origin(module_path, name)
        if parsed is None:
            return None
        source_file, binding = parsed
        if binding.is_definition:
            return (source_file, name)

        abs_module = _resolve_relative_module(
            module_path,
            binding.target_module,
            binding.level,
            is_package=source_file.name == "__init__.py",
        )
        if abs_module is None:
            return None
        return self._walk_origin(abs_module, binding.target_name, visited)

    def _parse_for_origin(
        self,
        module_path: str,
        name: str,
    ) -> tuple[Path, _Binding] | None:
        source_file = self._find_source_file(module_path)
        if source_file is None:
            return None
        tree = _safe_parse(source_file)
        if tree is None:
            return None

        public = _collect_all_names(tree)
        if public is not None and name not in public:
            return None

        binding = _find_name_binding(tree, name)
        if binding is None:
            return None
        return source_file, binding

    def _find_init_file(self, module_path: str) -> Path | None:
        """Find the __init__.py for a dotted module path."""
        parts = module_path.split(".")
        for root in self._src_roots:
            init = root / Path(*parts) / "__init__.py"
            if init.is_file():
                return init
        return _find_installed_init(module_path)

    def _find_source_file(self, module_path: str) -> Path | None:
        """Find ``__init__.py`` or the ``.py`` module file for *module_path*."""
        parts = module_path.split(".")
        for root in self._src_roots:
            init = root / Path(*parts) / "__init__.py"
            if init.is_file():
                return init
            module_file = root / Path(*parts[:-1]) / f"{parts[-1]}.py"
            if module_file.is_file():
                return module_file
        return _find_installed_source(module_path)


def _safe_parse(path: Path) -> ast.Module | None:
    """Read and parse a Python file, returning None on any parse failure."""
    try:
        source = path.read_text(encoding="utf-8")
        return ast.parse(source)
    except (OSError, UnicodeDecodeError, SyntaxError):
        return None


def _find_installed_init(module_path: str) -> Path | None:
    """Find __init__.py of an installed package via importlib."""
    origin = _find_installed_origin(module_path)
    if origin is None or origin.name != "__init__.py":
        return None
    return origin


def _find_installed_source(module_path: str) -> Path | None:
    """Find the source file (.py or __init__.py) of an installed module."""
    origin = _find_installed_origin(module_path)
    if origin is None or origin.suffix != ".py":
        return None
    return origin


def _find_installed_origin(module_path: str) -> Path | None:
    try:
        spec = importlib.util.find_spec(module_path)
    except (ImportError, ValueError):
        return None
    if spec is None or spec.origin is None:
        return None
    return Path(spec.origin)


def _extract_exported_names(tree: ast.Module) -> set[str]:
    """Extract names that a module exports via re-export or __all__."""
    reexported_names = _collect_reexported_names(tree)
    all_names = _collect_all_names(tree)

    if all_names is not None:
        assigned_aliases = _collect_assigned_aliases(tree)
        return (reexported_names | assigned_aliases) & all_names

    return reexported_names


def _collect_reexported_names(tree: ast.Module) -> set[str]:
    """Collect names from ``from ... import ...`` statements."""
    names: set[str] = set()
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name != "*":
                    names.add(alias.asname or alias.name)
    return names


def _collect_assigned_aliases(tree: ast.Module) -> set[str]:
    """Collect top-level ``Name = other.attr`` assignments (re-export aliases).

    Handles both plain ``Assign`` (``Foo = _impl._Foo``) and annotated
    ``AnnAssign`` (``Foo: type[Base] = _impl._Foo``). Only assignments whose
    RHS is an attribute access are treated as candidates, to avoid capturing
    arbitrary value assignments. The caller must intersect with ``__all__``
    before treating them as public.
    """
    names: set[str] = set()
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Assign):
            if not isinstance(node.value, ast.Attribute):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign):
            if not isinstance(node.value, ast.Attribute):
                continue
            if isinstance(node.target, ast.Name):
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


def _find_name_binding(tree: ast.Module, name: str) -> _Binding | None:
    """Return the last top-level statement that binds *name*, if any.

    Python import semantics follow the last binding wins rule, so for an
    ``__init__.py`` that contains multiple assignments or imports of the same
    name, only the final one reflects the runtime namespace.
    """
    last: _Binding | None = None
    for node in ast.iter_child_nodes(tree):
        candidate = _binding_from_node(node, name)
        if candidate is not None:
            last = candidate
    return last


def _binding_from_node(node: ast.AST, name: str) -> _Binding | None:
    if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
        return _Binding(is_definition=True) if node.name == name else None
    if isinstance(node, ast.Assign):
        return _binding_from_assign(node, name)
    if isinstance(node, ast.AnnAssign):
        return _binding_from_annassign(node, name)
    if isinstance(node, ast.ImportFrom):
        return _reexport_binding(node, name)
    return None


def _binding_from_assign(node: ast.Assign, name: str) -> _Binding | None:
    for target in node.targets:
        if isinstance(target, ast.Name) and target.id == name:
            return _Binding(is_definition=True)
    return None


def _binding_from_annassign(node: ast.AnnAssign, name: str) -> _Binding | None:
    if isinstance(node.target, ast.Name) and node.target.id == name:
        return _Binding(is_definition=True)
    return None


def _reexport_binding(node: ast.ImportFrom, name: str) -> _Binding | None:
    if not node.module:
        return None
    for alias in node.names:
        bound = alias.asname or alias.name
        if bound == name and alias.name != "*":
            return _Binding(
                is_definition=False,
                target_module=node.module,
                target_name=alias.name,
                level=node.level,
            )
    return None


def _resolve_relative_module(
    current_module: str,
    target: str,
    level: int,
    *,
    is_package: bool,
) -> str | None:
    """Convert a possibly-relative import to an absolute dotted path.

    ``level`` follows Python semantics: ``0`` means an absolute import, ``1``
    means the current package, ``2`` means its parent, and so on. When the
    current file is a module (not a package), ``level=1`` already refers to
    the parent package.
    """
    if level == 0:
        return target

    parts = current_module.split(".")
    up = level - 1 if is_package else level
    if up >= len(parts):
        return None

    base = parts[: len(parts) - up] if up > 0 else parts
    return ".".join([*base, *target.split(".")])
