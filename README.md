[![PyPI version](https://img.shields.io/pypi/v/minport)](https://pypi.org/project/minport/)
[![Python versions](https://img.shields.io/pypi/pyversions/minport)](https://pypi.org/project/minport/)
[![CI](https://github.com/KinjiKawaguchi/minport/actions/workflows/ci.yml/badge.svg)](https://github.com/KinjiKawaguchi/minport/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

# minport

A Python linter that finds unnecessarily long import paths and suggests shorter alternatives by tracing re-export chains.

## The Problem

Python packages expose public APIs through re-exports, but developers often import from deep internal paths instead of the canonical public interface:

```python
# Unnecessarily long — these reach into internal modules
from pydantic.fields import FieldInfo
from sqlalchemy.orm.session import Session
from myproject.domain.user.models import User

# Shorter — these use the public re-export path
from pydantic import FieldInfo
from sqlalchemy.orm import Session
from myproject.domain import User
```

Long import paths are:

1. **Harder to read**: Internal paths obscure the public interface
2. **Fragile**: Internal paths break when package maintainers refactor internals (re-exports are the stable API)
3. **Inconsistent**: Same name imported from different paths across the codebase

## Installation

```bash
pip install minport
```

```bash
# or with uv
uv add --dev minport
```

```bash
# or with pipx (for global CLI usage)
pipx install minport
```

**Requirements:** Python 3.11+ / No runtime dependencies.

## Quick Start

```bash
minport check src/
# src/models.py:3:1: MP001 `from pydantic.fields import FieldInfo` can be shortened to `from pydantic import FieldInfo`
# Found 1 error (checked 12 files, 1 fixable with `minport check --fix`).

minport check src/ --fix
# Found 1 error (checked 12 files, fixed 1 in 1 file).
```

## Usage

```bash
minport check src/                       # Check a directory
minport check src/models.py              # Check a single file
minport check src/ --src src/            # Set import resolution root
minport check src/ --exclude "tests/*"   # Exclude patterns (overrides defaults)
minport check src/ --extend-exclude "generated/*"  # Add to default excludes
minport check src/ --config path/to/pyproject.toml  # Custom config path
minport check src/ --fix                 # Auto-fix in place
minport check src/ --quiet               # Suppress the summary line
minport check src/ --output-format github  # output for github annotations
```

**Exit codes:** `0` = no violations, `1` = violations found, `2` = error (e.g. path not found).

## Configuration

Configure minport in `pyproject.toml`:

```toml
[tool.minport]
src = ["src"]                        # Import resolution root(s)
exclude = ["tests/*", "migrations/*"]  # Exclude patterns (overrides defaults)
extend-exclude = ["generated/*"]     # Add patterns without overriding defaults
```

CLI arguments override `pyproject.toml` settings.

### Default Excludes

minport automatically skips common non-source directories (`.venv`, `__pycache__`, `.git`, `node_modules`, `dist`, `site-packages`, etc.). Use `--exclude` to override these defaults entirely, or `--extend-exclude` to add patterns on top of them.

## Rules

| Code | Name | Description | Fixable |
|------|------|-------------|---------|
| MP001 | shorter-import-available | A shorter import path is available via re-exports | Yes |

## Inline Suppression

Add `# minport: ignore` to suppress violations on specific imports.

**Single-line import:**

```python
from pydantic.fields import FieldInfo  # minport: ignore
```

**Multi-line import — suppress all names:**

```python
from pydantic.fields import (  # minport: ignore
    FieldInfo,
    Field,
)
```

**Multi-line import — suppress a specific name:**

```python
from pydantic.fields import (
    FieldInfo,  # minport: ignore  ← only FieldInfo is suppressed
    Field,      # ← this can still be flagged
)
```

## How It Works

For each `from X.Y.Z import Name`:

1. Decompose the module path: `[X, X.Y, X.Y.Z]`
2. For each candidate path (shortest first), check if `Name` is re-exported there
3. Re-export detection via AST analysis of `__init__.py`:
   - `from .submodule import Name` — explicit re-export
   - `from .submodule import Name as Name` — PEP 484 explicit form
   - `from .submodule import *` — wildcard (recursively resolved, respects `__all__`)
   - `__all__ = ["Name", ...]` — public API declaration
4. Return the shortest match (if shorter than the original)

Works with both **project packages** (analyzes `__init__.py` files) and **third-party packages** (uses `importlib.util.find_spec` + AST analysis, no runtime imports).

### Safety

- **No modifications without `--fix`**: Read-only by default
- **Collision detection**: If a name exists in multiple candidate paths, the import is not flagged
- **Syntax error tolerance**: Malformed Python files are skipped with a warning
- **`--fix` writes in place**: Always verify changes with `git diff` before committing

## Integrations

### pre-commit

```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: minport
        name: minport
        entry: minport check
        language: python
        types: [python]
        additional_dependencies: ["minport"]
```

### GitHub Actions

```yaml
# .github/workflows/lint.yml
jobs:
  minport:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
      - run: pip install minport
      - run: minport check src/ --output-format github
```
The `--output-format github` flag emits [GitHub Actions workflow commands](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-commands#setting-an-error-message), so violations appear as inline annotations on the PR file view.

## Limitations

- Only rewrites `from X.Y.Z import Name` (not `import X.Y.Z`)
- Does not analyze dynamic or runtime imports
- No IDE integration yet

## Contributing

```bash
git clone https://github.com/KinjiKawaguchi/minport.git
cd minport
uv sync
uv run pytest --cov=minport
uv run ruff check src/ tests/
```

- [DeepWiki](https://deepwiki.com/KinjiKawaguchi/minport) — AI-generated codebase documentation

## License

[MIT](LICENSE)
