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

The cache is invalidated **coarsely** by the ``scope_key`` argument:
whenever the caller's notion of "current Python environment + dep
set" changes, they supply a different ``scope_key`` and the new
cache file replaces the old. This avoids the per-entry ``stat()``
that a finer-grained mtime check would require — a per-entry ``stat``
adds up to seconds of disk I/O on cold filesystems (CI runners, NFS).

Concretely: callers should derive ``scope_key`` from
``sys.executable`` plus the content hash of the project's lock file
(``uv.lock`` / ``requirements*.txt`` / etc). When dependencies change,
the lock file changes, ``scope_key`` changes, and the cache is
implicitly invalidated.

Schema- and minport-version mismatches in the JSON envelope also
trigger a full reload as empty.

Layout: ``<root>/find_spec/<sha256(scope_key)[:16]>.json``.

Not thread-safe; in-memory dict access is not synchronized. Parallel
resolution (issue #54) will add locking.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

from minport import __version__ as _minport_version

_SCHEMA_VERSION = "3"
_MISS: tuple[bool, Path | None] = (False, None)
# Stored value is just the resolved path string (or None for negative cache).
_Entry = str | None


class InstalledOriginCache:
    """In-memory cache for module-path → resolved file path lookups.

    Backed by a single JSON file on disk: loaded once on construction,
    written once on close. Per-operation cost is in memory.
    """

    def __init__(self, root: Path, scope_key: str) -> None:
        cache_dir = root / "find_spec"
        cache_dir.mkdir(parents=True, exist_ok=True)
        scope_hash = hashlib.sha256(scope_key.encode()).hexdigest()[:16]
        self._path = cache_dir / f"{scope_hash}.json"
        self._entries: dict[str, _Entry] = {}
        self._load()

    def get(self, module_path: str) -> tuple[bool, Path | None]:
        """Return (hit, resolved_path). hit=False means caller must compute."""
        if module_path not in self._entries:
            return _MISS
        path_str = self._entries[module_path]
        if path_str is None:
            return (True, None)
        return (True, Path(path_str))

    def set(self, module_path: str, resolved: Path | None) -> None:
        """Record an entry in memory; persisted by ``flush``/``close``."""
        self._entries[module_path] = str(resolved) if resolved is not None else None

    def flush(self) -> None:
        """Write the in-memory entries to disk atomically.

        Uses a temp file + atomic ``rename`` so a crash mid-write leaves the
        previous valid file in place. Write failures (e.g. read-only fs)
        are swallowed: persistence is best-effort.
        """
        envelope = {
            "schema_version": _SCHEMA_VERSION,
            "minport_version": _minport_version,
            "entries": self._entries,
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
            if value is None or isinstance(value, str):
                self._entries[key] = value


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


@contextmanager
def open_origin_cache(
    root: Path | None,
    scope_key: str,
) -> Iterator[InstalledOriginCache | None]:
    """Context manager yielding a cache, or None when disabled or unavailable.

    ``root=None`` disables persistence (caller's explicit signal).
    Initialization failure (read-only fs, etc.) also yields None so the
    check run continues without persistence.
    """
    if root is None:
        yield None
        return
    try:
        cache = InstalledOriginCache(root, scope_key)
    except OSError:
        yield None
        return
    try:
        yield cache
    finally:
        cache.close()
