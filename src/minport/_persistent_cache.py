"""Persistent SQLite-backed cache for ``find_spec`` results.

The find_spec call is the dominant cost on projects with deep
third-party graphs (langchain, numpy). Within a single run, the
in-process cache in ``ReexportResolver`` collapses duplicate calls.
Across runs, the same module-path lookups recur — so this layer
persists results between invocations.

Invalidation:
- Per-entry: the cached ``resolved_path`` is verified to still exist
  and have the same ``mtime``; if not, treated as a miss.
- Whole-cache: a schema-version + minport-version stored in a meta
  table. Any mismatch wipes the entries table.

Layout: ``<root>/find_spec/<sha256(python_executable)[:16]>.sqlite``.
The per-venv filename means switching venvs creates a fresh cache
without invalidating others.

Not thread-safe; SQLite connections are pinned to the creating
thread. Parallel resolution (issue #54) will add locking.
"""

from __future__ import annotations

import hashlib
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

from minport import __version__ as _minport_version

_SCHEMA_VERSION = "1"
_MISS: tuple[bool, Path | None] = (False, None)


class InstalledOriginCache:
    """SQLite cache for ``module_path → resolved file path | None``."""

    def __init__(self, root: Path) -> None:
        cache_dir = root / "find_spec"
        cache_dir.mkdir(parents=True, exist_ok=True)
        venv_hash = hashlib.sha256(sys.executable.encode()).hexdigest()[:16]
        self._db_path = cache_dir / f"{venv_hash}.sqlite"
        self._conn = sqlite3.connect(self._db_path)
        self._pending: dict[str, tuple[Path | None, float]] = {}
        self._ensure_schema()

    def get(self, module_path: str) -> tuple[bool, Path | None]:
        """Return (hit, resolved_path). hit=False means caller must compute."""
        row = self._conn.execute(
            "SELECT resolved_path, file_mtime FROM entries WHERE module_path = ?",
            (module_path,),
        ).fetchone()
        if row is None:
            return _MISS
        resolved_str, cached_mtime = row
        if resolved_str is None:
            return (True, None)
        resolved = Path(resolved_str)
        # Verify the resolved file still exists with the same mtime; otherwise
        # treat as miss so the caller refreshes the entry.
        try:
            current_mtime = resolved.stat().st_mtime
        except OSError:
            return _MISS
        if current_mtime != cached_mtime:
            return _MISS
        return (True, resolved)

    def set(self, module_path: str, resolved: Path | None) -> None:
        """Buffer an entry for the next ``flush``."""
        mtime = 0.0
        if resolved is not None:
            try:
                mtime = resolved.stat().st_mtime
            except OSError:
                # File vanished between resolution and caching; skip storing
                # rather than caching a doomed entry.
                return
        self._pending[module_path] = (resolved, mtime)

    def flush(self) -> None:
        """Write buffered entries in a single transaction."""
        if not self._pending:
            return
        rows = [
            (mp, str(p) if p is not None else None, mt) for mp, (p, mt) in self._pending.items()
        ]
        with self._conn:
            self._conn.executemany(
                "INSERT OR REPLACE INTO entries(module_path, resolved_path, file_mtime) "
                "VALUES (?, ?, ?)",
                rows,
            )
        self._pending.clear()

    def close(self) -> None:
        """Flush pending writes and close the SQLite connection."""
        self.flush()
        self._conn.close()

    def _ensure_schema(self) -> None:
        with self._conn:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS meta (  key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS entries ("
                "  module_path TEXT PRIMARY KEY,"
                "  resolved_path TEXT,"
                "  file_mtime REAL NOT NULL)"
            )
        if not self._meta_matches():
            self._wipe_entries()
            self._stamp_meta()

    def _meta_matches(self) -> bool:
        rows = dict(self._conn.execute("SELECT key, value FROM meta").fetchall())
        return (
            rows.get("schema_version") == _SCHEMA_VERSION
            and rows.get("minport_version") == _minport_version
        )

    def _wipe_entries(self) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM entries")

    def _stamp_meta(self) -> None:
        with self._conn:
            self._conn.executemany(
                "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                [
                    ("schema_version", _SCHEMA_VERSION),
                    ("minport_version", _minport_version),
                ],
            )


@contextmanager
def open_origin_cache(root: Path | None) -> Iterator[InstalledOriginCache | None]:
    """Context manager yielding a cache, or None when disabled or unavailable.

    ``root=None`` disables persistence (caller's explicit signal).
    Initialization failure (read-only fs, locked SQLite, etc.) also
    yields None so the check run continues without persistence.
    """
    if root is None:
        yield None
        return
    try:
        cache = InstalledOriginCache(root)
    except (OSError, sqlite3.Error):
        yield None
        return
    try:
        yield cache
    finally:
        cache.close()
