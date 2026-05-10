"""Persistent JSON-backed cache for ``find_spec`` results.

The find_spec call is the dominant cost on projects with deep
third-party graphs (langchain, numpy). Within a single run, the
in-process cache in ``ReexportResolver`` collapses duplicate calls.
Across runs, the same module-path lookups recur — so this layer
persists results between invocations.

Storage model:

The cache loads the whole entry table into memory on open and writes
it back as a single JSON file (via temp + atomic rename) on close.
This keeps the per-operation cost in memory and reduces filesystem
contact to one read at start and one write at end.

Why not SQLite: SQLite's per-operation file locking turns into a
network round-trip on high-latency filesystems (NFS, SMB, sshfs,
WSL2 cross-mount), making the cache slower than no cache at all.
Two syscalls per run sidesteps that entirely.

Invalidation:
- Per-entry: cached ``resolved_path`` is verified to still exist with
  the same ``mtime``; otherwise treated as a miss.
- Whole-cache: a schema-version + minport-version recorded in the
  JSON envelope. Any mismatch is treated as an empty cache.

Layout: ``<root>/find_spec/<sha256(python_executable)[:16]>.json``.
The per-venv filename means switching venvs creates a fresh cache
without invalidating others.

Not thread-safe; in-memory dict access is not synchronized. Parallel
resolution (issue #54) will add locking.
"""

from __future__ import annotations

import hashlib
import json
import sys
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

from minport import __version__ as _minport_version

_SCHEMA_VERSION = "2"
_MISS: tuple[bool, Path | None] = (False, None)
# Stored value: (resolved_path_str_or_None, file_mtime).
_Entry = tuple[str | None, float]
_ENTRY_FIELDS = 2  # serialized entries are [path_or_null, mtime]


class InstalledOriginCache:
    """In-memory cache for module-path → resolved file path lookups.

    Backed by a single JSON file on disk: loaded once on construction,
    written once on close. Per-operation cost is in memory.
    """

    def __init__(self, root: Path) -> None:
        cache_dir = root / "find_spec"
        cache_dir.mkdir(parents=True, exist_ok=True)
        venv_hash = hashlib.sha256(sys.executable.encode()).hexdigest()[:16]
        self._path = cache_dir / f"{venv_hash}.json"
        self._entries: dict[str, _Entry] = {}
        self._load()

    def get(self, module_path: str) -> tuple[bool, Path | None]:
        """Return (hit, resolved_path). hit=False means caller must compute."""
        entry = self._entries.get(module_path)
        if entry is None:
            return _MISS
        resolved_str, cached_mtime = entry
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
        """Record an entry in memory; persisted by ``flush``/``close``."""
        mtime = 0.0
        if resolved is not None:
            try:
                mtime = resolved.stat().st_mtime
            except OSError:
                # File vanished between resolution and caching; skip storing
                # rather than caching a doomed entry.
                return
        path_str = str(resolved) if resolved is not None else None
        self._entries[module_path] = (path_str, mtime)

    def flush(self) -> None:
        """Write the in-memory entries to disk atomically.

        Uses a temp file + atomic ``rename`` so a crash mid-write leaves the
        previous valid file in place. Write failures (e.g. read-only fs)
        are swallowed: persistence is best-effort.
        """
        envelope = {
            "schema_version": _SCHEMA_VERSION,
            "minport_version": _minport_version,
            "entries": {k: list(v) for k, v in self._entries.items()},
        }
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        try:
            tmp.write_text(json.dumps(envelope))
            tmp.replace(self._path)
        except OSError:
            # Best-effort: don't fail the run because cache write failed.
            with suppress(OSError):
                tmp.unlink()

    def close(self) -> None:
        """Flush in-memory state to disk."""
        self.flush()

    def _load(self) -> None:
        raw_entries = _read_envelope(self._path)
        if raw_entries is None:
            return
        for key, value in raw_entries.items():
            entry = _coerce_entry(key, value)
            if entry is not None:
                self._entries[key] = entry


def _read_envelope(path: Path) -> dict[str, object] | None:
    """Return the raw ``entries`` dict from a cache file, or None to skip."""
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    if (
        data.get("schema_version") != _SCHEMA_VERSION
        or data.get("minport_version") != _minport_version
    ):
        return None
    raw = data.get("entries")
    if not isinstance(raw, dict):
        return None
    return raw


def _coerce_entry(key: str, value: object) -> _Entry | None:
    """Validate a single deserialized entry; return None if malformed.

    JSON guarantees ``key`` is a ``str``; the surrounding ``dict`` shape
    is verified before this is called, so only the ``value`` side needs
    validation.
    """
    del key  # signature kept symmetrical with caller iteration
    if not isinstance(value, list) or len(value) != _ENTRY_FIELDS:
        return None
    path_value, mtime = value
    if path_value is not None and not isinstance(path_value, str):
        return None
    if not isinstance(mtime, (int, float)):
        return None
    return (path_value, float(mtime))


@contextmanager
def open_origin_cache(root: Path | None) -> Iterator[InstalledOriginCache | None]:
    """Context manager yielding a cache, or None when disabled or unavailable.

    ``root=None`` disables persistence (caller's explicit signal).
    Initialization failure (read-only fs, etc.) also yields None so the
    check run continues without persistence.
    """
    if root is None:
        yield None
        return
    try:
        cache = InstalledOriginCache(root)
    except OSError:
        yield None
        return
    try:
        yield cache
    finally:
        cache.close()
