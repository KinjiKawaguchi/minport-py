# benchmarks/

End-to-end performance measurement for minport. Establishes a baseline
against representative Python packages so optimization changes can be
verified quantitatively.

## Quick start

```bash
uv run benchmarks/setup.py                        # clone targets (idempotent)
uv run --group benchmarks benchmarks/run.py       # measure
uv run --group benchmarks benchmarks/run.py --only langgraph
```

## Why `--group benchmarks`

The runner spawns minport via `uv run --group benchmarks` so every
target's third-party dependencies are importable. Without them
`find_spec` returns `None` for third-party modules, minport's resolver
short-circuits, and the per-file cost we want to measure is hidden.
This matches the realistic scenario where users invoke minport from a
project venv where its deps are installed.

## Targets

| target | role |
|---|---|
| `self` | smoke test on minport itself; mostly startup overhead |
| `flask`, `django` | self-contained packages, light third-party use |
| `requests` | small package whose third-party (urllib3) drives find_spec cost |
| `pandas` | scale + numpy resolution chain |
| `sympy` | scale + deep self re-export structure |
| `langgraph` | reproduces the find_spec storm pattern observed in real projects with heavy langchain ecosystem usage |

Targets are pinned by tag in `setup.py` and by version in
`pyproject.toml`'s `benchmarks` group; the two pins are kept in sync so
`find_spec` resolves against the same package version whose source is
being scanned.

## Adding a new target

Three files must change together:

1. `setup.py` — add `(name, url, tag)` to `TARGETS`
2. `pyproject.toml` — pin the same version in `[dependency-groups] benchmarks`
3. `run.py` — add a `Target(...)` entry in `discover_targets()` pointing
   at the package's source subdirectory inside `.cache/<name>/`

Then `uv sync --group benchmarks` and `uv run benchmarks/setup.py`.

## Interpreting results

The runner reports median, min, max, stdev, and **`ms/file`**.

- `median` is the headline number for absolute regression checks.
- `ms/file` is the scaling metric. Compare across targets: a high value
  means per-file resolution cost dominates (typically deep re-export
  chains or heavy third-party graphs), independent of file count.
- `stdev` above ~5% of median usually indicates page-cache variance on
  large targets; raise `--warmup` and/or `--runs` for tighter intervals.

Defaults (`--warmup 1 --runs 3`) prioritize iteration speed. For
publication-quality numbers, use `--warmup 3 --runs 10`.
