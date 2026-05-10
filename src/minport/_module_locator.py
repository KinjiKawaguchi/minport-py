"""Locate the source file of an installed Python module.

Wraps ``importlib.util.find_spec`` with the error handling needed to
survive third-party packages whose ``__init__.py`` raises unusual
exceptions during import resolution.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


def find_installed_source(module_path: str) -> Path | None:
    """Return the .py source file of an installed module, or None."""
    origin = find_installed_origin(module_path)
    if origin is None or origin.suffix != ".py":
        return None
    return origin


def find_installed_origin(module_path: str) -> Path | None:
    """Return any spec.origin of an installed module, or None."""
    try:
        spec = importlib.util.find_spec(module_path)
    except Exception:  # noqa: BLE001
        # find_spec executes third-party module code (package __init__.py)
        # during resolution. That code may raise anything — module-level
        # AssertionError for platform guards (click/_winconsole.py),
        # OSError, ImportError, or arbitrary custom exceptions. Treat any
        # failure as "module not usable" and let the caller skip it
        # rather than crashing the whole check run.
        return None
    if spec is None or spec.origin is None:
        return None
    return Path(spec.origin)
