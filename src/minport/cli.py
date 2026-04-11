"""CLI entry point for minport."""

from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

from minport.checker import check

if TYPE_CHECKING:
    from minport._models import CheckResult, FixResult


def main(argv: list[str] | None = None) -> int:
    """Entry point for ``minport check``."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    if not hasattr(args, "handler"):
        parser.print_help()
        return 0

    return args.handler(args)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="minport",
        description="Find unnecessarily long import paths and suggest shorter alternatives",
    )
    sub = parser.add_subparsers()

    check_parser = sub.add_parser("check", help="Run the checker")
    check_parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Files or directories to check",
    )
    check_parser.add_argument(
        "--fix",
        action="store_true",
        default=False,
        help="Auto-fix import paths in place",
    )
    check_parser.add_argument(
        "--src",
        dest="src_roots",
        action="append",
        type=Path,
        default=None,
        help="Source root(s) for import resolution",
    )
    check_parser.add_argument(
        "--exclude",
        action="append",
        default=None,
        help="Glob patterns to exclude",
    )
    check_parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to pyproject.toml",
    )
    check_parser.set_defaults(handler=_handle_check)
    return parser


def _handle_check(args: argparse.Namespace) -> int:
    config = _load_config(args.config)

    paths: list[Path] = args.paths or [Path(p) for p in _config_str_list(config, "src", ["."])]
    if not paths:
        paths = [Path()]

    src_roots: list[Path] | None = args.src_roots or None
    exclude = args.exclude or _config_str_list(config, "exclude", [])

    for p in paths:
        if not p.exists():
            sys.stderr.write(f"Error: path does not exist: {p}\n")
            return 2

    check_result, fix_result = check(paths, src_roots=src_roots, exclude=exclude, fix=args.fix)
    _output_text(check_result, fix_result)

    return 1 if check_result.violations else 0


def _load_config(config_path: Path | None) -> dict[str, object]:
    """Load [tool.minport] from pyproject.toml."""
    if config_path is None:
        config_path = Path("pyproject.toml")
    if not config_path.is_file():
        return {}
    try:
        with config_path.open("rb") as f:
            data = tomllib.load(f)
    except (tomllib.TOMLDecodeError, OSError):
        return {}
    tool = data.get("tool", {})
    if isinstance(tool, dict):
        section = tool.get("minport", {})
        if isinstance(section, dict):
            return section
    return {}


def _config_str_list(config: dict[str, object], key: str, default: list[str]) -> list[str]:
    """Extract a list-of-strings value from config with type safety."""
    value = config.get(key)
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return [str(v) for v in value]
    return default


def _output_text(
    result: CheckResult,
    fix_result: FixResult | None = None,
) -> None:
    for v in result.violations:
        sys.stdout.write(f"{v.file_path}:{v.line}:{v.col}: {v.code} {v.message}\n")
    count = len(result.violations)
    if count:
        if fix_result:
            sys.stdout.write(
                f"Found {count} error{'s' if count != 1 else ''}."
                f" Fixed {fix_result.fixes_applied} in {fix_result.files_modified} file"
                f"{'s' if fix_result.files_modified != 1 else ''}.\n",
            )
        else:
            sys.stdout.write(
                f"Found {count} error{'s' if count != 1 else ''}"
                f" ({result.fixable_count} fixable with `minport check --fix`).\n",
            )


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
