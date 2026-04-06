"""Auto-fix import statements by rewriting source lines."""

from __future__ import annotations

from typing import TYPE_CHECKING

from minport._models import FixResult

if TYPE_CHECKING:
    from pathlib import Path

    from minport._models import Violation


def fix_file(file_path: Path, violations: list[Violation]) -> bool:
    """Rewrite *file_path* in place, applying all *violations* as fixes.

    Returns True if the file was modified.
    """
    if not violations:
        return False

    try:
        source = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False

    lines = source.splitlines(keepends=True)
    modified = False

    # Process violations in reverse line order to preserve line numbers.
    for v in sorted(violations, key=lambda v: v.line, reverse=True):
        idx = v.line - 1
        if idx < 0 or idx >= len(lines):
            continue
        old_line = lines[idx]
        new_line = _rewrite_import_line(old_line, v)
        if new_line != old_line:
            lines[idx] = new_line
            modified = True

    if modified:
        file_path.write_text("".join(lines), encoding="utf-8")

    return modified


def fix_files(
    files_violations: dict[Path, list[Violation]],
) -> FixResult:
    """Apply fixes to multiple files."""
    files_modified = 0
    fixes_applied = 0

    for file_path, violations in files_violations.items():
        if fix_file(file_path, violations):
            files_modified += 1
            fixes_applied += len(violations)

    return FixResult(files_modified=files_modified, fixes_applied=fixes_applied)


def _rewrite_import_line(line: str, v: Violation) -> str:
    """Replace the import path in a single line."""
    old_from = f"from {v.original_path} import"
    new_from = f"from {v.shorter_path} import"
    if old_from in line:
        return line.replace(old_from, new_from, 1)
    return line
