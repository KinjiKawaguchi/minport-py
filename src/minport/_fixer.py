"""Auto-fix import statements by rewriting ``from ... import`` source spans."""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

from minport._models import FixResult

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from minport._models import Violation


def fix_file(file_path: Path, violations: list[Violation]) -> int:
    """Rewrite *file_path* in place, returning the number of violations fixed.

    The count reflects violations whose ``from X import`` statement was
    actually rebuilt. Violations that are silently skipped — stale
    ``original_path``, inline-comment guard, missing alias on the node —
    are not counted, so ``fix_files`` can report an accurate
    ``fixes_applied``.
    """
    if not violations:
        return 0

    loaded = _load_source(file_path)
    if loaded is None:
        return 0
    source, tree = loaded

    lines = source.splitlines(keepends=True)
    by_line = _group_by_line(violations)
    nodes_by_line = _collect_import_nodes(tree, by_line.keys())

    applied = _apply_rewrites(lines, by_line, nodes_by_line)

    if applied:
        file_path.write_text("".join(lines), encoding="utf-8")

    return applied


def _load_source(file_path: Path) -> tuple[str, ast.Module] | None:
    try:
        source = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    return source, tree


def _group_by_line(violations: list[Violation]) -> dict[int, list[Violation]]:
    by_line: dict[int, list[Violation]] = {}
    for v in violations:
        by_line.setdefault(v.line, []).append(v)
    return by_line


def _collect_import_nodes(
    tree: ast.Module,
    linenos: Iterable[int],
) -> dict[int, ast.ImportFrom]:
    wanted = set(linenos)
    nodes: dict[int, ast.ImportFrom] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.lineno in wanted:
            nodes[node.lineno] = node
    return nodes


def _apply_rewrites(
    lines: list[str],
    by_line: dict[int, list[Violation]],
    nodes_by_line: dict[int, ast.ImportFrom],
) -> int:
    applied = 0
    for lineno in sorted(by_line.keys(), reverse=True):
        node = nodes_by_line.get(lineno)
        if node is None:
            continue
        result = _rebuild_import(node, by_line[lineno], lines)
        if result is None:
            continue
        replacement, count = result
        start = node.lineno - 1
        end = node.end_lineno or node.lineno
        lines[start:end] = replacement
        applied += count
    return applied


def fix_files(
    files_violations: dict[Path, list[Violation]],
) -> FixResult:
    """Apply fixes to multiple files."""
    files_modified = 0
    fixes_applied = 0

    for file_path, violations in files_violations.items():
        applied = fix_file(file_path, violations)
        if applied:
            files_modified += 1
            fixes_applied += applied

    return FixResult(files_modified=files_modified, fixes_applied=fixes_applied)


def _rebuild_import(
    node: ast.ImportFrom,
    violations: list[Violation],
    lines: list[str],
) -> tuple[list[str], int] | None:
    """Return replacement lines and applied-move count, or None to skip."""
    if not node.module or node.level:
        return None

    start_idx = node.lineno - 1
    end_idx = node.end_lineno or node.lineno
    end_col = node.end_col_offset if node.end_col_offset is not None else len(lines[end_idx - 1])
    span_source = "".join(lines[start_idx:end_idx])
    if not _is_safe_to_rebuild(
        span_source,
        start_line=lines[start_idx],
        start_col=node.col_offset,
        end_line=lines[end_idx - 1],
        end_col=end_col,
    ):
        return None

    moves = _collect_moves(node, violations)
    groups, remaining = _partition_aliases(node.names, moves)
    if not groups:
        return None

    indent = lines[start_idx][: node.col_offset]
    trailing_nl = _detect_newline(lines[end_idx - 1])

    bodies: list[str] = [_format_from(shorter, groups[shorter]) for shorter in sorted(groups)]
    if remaining:
        bodies.append(_format_from(node.module, remaining))

    rebuilt = [indent + body + "\n" for body in bodies[:-1]]
    rebuilt.append(indent + bodies[-1] + trailing_nl)
    applied = sum(len(aliases) for aliases in groups.values())
    return rebuilt, applied


def _collect_moves(
    node: ast.ImportFrom,
    violations: list[Violation],
) -> dict[tuple[str, str | None], str]:
    moves: dict[tuple[str, str | None], str] = {}
    for v in violations:
        if v.shorter_path == v.original_path:
            continue
        if v.original_path != node.module:
            continue
        moves[(v.name, v.alias)] = v.shorter_path
    return moves


def _partition_aliases(
    aliases: list[ast.alias],
    moves: dict[tuple[str, str | None], str],
) -> tuple[dict[str, list[ast.alias]], list[ast.alias]]:
    groups: dict[str, list[ast.alias]] = {}
    remaining: list[ast.alias] = []
    for alias in aliases:
        dest = moves.get((alias.name, alias.asname))
        if dest is None:
            remaining.append(alias)
        else:
            groups.setdefault(dest, []).append(alias)
    return groups, remaining


def _is_safe_to_rebuild(
    span_source: str,
    *,
    start_line: str,
    start_col: int,
    end_line: str,
    end_col: int,
) -> bool:
    """Refuse rewrites that would drop comments or trailing code.

    Multi-line imports with inline ``#`` comments would lose those comments
    when rebuilt from AST, and ``a = 1; from x import Y; z = 2`` would lose
    code on either side if we replaced the whole line. In all such cases we
    skip so the user can address the import manually.
    """
    if start_line[:start_col].strip():
        return False
    if end_line[end_col:].strip():
        return False
    return "#" not in span_source


def _format_from(module: str, aliases: list[ast.alias]) -> str:
    names = ", ".join(_format_alias(a) for a in aliases)
    return f"from {module} import {names}"


def _format_alias(alias: ast.alias) -> str:
    if alias.asname:
        return f"{alias.name} as {alias.asname}"
    return alias.name


def _detect_newline(line: str) -> str:
    if line.endswith("\n"):
        return "\n"
    return ""
