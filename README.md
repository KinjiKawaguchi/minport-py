[![PyPI version](https://img.shields.io/pypi/v/minport)](https://pypi.org/project/minport/)
[![Python versions](https://img.shields.io/pypi/pyversions/minport)](https://pypi.org/project/minport/)
[![CI](https://github.com/KinjiKawaguchi/minport/actions/workflows/ci.yml/badge.svg)](https://github.com/KinjiKawaguchi/minport/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

# minport

A Python linter that finds unnecessarily long import paths and suggests shorter alternatives by tracing re-export chains.

## Problem

Python packages expose public APIs through re-exports, but developers often import from deep internal paths instead of the canonical public interface:

```python
# Before (unnecessarily long)
from pydantic.fields import FieldInfo
from sqlalchemy.orm.session import Session
from myproject.domain.user.models import User

print(user.name)  # Still works, but...
```

This creates three problems:

1. **Readability**: Internal paths obscure the public interface
2. **Fragility**: Internal paths break when package maintainers refactor internals (re-exports are the stable API)
3. **Inconsistency**: Same name imported from different paths across the codebase

## Quick Start

```bash
pip install minport
```

```python
# models.py
from pydantic import FieldInfo  # Correct: shorter public path
from pydantic.fields import FieldInfo  # Would be flagged as MP001
```

```bash
minport check src/
# src/models.py:1:1: MP001 `from pydantic.fields import FieldInfo` can be shortened to `from pydantic import FieldInfo`
```

## Usage

### CLI

```bash
minport check src/                       # Check a directory
minport check src/models.py              # Check a single file
minport check src/ --src src/            # Set import resolution root
minport check src/ --exclude "tests/*"   # Exclude patterns
minport check src/ --fix                 # Check and auto-fix
minport check src/ --quiet               # Suppress the summary line
```

**Exit codes:** `0` = no violations, `1` = violations found, `2` = error (e.g. path not found).

### With --fix

```bash
minport check src/ --fix
# Modifies files in-place. Verify with `git diff` before committing.
```

## Configuration

```toml
# pyproject.toml
[tool.minport]
src = ["src"]                    # Import resolution root(s)
exclude = ["tests/*", "migrations/*"]   # Patterns to exclude
```

CLI arguments override `pyproject.toml` settings.

## Rules

| Code | Name | Description |
|------|------|-------------|
| MP001 | shorter-import-available | A shorter import path is available via re-exports |

### Safety

- **No modifications without `--fix`**: Read-only by default
- **Collision detection**: If a name exists in multiple paths, the import is not flagged (ambiguous)
- **Syntax error tolerance**: Malformed Python files are skipped with a warning (doesn't break the entire check)

## How It Works

For each `from X.Y.Z import Name`:

1. Decompose the module path: `[X, X.Y, X.Y.Z]`
2. For each candidate path (shortest first), check if `Name` is re-exported there
3. Re-export detection via AST analysis of `__init__.py`:
   - `from .submodule import Name` — explicit re-export
   - `from .submodule import Name as Name` — PEP 484 explicit form
   - `__all__ = ["Name", ...]` — public API declaration
4. Return the shortest match (if shorter than the original)

Works with:
- Project packages (analyzes `src/` and `__init__.py` files)
- Third-party packages (uses `importlib.util.find_spec` + AST analysis)

## Limitations

- v0.1 does not rewrite `import X.Y.Z` (only `from ... import` statements)
- Type inference is package-boundary only (no cross-package resolution)
- Does not analyze `from X import *` or dynamic imports
- No IDE integration yet

## pre-commit

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/KinjiKawaguchi/minport
    rev: v0.1.0
    hooks:
      - id: minport
        args: [check, src/]
        stages: [commit]
```

## Contributing

Development setup:

```bash
git clone https://github.com/KinjiKawaguchi/minport.git
cd minport
uv sync
uv run pytest --cov=minport
uv run ruff check src/ tests/
```

- [DeepWiki](https://deepwiki.com/KinjiKawaguchi/minport) — AI-generated codebase documentation

## License

MIT
