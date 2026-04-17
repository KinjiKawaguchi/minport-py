"""Resolve re-export chains to find the shortest import path for a name."""

from __future__ import annotations

import ast
import importlib.util
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from typing import NoReturn

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
        self._loads_cache: dict[tuple[str, frozenset[str]], frozenset[Path]] = {}

    def find_shortest_path(
        self,
        module_path: str,
        name: str,
        *,
        current_file: Path | None = None,
    ) -> str | None:
        """Return the shortest candidate module that safely re-exports *name*.

        A candidate is safe when:

        1. Its terminal origin (the file and symbol that actually define
           *name*) equals the origin reached from *module_path*.
        2. Loading the candidate does not transitively load *current_file*
           (when provided). This prevents circular-import regressions, and
           lets the next-shortest safe candidate be returned when the very
           shortest would cycle.
        """
        parts = module_path.split(".")
        if len(parts) <= 1:
            return None

        original_origin = self._resolve_origin(module_path, name)
        if original_origin is None:
            return None

        for candidate in [".".join(parts[:i]) for i in range(1, len(parts))]:
            if self._resolve_origin(candidate, name) != original_origin:
                continue
            if current_file is not None and self.loads_file(candidate, current_file):
                continue
            return candidate
        return None

    def loads_file(self, module_path: str, target_file: Path) -> bool:
        """Return True if loading *module_path* transitively loads *target_file*.

        Used to detect circular imports: if shortening an import would make
        the file read from a namespace whose initialization triggers loading
        the file itself, the shortened form is unsafe.

        The BFS distinguishes two cases based on whether *module_path* is an
        ancestor of the file's module:

        * **Ancestor candidate** (shortening to a wrapping package):
          no skipping. Conservatively reports any path that reaches the
          file, since the file reads from a partially-initialized
          namespace whose name binding order cannot be verified statically.

        * **Non-ancestor candidate** (sibling or cousin package):
          skips the file's ancestor packages, which are already present in
          ``sys.modules`` when the file is loading and will not re-execute.
          This avoids false positives for patterns where an aggregator
          ``__init__.py`` would otherwise be walked via the parent chain.

        Follows ``from .x import y``, ``import a.b.c``, and their variants
        under runtime-reachable nodes (skips ``if TYPE_CHECKING:`` blocks).
        """
        try:
            target_resolved = target_file.resolve()
        except OSError:
            return False
        target_module = self._file_to_module(target_file)
        ancestors = self._ancestor_packages_of_file(target_file)
        candidate_is_ancestor = module_path == target_module or module_path in ancestors
        skip = frozenset() if candidate_is_ancestor else ancestors
        return target_resolved in self._transitive_loads(module_path, skip)

    def _transitive_loads(
        self,
        module_path: str,
        skip_modules: frozenset[str],
    ) -> frozenset[Path]:
        """Return resolved source files loaded transitively by *module_path*.

        Modules listed in *skip_modules* are treated as already-loaded (their
        ``__init__.py`` is not processed). This models Python's behavior
        where a module in ``sys.modules`` is not re-initialized.
        """
        cache_key = (module_path, skip_modules)
        if cache_key in self._loads_cache:
            return self._loads_cache[cache_key]
        self._loads_cache[cache_key] = frozenset()
        loaded: set[Path] = set()
        visited: set[str] = set()
        stack: list[str] = [module_path]
        while stack:
            current = stack.pop()
            if current in visited or current in skip_modules:
                continue
            visited.add(current)
            source_file = self._find_source_file(current)
            if source_file is None:
                continue
            try:
                loaded.add(source_file.resolve())
            except OSError:
                continue
            tree = _safe_parse(source_file)
            if tree is None:
                continue
            is_package = source_file.name == "__init__.py"
            stack.extend(
                imported
                for imported in _iter_runtime_load_targets(
                    tree,
                    current,
                    is_package=is_package,
                )
                if imported not in visited and imported not in skip_modules
            )
        result = frozenset(loaded)
        self._loads_cache[cache_key] = result
        return result

    def _ancestor_packages_of_file(self, file_path: Path) -> frozenset[str]:
        """Return the dotted module paths of *file_path*'s ancestor packages."""
        module = self._file_to_module(file_path)
        if module is None:
            return frozenset()
        parts = module.split(".")
        return frozenset(".".join(parts[:i]) for i in range(1, len(parts)))

    def _file_to_module(self, file_path: Path) -> str | None:
        """Map a source file path to its dotted module name."""
        try:
            resolved = file_path.resolve()
        except OSError:
            return None
        best: tuple[str, ...] | None = None
        for root in self._src_roots:
            try:
                root_resolved = root.resolve()
            except OSError:
                continue
            try:
                rel = resolved.relative_to(root_resolved)
            except ValueError:
                continue
            parts = rel.parts
            if parts[-1] == "__init__.py":
                parts = parts[:-1]
            elif parts[-1].endswith(".py"):
                parts = (*parts[:-1], parts[-1][:-3])
            else:
                continue
            if best is None or len(parts) < len(best):
                best = parts
        return ".".join(best) if best is not None and best else None

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
        """Return the set of names exported by the package at *module_path*."""
        if module_path in self._names_cache:
            return self._names_cache[module_path]

        source_file = self._find_source_file(module_path)
        names: set[str] = set()
        if source_file is not None:
            tree = _safe_parse(source_file)
            if tree is not None:
                names = self._extract_exported_names(
                    tree,
                    module_path,
                    is_package=source_file.name == "__init__.py",
                    visited=frozenset({module_path}),
                )
        self._names_cache[module_path] = names
        return names

    def _extract_exported_names(
        self,
        tree: ast.Module,
        module_path: str,
        *,
        is_package: bool,
        visited: frozenset[str],
    ) -> set[str]:
        """Collect names exported by *tree*, including wildcard-resolved ones."""
        reexported = _collect_reexported_names(tree)
        assigned = _collect_assigned_aliases(tree)
        wildcard = self._collect_wildcard_exports(
            tree,
            module_path,
            is_package=is_package,
            visited=visited,
        )
        all_names = _collect_all_names(tree)
        if all_names is not None:
            return (reexported | assigned | wildcard) & all_names
        return reexported | wildcard

    def _collect_wildcard_exports(
        self,
        tree: ast.Module,
        module_path: str,
        *,
        is_package: bool,
        visited: frozenset[str],
    ) -> set[str]:
        """Gather names brought in by ``from X import *`` statements in *tree*."""
        collected: set[str] = set()
        for target in _find_wildcard_targets(tree, module_path, is_package=is_package):
            collected |= self._wildcard_namespace(target, visited)
        return collected

    def _wildcard_namespace(
        self,
        module_path: str,
        visited: frozenset[str],
    ) -> set[str]:
        """Names that ``from module_path import *`` would bring into the caller.

        Follows Python wildcard semantics: if the target defines ``__all__``,
        use it verbatim; otherwise expose all top-level public names (excluding
        underscore-prefixed). Recurses into nested wildcard imports with a
        visited set guarding against cycles.
        """
        if module_path in visited:
            return set()

        source_file = self._find_source_file(module_path)
        if source_file is None:
            return set()
        tree = _safe_parse(source_file)
        if tree is None:
            return set()

        new_visited = visited | {module_path}
        is_package = source_file.name == "__init__.py"

        direct = _collect_reexported_names(tree) | _collect_top_level_defs(tree)
        nested = self._collect_wildcard_exports(
            tree,
            module_path,
            is_package=is_package,
            visited=new_visited,
        )
        combined = direct | nested

        all_names = _collect_all_names(tree)
        if all_names is not None:
            return combined & all_names
        return {n for n in combined if not n.startswith("_")}

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
            return self._wildcard_origin(module_path, name, visited)

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

    def _wildcard_origin(
        self,
        module_path: str,
        name: str,
        visited: frozenset[tuple[str, str]],
    ) -> Origin | None:
        """Resolve *name* through ``from X import *`` statements.

        Called when no direct binding is found. Respects the current module's
        ``__all__`` gate and each wildcard target's wildcard-export rule.
        """
        source_file = self._find_source_file(module_path)
        if source_file is None:
            return None
        tree = _safe_parse(source_file)
        if tree is None:
            return None

        public = _collect_all_names(tree)
        if public is not None and name not in public:
            return None

        is_package = source_file.name == "__init__.py"
        for target in _find_wildcard_targets(
            tree,
            module_path,
            is_package=is_package,
        ):
            if not self._name_passes_wildcard(target, name):
                continue
            origin = self._walk_origin(target, name, visited)
            if origin is not None:
                return origin
        return None

    def _name_passes_wildcard(self, target_module: str, name: str) -> bool:
        """Check that ``from target_module import *`` would expose *name*."""
        source_file = self._find_source_file(target_module)
        if source_file is None:
            return False
        tree = _safe_parse(source_file)
        if tree is None:
            return False
        all_names = _collect_all_names(tree)
        if all_names is not None:
            return name in all_names
        return not name.startswith("_")

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


def _find_installed_source(module_path: str) -> Path | None:
    """Find the source file (.py or __init__.py) of an installed module."""
    origin = _find_installed_origin(module_path)
    if origin is None or origin.suffix != ".py":
        return None
    return origin


def _find_installed_origin(module_path: str) -> Path | None:
    try:
        spec = importlib.util.find_spec(module_path)
    except Exception:  # noqa: BLE001
        # find_spec executes third-party module code (package __init__.py)
        # during resolution. That code may raise anything — module-level
        # AssertionError for platform guards (click/_winconsole.py),
        # OSError, ImportError, or arbitrary custom exceptions. Treat any
        # failure as \"module not usable\" and let the caller skip it
        # rather than crashing the whole check run.
        return None
    if spec is None or spec.origin is None:
        return None
    return Path(spec.origin)


def _collect_reexported_names(tree: ast.Module) -> set[str]:
    """Collect names from ``from ... import ...`` statements (excluding ``*``).

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


_SKIP_STMTS: tuple[type[ast.stmt], ...] = (
    # Nested scopes: bodies cannot publish module-level bindings at runtime.
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.ClassDef,
    # Compound hosts that are legal but not realistic re-export sites.
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.With,
    ast.AsyncWith,
    ast.Match,
    # Simple statements with no stmt-body to recurse into.
    ast.Return,
    ast.Delete,
    ast.Assign,
    ast.AugAssign,
    ast.AnnAssign,
    ast.Raise,
    ast.Assert,
    ast.Import,
    ast.ImportFrom,
    ast.Global,
    ast.Nonlocal,
    ast.Expr,
    ast.Pass,
    ast.Break,
    ast.Continue,
    # PEP 695 ``type X = ...`` (Python 3.12+). Accessed via ``getattr`` so
    # the expression stays valid on 3.11 where ``ast.TypeAlias`` is absent,
    # and inlined here so every Python version executes the same single
    # tuple-literal line (keeps line coverage at 100% across the matrix).
    # ast.TypeAlias is Python 3.12+; direct access would break 3.11 imports.
    *(
        (getattr(ast, "TypeAlias"),) if hasattr(ast, "TypeAlias") else ()  # noqa: B009
    ),
)


def _child_stmt_blocks(stmt: ast.stmt) -> Iterator[Sequence[ast.stmt]]:
    """Yield the nested stmt bodies ``_walk_stmts`` should recurse into.

    ``If`` / ``Try`` / ``TryStar`` bodies are walked because re-exports
    guarded by them still execute at runtime. Every other statement type
    is enumerated in ``_SKIP_STMTS`` as a deliberate no-op; anything that
    leaks past both groups hits ``_raise_unhandled_stmt`` so new Python
    grammar additions surface at test time rather than silently producing
    wrong results.
    """
    if isinstance(stmt, ast.If):
        yield stmt.body
        yield stmt.orelse
        return
    if isinstance(stmt, (ast.Try, ast.TryStar)):
        yield stmt.body
        for handler in stmt.handlers:
            yield handler.body
        yield stmt.orelse
        yield stmt.finalbody
        return
    if isinstance(stmt, _SKIP_STMTS):
        return
    _raise_unhandled_stmt(stmt)


def _raise_unhandled_stmt(stmt: ast.stmt) -> NoReturn:
    """Fail loudly on an ``ast.stmt`` subclass the walker was not taught about.

    Acts as a runtime ``assert_never`` equivalent. Static exhaustiveness
    via ``typing.assert_never`` cannot narrow here because ``_SKIP_STMTS``
    is built dynamically (to accommodate ``ast.TypeAlias`` being absent on
    Python 3.11), so this helper takes over as the last-line guard.
    """
    msg = (
        "Unhandled ast.stmt subclass in re-export walker: "
        f"{type(stmt).__name__}. Update _child_stmt_blocks to classify it."
    )
    raise TypeError(msg)


def _is_type_checking_guard(test: ast.expr) -> bool:
    """Return True for ``if TYPE_CHECKING`` / ``if typing.TYPE_CHECKING``."""
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    if isinstance(test, ast.Attribute):
        return test.attr == "TYPE_CHECKING"
    return False


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


def _collect_top_level_defs(tree: ast.Module) -> set[str]:
    """Collect all top-level class/function/assignment names.

    Used for wildcard semantics where any top-level public name defined in
    the target module is made available by ``from module import *``.
    """
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


def _find_wildcard_targets(
    tree: ast.Module,
    current_module: str,
    *,
    is_package: bool,
) -> list[str]:
    """Return the absolute module paths targeted by ``from X import *`` nodes."""
    targets: list[str] = []
    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        if not any(alias.name == "*" for alias in node.names):
            continue
        target_mod = node.module or ""
        resolved = _resolve_relative_module(
            current_module,
            target_mod,
            node.level,
            is_package=is_package,
        )
        if resolved:
            targets.append(resolved)
    return targets


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
    """Return the last statement that binds *name* at runtime, if any.

    Walks nested ``try/except`` and runtime ``if`` blocks so imports guarded
    by them are honoured. ``if TYPE_CHECKING:`` branches are skipped because
    the binding they introduce is not available at runtime. Python's last
    binding wins rule still applies, so only the final match is returned.
    """
    last: _Binding | None = None
    for node in _iter_runtime_nodes(tree):
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


def _iter_runtime_load_targets(
    tree: ast.Module,
    current_module: str,
    *,
    is_package: bool,
) -> Iterator[str]:
    """Yield module paths that Python would load at runtime for *tree*.

    Emits the target of each ``import`` / ``from ... import`` plus all parent
    packages, since Python loads them during the import chain. Submodule
    names in ``from pkg import X`` are also emitted as candidates; non-existent
    ones are filtered out by ``_find_source_file``.

    Statements under ``if TYPE_CHECKING:`` are skipped because their imports
    are not actually executed at runtime.
    """
    for node in _iter_runtime_nodes(tree):
        if isinstance(node, ast.ImportFrom):
            yield from _load_targets_from_node(
                node,
                current_module,
                is_package=is_package,
            )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                yield from _module_chain(alias.name)


def _load_targets_from_node(
    node: ast.ImportFrom,
    current_module: str,
    *,
    is_package: bool,
) -> Iterator[str]:
    """Yield module paths that *node* causes Python to load."""
    resolved = _resolve_relative_module(
        current_module,
        node.module or "",
        node.level,
        is_package=is_package,
    )
    if not resolved:
        return
    yield from _module_chain(resolved)
    for alias in node.names:
        if alias.name != "*":
            yield f"{resolved}.{alias.name}"


def _module_chain(module_path: str) -> Iterator[str]:
    """Yield *module_path* and every ancestor package it would trigger."""
    parts = module_path.split(".")
    for i in range(1, len(parts) + 1):
        yield ".".join(parts[:i])


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
    the parent package. An empty *target* is allowed (``from .. import *``)
    and resolves to just the base package.
    """
    if level == 0:
        return target or None

    parts = current_module.split(".") if current_module else []
    up = level - 1 if is_package else level
    if up >= len(parts):
        return None

    base = parts[: len(parts) - up] if up > 0 else parts
    target_parts = target.split(".") if target else []
    combined = [*base, *target_parts]
    return ".".join(combined) if combined else None
