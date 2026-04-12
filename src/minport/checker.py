"""Facade that orchestrates the full minport check pipeline."""

from __future__ import annotations

import ast
import os
from fnmatch import fnmatch
from pathlib import Path
from typing import TYPE_CHECKING

from minport._fixer import fix_files
from minport._import_parser import parse_imports
from minport._models import DEFAULT_EXCLUDES, CheckResult, FixResult, ParsedFile, Violation
from minport._reexport_resolver import ReexportResolver

if TYPE_CHECKING:
    from collections.abc import Sequence

_INLINE_SUPPRESS = "minport: ignore"


def check(
    paths: Sequence[Path],
    *,
    src_roots: Sequence[Path] | None = None,
    exclude: Sequence[str] | None = None,
    fix: bool = False,
) -> tuple[CheckResult, FixResult | None]:
    """Run the full minport check on the given paths.

    When *exclude* is ``None`` (the default), :data:`DEFAULT_EXCLUDES` is used.
    Pass an explicit list to override the defaults entirely.
    """
    effective_src = list(src_roots) if src_roots else _infer_src_roots(paths)
    effective_exclude = tuple(exclude) if exclude is not None else DEFAULT_EXCLUDES
    files = _collect_files(paths, effective_exclude)

    resolver = ReexportResolver(effective_src)

    parsed: dict[Path, ParsedFile] = {}
    skipped: list[tuple[Path, str]] = []

    for file_path in files:
        pf = _safe_parse(file_path, skipped)
        if pf is not None:
            parsed[file_path] = pf

    all_violations: list[Violation] = []
    for file_path, pf in parsed.items():
        all_violations.extend(
            _find_violations(file_path, pf, resolver, effective_src),
        )
    all_violations.sort(key=lambda v: (str(v.file_path), v.line, v.col))

    files_violations: dict[Path, list[Violation]] = {}
    for v in all_violations:
        files_violations.setdefault(v.file_path, []).append(v)
    fixable = {fp: _drop_duplicate_fixes(vs, parsed[fp]) for fp, vs in files_violations.items()}
    fixable_count = sum(len(vs) for vs in fixable.values())

    result = CheckResult(
        violations=tuple(all_violations),
        files_checked=len(parsed),
        files_skipped=len(skipped),
        fixable_count=fixable_count,
    )

    if not fix:
        return result, None
    return result, fix_files(fixable)


def _find_violations(
    file_path: Path,
    pf: ParsedFile,
    resolver: ReexportResolver,
    src_roots: list[Path],
) -> list[Violation]:
    """Detect shortenable imports in a single parsed file."""
    violations: list[Violation] = []
    for imp in parse_imports(pf.tree, file_path):
        if _has_suppress_comment(imp.line, pf.source_lines):
            continue
        shorter = resolver.find_shortest_path(imp.module_path, imp.name)
        if shorter is None:
            continue
        if resolver.has_name_conflict(imp.name, imp.module_path):
            continue
        if _is_own_init(file_path, shorter, src_roots):
            continue
        violations.append(
            Violation(
                file_path=file_path,
                line=imp.line,
                col=imp.col,
                original_path=imp.module_path,
                shorter_path=shorter,
                name=imp.name,
                alias=imp.alias,
                code="MP001",
                message=(
                    f"`from {imp.module_path} import {imp.name}` can be shortened"
                    f" to `from {shorter} import {imp.name}`"
                ),
            ),
        )
    return violations


def _infer_src_roots(paths: Sequence[Path]) -> list[Path]:
    """Infer source roots from the given paths."""
    roots: list[Path] = []
    for p in paths:
        resolved = p.resolve()
        if resolved.is_dir():
            roots.append(resolved)
        elif resolved.is_file():
            roots.append(resolved.parent)
    return roots or [Path.cwd()]


def _collect_files(
    paths: Sequence[Path],
    exclude: Sequence[str],
) -> list[Path]:
    """Collect all .py files from the given paths."""
    exclude_set = frozenset(exclude)
    files: list[Path] = []
    seen: set[Path] = set()

    for path in paths:
        resolved = path.resolve()
        if resolved.is_file():
            real = _safe_realpath(resolved)
            if real not in seen and resolved.suffix == ".py":
                seen.add(real)
                files.append(resolved)
        elif resolved.is_dir():
            for root, dirs, filenames in os.walk(resolved):
                dirs[:] = [d for d in dirs if d not in exclude_set]
                for name in filenames:
                    fp = Path(root) / name
                    if fp.suffix != ".py":
                        continue
                    real = _safe_realpath(fp)
                    if real in seen:
                        continue
                    if _is_excluded(fp, resolved, exclude):
                        continue
                    seen.add(real)
                    files.append(fp)
    return sorted(files)


def _is_excluded(path: Path, base: Path, patterns: Sequence[str]) -> bool:
    try:
        rel = str(path.relative_to(base))
    except ValueError:
        rel = str(path)
    return any(fnmatch(rel, pat) for pat in patterns)


def _safe_realpath(path: Path) -> Path:
    """Resolve symlinks to prevent duplicate processing."""
    try:
        return path.resolve(strict=True)
    except OSError:
        return path.resolve()


def _safe_parse(
    file_path: Path,
    skipped: list[tuple[Path, str]],
) -> ParsedFile | None:
    """Parse a Python file, skipping binary/syntax-error files."""
    try:
        source = file_path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as e:
        skipped.append((file_path, f"Cannot read: {e}"))
        return None

    try:
        tree = ast.parse(source, filename=str(file_path))
    except SyntaxError as e:
        skipped.append((file_path, f"Syntax error: {e}"))
        return None

    return ParsedFile(
        file_path=file_path,
        tree=tree,
        source_lines=tuple(source.splitlines()),
    )


def _drop_duplicate_fixes(
    violations: list[Violation],
    parsed_file: ParsedFile,
) -> list[Violation]:
    """Drop violations whose rewrite would duplicate another import in the file.

    Skipping (rather than merging) is the safe choice: if the user already has
    ``from M import N`` on another line, rewriting ``from M.sub import N`` would
    produce a second import of ``(M, N)`` — flagged by ruff F811 / F401.
    Leaving the longer import in place preserves existing bindings.

    The fixer rebuilds imports per-alias, so each violation can be decided
    independently: a multi-name line is safe to partially rewrite as long as
    each surviving move points at a unique, unclaimed ``(shorter, name)``
    target. Two violations that would both reduce to the same target are
    both dropped, since applying either alone still leaves a duplicate on
    the untouched sibling.
    """
    existing = _collect_all_from_imports(parsed_file.tree)

    target_count: dict[tuple[str, str], int] = {}
    for v in violations:
        key = (v.shorter_path, v.name)
        target_count[key] = target_count.get(key, 0) + 1

    return [
        v
        for v in violations
        if (v.shorter_path, v.name) not in existing and target_count[v.shorter_path, v.name] == 1
    ]


def _collect_all_from_imports(tree: ast.Module) -> dict[tuple[str, str], int]:
    """Map ``(module, name)`` to line for every absolute from-import in *tree*.

    Unlike :func:`parse_imports`, single-segment modules (``from pkg import X``)
    are included — they are the very targets that duplicate-fix detection
    needs to compare against.
    """
    imports: dict[tuple[str, str], int] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.level or not node.module:
            continue
        module = node.module
        for alias in node.names:
            imports.setdefault((module, alias.name), node.lineno)
    return imports


def _is_own_init(
    file_path: Path,
    shorter_module: str,
    src_roots: list[Path],
) -> bool:
    """Return True when shortening would cause a circular import.

    Two cases are blocked:
    1. *file_path* is the ``__init__.py`` of *shorter_module* itself (direct
       self-import → partially initialized module).
    2. *file_path* is an ``__init__.py`` inside a descendant package of
       *shorter_module*. The ancestor's ``__init__.py`` may re-export from
       this package, creating an indirect circular import chain.
    """
    if file_path.name != "__init__.py":
        return False
    pkg_module = _init_to_module(file_path, src_roots)
    if pkg_module is None:
        return False
    return pkg_module == shorter_module or pkg_module.startswith(f"{shorter_module}.")


def _init_to_module(file_path: Path, src_roots: list[Path]) -> str | None:
    """Map an ``__init__.py`` path to its dotted module name."""
    try:
        resolved = file_path.resolve()
    except OSError:
        return None
    pkg_dir = resolved.parent
    for root in src_roots:
        try:
            root_resolved = root.resolve()
        except OSError:
            continue
        try:
            rel = pkg_dir.relative_to(root_resolved)
        except ValueError:
            continue
        return ".".join(rel.parts)
    return None


def _has_suppress_comment(lineno: int, source_lines: tuple[str, ...]) -> bool:
    """Check for ``# minport: ignore`` on the given line."""
    idx = lineno - 1
    if 0 <= idx < len(source_lines):
        return _INLINE_SUPPRESS in source_lines[idx]
    return False
