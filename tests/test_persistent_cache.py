"""Tests for the persistent find_spec cache."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

from minport._module_locator import find_installed_origin
from minport._persistent_cache import (
    _SCHEMA_VERSION,
    InstalledOriginCache,
    _minport_version,
    open_origin_cache,
)

if TYPE_CHECKING:
    import pytest


class TestInstalledOriginCache:
    def test_set_then_get_returns_cached_path(self, tmp_path: Path) -> None:
        target = tmp_path / "module.py"
        target.write_text("x = 1\n")

        cache = InstalledOriginCache(tmp_path / "cache")
        try:
            cache.set("foo.bar", target)
            cache.flush()
            hit, value = cache.get("foo.bar")
        finally:
            cache.close()

        assert hit
        assert value == target

    def test_set_then_get_caches_none_result(self, tmp_path: Path) -> None:
        cache = InstalledOriginCache(tmp_path / "cache")
        try:
            cache.set("nope.module", None)
            cache.flush()
            hit, value = cache.get("nope.module")
        finally:
            cache.close()

        assert hit
        assert value is None

    def test_get_returns_miss_for_unknown_key(self, tmp_path: Path) -> None:
        cache = InstalledOriginCache(tmp_path / "cache")
        try:
            hit, value = cache.get("never.cached")
        finally:
            cache.close()

        assert not hit
        assert value is None

    def test_get_returns_miss_when_file_deleted(self, tmp_path: Path) -> None:
        target = tmp_path / "vanish.py"
        target.write_text("x = 1\n")

        cache = InstalledOriginCache(tmp_path / "cache")
        try:
            cache.set("vanish", target)
            cache.flush()
            target.unlink()
            hit, value = cache.get("vanish")
        finally:
            cache.close()

        assert not hit
        assert value is None

    def test_get_returns_miss_when_mtime_changed(self, tmp_path: Path) -> None:
        target = tmp_path / "modified.py"
        target.write_text("x = 1\n")

        cache = InstalledOriginCache(tmp_path / "cache")
        try:
            cache.set("modified", target)
            cache.flush()
            # Force a different mtime by writing newer content.
            os.utime(target, (target.stat().st_atime, target.stat().st_mtime + 100))
            hit, _ = cache.get("modified")
        finally:
            cache.close()

        assert not hit

    def test_cache_survives_close_reopen(self, tmp_path: Path) -> None:
        target = tmp_path / "persist.py"
        target.write_text("x = 1\n")

        c1 = InstalledOriginCache(tmp_path / "cache")
        try:
            c1.set("persist", target)
            c1.flush()
        finally:
            c1.close()

        c2 = InstalledOriginCache(tmp_path / "cache")
        try:
            hit, value = c2.get("persist")
        finally:
            c2.close()

        assert hit
        assert value == target

    def test_set_skips_when_file_vanished(self, tmp_path: Path) -> None:
        cache = InstalledOriginCache(tmp_path / "cache")
        try:
            cache.set("ghost", tmp_path / "does-not-exist.py")
            cache.flush()
            hit, _ = cache.get("ghost")
        finally:
            cache.close()

        assert not hit  # nothing was stored, since stat() raised OSError

    def test_minport_version_change_wipes_entries(self, tmp_path: Path) -> None:
        target = tmp_path / "old.py"
        target.write_text("x = 1\n")

        c1 = InstalledOriginCache(tmp_path / "cache")
        try:
            c1.set("old", target)
            c1.flush()
        finally:
            c1.close()

        # Re-open after pretending minport upgraded.
        with patch("minport._persistent_cache._minport_version", "999.0.0"):
            c2 = InstalledOriginCache(tmp_path / "cache")
            try:
                hit, _ = c2.get("old")
            finally:
                c2.close()

        assert not hit


class TestFindInstalledOriginWithCache:
    def test_first_call_writes_to_cache(self, tmp_path: Path) -> None:
        cache = InstalledOriginCache(tmp_path / "cache")
        try:
            # 'pytest' is installed in the dev env with a real .py origin.
            # (Stdlib modules like 'os' are 'frozen' on 3.11+ and would be
            # skipped by set() since Path('frozen').stat() raises OSError.)
            result = find_installed_origin("pytest", cache=cache)
            cache.flush()
            hit, cached = cache.get("pytest")
        finally:
            cache.close()

        assert result is not None
        assert hit
        assert cached == result


class TestOpenOriginCacheContextManager:
    def test_yields_none_when_root_is_none(self) -> None:
        with open_origin_cache(None) as cache:
            assert cache is None

    def test_yields_cache_when_root_given(self, tmp_path: Path) -> None:
        with open_origin_cache(tmp_path / "cache") as cache:
            assert isinstance(cache, InstalledOriginCache)

    def test_yields_none_on_init_failure(self, tmp_path: Path) -> None:
        # Pass a path under a regular file: mkdir fails with NotADirectoryError.
        blocker = tmp_path / "regular-file"
        blocker.write_text("x")
        with open_origin_cache(blocker) as cache:
            assert cache is None


class TestLoadValidation:
    """The on-disk JSON envelope is validated; malformed/corrupt files
    must be treated as empty rather than crashing."""

    @staticmethod
    def _cache_file(root: Path) -> Path:
        cache = InstalledOriginCache(root)
        path = cache._path  # type: ignore[attr-defined]
        cache.close()
        path.unlink(missing_ok=True)
        return path

    def test_corrupted_json_is_ignored(self, tmp_path: Path) -> None:
        path = self._cache_file(tmp_path / "cache")
        path.write_text("{ not valid json")
        cache = InstalledOriginCache(tmp_path / "cache")
        try:
            assert cache.get("anything") == (False, None)
        finally:
            cache.close()

    def test_non_dict_envelope_is_ignored(self, tmp_path: Path) -> None:
        path = self._cache_file(tmp_path / "cache")
        path.write_text('["not", "a", "dict"]')
        cache = InstalledOriginCache(tmp_path / "cache")
        try:
            assert cache.get("anything") == (False, None)
        finally:
            cache.close()

    def test_non_dict_entries_field_is_ignored(self, tmp_path: Path) -> None:
        path = self._cache_file(tmp_path / "cache")
        path.write_text(
            json.dumps(
                {
                    "schema_version": _SCHEMA_VERSION,
                    "minport_version": _minport_version,
                    "entries": "not a dict",
                }
            )
        )
        cache = InstalledOriginCache(tmp_path / "cache")
        try:
            assert cache.get("anything") == (False, None)
        finally:
            cache.close()

    def test_malformed_entries_are_skipped_individually(self, tmp_path: Path) -> None:
        target = tmp_path / "real.py"
        target.write_text("x = 1\n")
        good_mtime = target.stat().st_mtime
        path = self._cache_file(tmp_path / "cache")
        path.write_text(
            json.dumps(
                {
                    "schema_version": _SCHEMA_VERSION,
                    "minport_version": _minport_version,
                    "entries": {
                        "bad_shape": [1, 2, 3],
                        "bad_path_type": [42, 1.0],
                        "bad_mtime_type": ["x", "not float"],
                        "good": [str(target), good_mtime],
                    },
                }
            )
        )
        cache = InstalledOriginCache(tmp_path / "cache")
        try:
            assert cache.get("good") == (True, target)
            assert cache.get("bad_shape") == (False, None)
            assert cache.get("bad_path_type") == (False, None)
            assert cache.get("bad_mtime_type") == (False, None)
        finally:
            cache.close()


class TestFlushFailure:
    def test_flush_swallows_oserror(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        cache = InstalledOriginCache(tmp_path / "cache")
        target = tmp_path / "real.py"
        target.write_text("x = 1\n")
        cache.set("x", target)

        original = Path.write_text

        def boom(self: Path, *args: object, **kwargs: object) -> int:
            if self.suffix == ".tmp":
                msg = "disk full"
                raise OSError(msg)
            return original(self, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(Path, "write_text", boom)
        cache.close()
