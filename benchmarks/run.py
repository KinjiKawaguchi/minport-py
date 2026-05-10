#!/usr/bin/env python3
"""Run minport against fixed targets and report timing statistics.

Targets are cloned by setup.py into .cache/<name>/. Self-target uses
the in-repo src/minport. Each target is timed ``runs`` times after
``warmup`` warm runs; we report median, min, max, stdev, and ms-per-file.

Usage:
    uv run --group benchmarks benchmarks/run.py
    uv run --group benchmarks benchmarks/run.py --runs 10 --warmup 3
    uv run --group benchmarks benchmarks/run.py --only langgraph
"""

from __future__ import annotations

import argparse
import os
import statistics
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = Path(__file__).resolve().parent / ".cache"


@dataclass(frozen=True)
class Target:
    name: str
    path: Path

    @property
    def exists(self) -> bool:
        return self.path.is_dir()

    def file_count(self) -> int:
        return sum(1 for _ in self.path.rglob("*.py"))


def discover_targets() -> list[Target]:
    return [
        Target("self", REPO_ROOT / "src" / "minport"),
        Target("requests", CACHE_DIR / "requests" / "src"),
        Target("flask", CACHE_DIR / "flask" / "src"),
        Target("django", CACHE_DIR / "django" / "django"),
        Target("pandas", CACHE_DIR / "pandas" / "pandas"),
        Target("sympy", CACHE_DIR / "sympy" / "sympy"),
        Target("langgraph", CACHE_DIR / "langgraph" / "libs" / "langgraph" / "langgraph"),
    ]


def time_once(target: Target) -> float:
    """Run minport against target once, return elapsed seconds."""
    start = time.perf_counter()
    # Run via `uv run` so the benchmarks dependency group (langchain etc.)
    # is on the import path. Without this, find_spec resolution against
    # third-party packages in benchmark targets would no-op and hide the
    # cost we want to measure.
    result = subprocess.run(
        ["uv", "run", "--group", "benchmarks", "minport", "check", "--quiet", str(target.path)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    elapsed = time.perf_counter() - start
    # minport exits non-zero when violations are found; that is expected.
    # Treat unexpected failures (e.g. crash, missing binary) as fatal.
    if result.returncode not in (0, 1):
        sys.stderr.write(
            f"[error] minport failed on {target.name} "
            f"(exit {result.returncode}):\n{result.stderr}\n"
        )
        sys.exit(2)
    return elapsed


@dataclass(frozen=True)
class Result:
    target: Target
    samples: tuple[float, ...]
    files: int

    @property
    def median(self) -> float:
        return statistics.median(self.samples)

    @property
    def stdev(self) -> float:
        return statistics.stdev(self.samples) if len(self.samples) > 1 else 0.0

    @property
    def ms_per_file(self) -> float:
        return (self.median * 1000.0) / self.files if self.files else 0.0


def measure(target: Target, warmup: int, runs: int) -> Result:
    for _ in range(warmup):
        time_once(target)
    samples = tuple(time_once(target) for _ in range(runs))
    return Result(target=target, samples=samples, files=target.file_count())


def fmt_seconds(seconds: float) -> str:
    if seconds < 1.0:
        return f"{seconds * 1000:.0f}ms"
    return f"{seconds:.2f}s"


def print_table(results: list[Result]) -> None:
    header = f"{'target':<12} {'files':>6} {'median':>9} {'min':>9} {'max':>9} {'stdev':>9} {'ms/file':>9}"
    print(header)
    print("-" * len(header))
    for r in results:
        print(
            f"{r.target.name:<12} {r.files:>6} "
            f"{fmt_seconds(r.median):>9} "
            f"{fmt_seconds(min(r.samples)):>9} "
            f"{fmt_seconds(max(r.samples)):>9} "
            f"{fmt_seconds(r.stdev):>9} "
            f"{r.ms_per_file:>8.2f} "
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument(
        "--parallel",
        "-p",
        type=int,
        default=1,
        help=(
            "Number of targets to measure concurrently (default: 1). "
            "Higher values finish faster but introduce CPU/IO contention "
            "between targets, so before/after comparisons must use the "
            "same value."
        ),
    )
    parser.add_argument(
        "--only",
        type=str,
        default=None,
        help="Comma-separated subset of target names (e.g. 'self,django')",
    )
    return parser.parse_args()


def select_targets(args: argparse.Namespace) -> list[Target]:
    targets = discover_targets()
    if args.only:
        wanted = {name.strip() for name in args.only.split(",")}
        targets = [t for t in targets if t.name in wanted]
    missing = [t for t in targets if not t.exists]
    if missing:
        names = ", ".join(t.name for t in missing)
        sys.stderr.write(
            f"[error] missing target(s): {names}\n"
            f"        run ./benchmarks/setup.sh first.\n"
        )
        sys.exit(1)
    return targets


def run_measurements(targets: list[Target], warmup: int, runs: int, parallel: int) -> list[Result]:
    if parallel <= 1:
        results: list[Result] = []
        for t in targets:
            sys.stderr.write(f"[measure] {t.name} ...\n")
            results.append(measure(t, warmup, runs))
        return results

    workers = min(parallel, len(targets))
    by_name: dict[str, Result] = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(measure, t, warmup, runs): t for t in targets}
        for t in targets:
            sys.stderr.write(f"[start] {t.name}\n")
        for fut in as_completed(futures):
            t = futures[fut]
            by_name[t.name] = fut.result()
            sys.stderr.write(f"[done]  {t.name}\n")
    return [by_name[t.name] for t in targets]


def main() -> None:
    args = parse_args()
    targets = select_targets(args)
    parallel = max(1, min(args.parallel, len(targets), os.cpu_count() or 1))
    print(f"warmup={args.warmup}  runs={args.runs}  parallel={parallel}\n")
    results = run_measurements(targets, args.warmup, args.runs, parallel)
    print()
    print_table(results)


if __name__ == "__main__":
    main()
