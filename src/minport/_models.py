"""Immutable data models used across the minport pipeline."""

import ast
from dataclasses import dataclass
from pathlib import Path

DEFAULT_EXCLUDES: tuple[str, ...] = (
    ".bzr",
    ".direnv",
    ".eggs",
    ".git",
    ".git-rewrite",
    ".hg",
    ".ipynb_checkpoints",
    ".mypy_cache",
    ".nox",
    ".pants.d",
    ".pyenv",
    ".pytest_cache",
    ".pytype",
    ".ruff_cache",
    ".svn",
    ".tox",
    ".venv",
    ".vscode",
    "__pypackages__",
    "__pycache__",
    "_build",
    "buck-out",
    "dist",
    "node_modules",
    "site-packages",
    "venv",
)


@dataclass(frozen=True)
class ImportStatement:
    """A parsed ``from X.Y.Z import Name`` statement."""

    module_path: str
    name: str
    alias: str | None
    file_path: Path
    line: int
    col: int
    name_line: int = 0


@dataclass(frozen=True)
class Violation:
    """A detected import that can be shortened."""

    file_path: Path
    line: int
    col: int
    original_path: str
    shorter_path: str
    name: str
    alias: str | None
    code: str
    message: str


@dataclass(frozen=True)
class CheckResult:
    """Aggregated result of a check run."""

    violations: tuple[Violation, ...]
    files_checked: int
    files_skipped: int
    fixable_count: int = 0


@dataclass(frozen=True)
class FixResult:
    """Result of an auto-fix run."""

    files_modified: int
    fixes_applied: int


@dataclass(frozen=True)
class ParsedFile:
    """A parsed Python source file."""

    file_path: Path
    tree: ast.Module
    source_lines: tuple[str, ...]
