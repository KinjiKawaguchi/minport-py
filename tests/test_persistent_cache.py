"""Tests for the persistent find_spec cache."""

from __future__ import annotations

import json
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


_SCOPE = "test-scope"


class TestInstalledOriginCache:
    def test_set_then_get_returns_cached_path(self, tmp_path: Path) -> None:
        target = tmp_path / "module.py"
        target.write_text("x = 1\n")

        cache = InstalledOriginCache(tmp_path / "cache", _SCOPE)
        try:
            cache.set("foo.bar", target)
            cache.flush()
            hit, value = cache.get("foo.bar")
        finally:
            cache.close()

        assert hit
        assert value == target

    def test_set_then_get_caches_none_result(self, tmp_path: Path) -> None:
        cache = InstalledOriginCache(tmp_path / "cache", _SCOPE)
        try:
            cache.set("nope.module", None)
            cache.flush()
            hit, value = cache.get("nope.module")
        finally:
            cache.close()

        assert hit
        assert value is None

    def test_get_returns_miss_for_unknown_key(self, tmp_path: Path) -> None:
        cache = InstalledOriginCache(tmp_path / "cache", _SCOPE)
        try:
            hit, value = cache.get("never.cached")
        finally:
            cache.close()

        assert not hit
        assert value is None

    def test_get_returns_cached_path_even_if_file_deleted(self, tmp_path: Path) -> None:
        # Without per-entry mtime verification, the cache trusts its scope_key
        # for invalidation. Files that disappear without a scope change still
        # produce a (True, Path) hit; the caller is responsible for handling
        # a path that no longer exists (and does — _parse returns None).
        target = tmp_path / "vanish.py"
        target.write_text("x = 1\n")

        cache = InstalledOriginCache(tmp_path / "cache", _SCOPE)
        try:
            cache.set("vanish", target)
            cache.flush()
            target.unlink()
            hit, value = cache.get("vanish")
        finally:
            cache.close()

        assert hit
        assert value == target

    def test_cache_survives_close_reopen(self, tmp_path: Path) -> None:
        target = tmp_path / "persist.py"
        target.write_text("x = 1\n")

        c1 = InstalledOriginCache(tmp_path / "cache", _SCOPE)
        try:
            c1.set("persist", target)
            c1.flush()
        finally:
            c1.close()

        c2 = InstalledOriginCache(tmp_path / "cache", _SCOPE)
        try:
            hit, value = c2.get("persist")
        finally:
            c2.close()

        assert hit
        assert value == target

    def test_different_scope_keys_use_different_cache_files(self, tmp_path: Path) -> None:
        target = tmp_path / "real.py"
        target.write_text("x = 1\n")

        c1 = InstalledOriginCache(tmp_path / "cache", "scope-A")
        try:
            c1.set("key", target)
            c1.flush()
        finally:
            c1.close()

        c2 = InstalledOriginCache(tmp_path / "cache", "scope-B")
        try:
            hit, _ = c2.get("key")
        finally:
            c2.close()

        assert not hit  # scope-B has its own (empty) file

    def test_minport_version_change_wipes_entries(self, tmp_path: Path) -> None:
        target = tmp_path / "old.py"
        target.write_text("x = 1\n")

        c1 = InstalledOriginCache(tmp_path / "cache", _SCOPE)
        try:
            c1.set("old", target)
            c1.flush()
        finally:
            c1.close()

        with patch("minport._persistent_cache._minport_version", "999.0.0"):
            c2 = InstalledOriginCache(tmp_path / "cache", _SCOPE)
            try:
                hit, _ = c2.get("old")
            finally:
                c2.close()

        assert not hit


class TestFindInstalledOriginWithCache:
    def test_first_call_writes_to_cache(self, tmp_path: Path) -> None:
        cache = InstalledOriginCache(tmp_path / "cache", _SCOPE)
        try:
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
        with open_origin_cache(None, _SCOPE) as cache:
            assert cache is None

    def test_yields_cache_when_root_given(self, tmp_path: Path) -> None:
        with open_origin_cache(tmp_path / "cache", _SCOPE) as cache:
            assert isinstance(cache, InstalledOriginCache)

    def test_yields_none_on_init_failure(self, tmp_path: Path) -> None:
        # Pass a path under a regular file: mkdir fails with NotADirectoryError.
        blocker = tmp_path / "regular-file"
        blocker.write_text("x")
        with open_origin_cache(blocker, _SCOPE) as cache:
            assert cache is None


class TestLoadValidation:
    """The on-disk JSON envelope is validated; malformed/corrupt files
    must be treated as empty rather than crashing.
    """

    @staticmethod
    def _cache_file(root: Path) -> Path:
        cache = InstalledOriginCache(root, _SCOPE)
        path = cache._path  # type: ignore[attr-defined]
        cache.close()
        path.unlink(missing_ok=True)
        return path

    def test_corrupted_json_is_ignored(self, tmp_path: Path) -> None:
        path = self._cache_file(tmp_path / "cache")
        path.write_text("{ not valid json")
        cache = InstalledOriginCache(tmp_path / "cache", _SCOPE)
        try:
            assert cache.get("anything") == (False, None)
        finally:
            cache.close()

    def test_non_dict_envelope_is_ignored(self, tmp_path: Path) -> None:
        path = self._cache_file(tmp_path / "cache")
        path.write_text('["not", "a", "dict"]')
        cache = InstalledOriginCache(tmp_path / "cache", _SCOPE)
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
        cache = InstalledOriginCache(tmp_path / "cache", _SCOPE)
        try:
            assert cache.get("anything") == (False, None)
        finally:
            cache.close()

    def test_malformed_entries_are_skipped_individually(self, tmp_path: Path) -> None:
        target = tmp_path / "real.py"
        target.write_text("x = 1\n")
        path = self._cache_file(tmp_path / "cache")
        path.write_text(
            json.dumps(
                {
                    "schema_version": _SCHEMA_VERSION,
                    "minport_version": _minport_version,
                    "entries": {
                        "bad_int": 42,
                        "bad_list": [1, 2],
                        "good": str(target),
                        "good_null": None,
                    },
                }
            )
        )
        cache = InstalledOriginCache(tmp_path / "cache", _SCOPE)
        try:
            assert cache.get("good") == (True, target)
            assert cache.get("good_null") == (True, None)
            assert cache.get("bad_int") == (False, None)
            assert cache.get("bad_list") == (False, None)
        finally:
            cache.close()


class TestFlushFailure:
    def test_flush_swallows_oserror(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        cache = InstalledOriginCache(tmp_path / "cache", _SCOPE)
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
