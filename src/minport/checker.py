"""Facade that orchestrates the full minport check pipeline."""

from __future__ import annotations

import ast
import os
from fnmatch import fnmatch
from pathlib import Path
from typing import TYPE_CHECKING

from minport._fixer import fix_files
from minport._import_parser import parse_imports
from minport._models import CheckResult, FixResult, ParsedFile, Violation
from minport._reexport_resolver import ReexportResolver

if TYPE_CHECKING:
    from collections.abc import Sequence

_INLINE_SUPPRESS = "minport: ignore"


def check(
    paths: Sequence[Path],
    *,
    src_roots: Sequence[Path] | None = None,
    exclude: Sequence[str] = (),
    fix: bool = False,
) -> CheckResult | tuple[CheckResult, FixResult]:
    """Run the full minport check on the given paths."""
    effective_src = list(src_roots) if src_roots else _infer_src_roots(paths)
    files = _collect_files(paths, exclude)

    resolver = ReexportResolver(effective_src)

    parsed: dict[Path, ParsedFile] = {}
    skipped: list[tuple[Path, str]] = []

    for file_path in files:
        pf = _safe_parse(file_path, skipped)
        if pf is not None:
            parsed[file_path] = pf

    all_violations: list[Violation] = []

    for file_path, pf in parsed.items():
        imports = parse_imports(pf.tree, file_path)
        for imp in imports:
            if _has_suppress_comment(imp.line, pf.source_lines):
                continue
            shorter = resolver.find_shortest_path(imp.module_path, imp.name)
            if shorter is None:
                continue
            if resolver.has_name_conflict(imp.name, imp.module_path):
                continue
            all_violations.append(
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

    all_violations.sort(key=lambda v: (str(v.file_path), v.line, v.col))

    result = CheckResult(
        violations=tuple(all_violations),
        files_checked=len(parsed),
        files_skipped=len(skipped),
    )

    if fix:
        files_violations: dict[Path, list[Violation]] = {}
        for v in all_violations:
            files_violations.setdefault(v.file_path, []).append(v)
        fix_result = fix_files(files_violations)
        return result, fix_result

    return result


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
            for root, _, filenames in os.walk(resolved):
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


def _has_suppress_comment(lineno: int, source_lines: tuple[str, ...]) -> bool:
    """Check for ``# minport: ignore`` on the given line."""
    idx = lineno - 1
    if 0 <= idx < len(source_lines):
        return _INLINE_SUPPRESS in source_lines[idx]
    return False
