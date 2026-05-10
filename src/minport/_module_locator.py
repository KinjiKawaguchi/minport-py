"""Locate installed Python modules and manipulate dotted module paths.

Wraps ``importlib.util.find_spec`` with the error handling needed to
survive third-party packages whose ``__init__.py`` raises unusual
exceptions during import resolution. Also provides pure functions for
deriving module-path strings (``module_chain``, ``resolve_relative``).

An optional :class:`~minport._persistent_cache.PersistentSpecCache`
short-circuits repeat lookups across runs.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

    from minport._persistent_cache import PersistentSpecCache


def find_installed_source(
    module_path: str,
    *,
    cache: PersistentSpecCache | None = None,
) -> Path | None:
    """Return the .py source file of an installed module, or None."""
    origin = find_installed_origin(module_path, cache=cache)
    if origin is None or origin.suffix != ".py":
        return None
    return origin


def find_installed_origin(
    module_path: str,
    *,
    cache: PersistentSpecCache | None = None,
) -> Path | None:
    """Return any spec.origin of an installed module, or None."""
    if cache is not None:
        hit, value = cache.get(module_path)
        if hit:
            return value
    resolved = _call_find_spec(module_path)
    if cache is not None:
        cache.set(module_path, resolved)
    return resolved


def _call_find_spec(module_path: str) -> Path | None:
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


def module_chain(module_path: str) -> Iterator[str]:
    """Yield *module_path* and every ancestor package it would trigger."""
    parts = module_path.split(".")
    for i in range(1, len(parts) + 1):
        yield ".".join(parts[:i])


def resolve_relative(
    current_module: str,
    target: str,
    level: int,
    *,
    is_package: bool,
) -> str | None:
    """Convert a possibly-relative import to an absolute dotted path.

    ``level`` follows Python semantics: ``0`` means an absolute import, ``1``
    means the current package, ``2`` means its parent, and so on. When the
    current file is a module (not a package), ``level=1`` already refers to
    the parent package. An empty *target* is allowed (``from .. import *``)
    and resolves to just the base package.
    """
    if level == 0:
        return target or None

    parts = current_module.split(".") if current_module else []
    up = level - 1 if is_package else level
    if up >= len(parts):
        return None

    base = parts[: len(parts) - up] if up > 0 else parts
    target_parts = target.split(".") if target else []
    combined = [*base, *target_parts]
    return ".".join(combined) if combined else None
