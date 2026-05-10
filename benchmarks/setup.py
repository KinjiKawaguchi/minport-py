#!/usr/bin/env python3
"""Clone benchmark targets at fixed commits into benchmarks/.cache/.

Each target's ref must match the corresponding pin in pyproject.toml's
``benchmarks`` dependency group, so the source minport scans matches the
package version available to ``find_spec`` resolution.

Usage:
    uv run benchmarks/setup.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

CACHE_DIR = Path(__file__).resolve().parent / ".cache"

TARGETS: tuple[tuple[str, str, str], ...] = (
    ("requests", "https://github.com/psf/requests", "v2.32.3"),
    ("flask", "https://github.com/pallets/flask", "3.0.3"),
    ("django", "https://github.com/django/django", "5.1.4"),
    ("pandas", "https://github.com/pandas-dev/pandas", "v2.2.3"),
    ("sympy", "https://github.com/sympy/sympy", "sympy-1.13.3"),
    ("langgraph", "https://github.com/langchain-ai/langgraph", "1.1.9"),
)


def clone(name: str, url: str, ref: str) -> None:
    dest = CACHE_DIR / name
    if dest.is_dir():
        print(f"[skip] {name} (already exists at {dest})")
        return
    print(f"[clone] {name} @ {ref}")
    subprocess.run(
        ["git", "clone", "--depth", "1", "--branch", ref, url, str(dest)],
        check=True,
    )


def main() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    for name, url, ref in TARGETS:
        clone(name, url, ref)
    print(f"\nDone. Targets in {CACHE_DIR}")
    print("\nNext: run the benchmark (uv will sync the benchmarks group):")
    print("  uv run --group benchmarks benchmarks/run.py")


if __name__ == "__main__":
    sys.exit(main())
