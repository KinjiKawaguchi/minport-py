"""Tests for the persistent find_spec cache."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from minport._persistent_cache import (
    PersistentSpecCache,
    default_cache_dir,
    spec_cache,
)


class TestPersistentSpecCache:
    def test_set_then_get_returns_cached_path(self, tmp_path: Path) -> None:
        target = tmp_path / "module.py"
        target.write_text("x = 1\n")

        cache = PersistentSpecCache(tmp_path / "cache")
        try:
            cache.set("foo.bar", target)
            cache.flush()
            hit, value = cache.get("foo.bar")
        finally:
            cache.close()

        assert hit
        assert value == target

    def test_set_then_get_caches_none_result(self, tmp_path: Path) -> None:
        cache = PersistentSpecCache(tmp_path / "cache")
        try:
            cache.set("nope.module", None)
            cache.flush()
            hit, value = cache.get("nope.module")
        finally:
            cache.close()

        assert hit
        assert value is None

    def test_get_returns_miss_for_unknown_key(self, tmp_path: Path) -> None:
        cache = PersistentSpecCache(tmp_path / "cache")
        try:
            hit, value = cache.get("never.cached")
        finally:
            cache.close()

        assert not hit
        assert value is None

    def test_get_returns_miss_when_file_deleted(self, tmp_path: Path) -> None:
        target = tmp_path / "vanish.py"
        target.write_text("x = 1\n")

        cache = PersistentSpecCache(tmp_path / "cache")
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

        cache = PersistentSpecCache(tmp_path / "cache")
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

        c1 = PersistentSpecCache(tmp_path / "cache")
        try:
            c1.set("persist", target)
            c1.flush()
        finally:
            c1.close()

        c2 = PersistentSpecCache(tmp_path / "cache")
        try:
            hit, value = c2.get("persist")
        finally:
            c2.close()

        assert hit
        assert value == target

    def test_minport_version_change_wipes_entries(self, tmp_path: Path) -> None:
        target = tmp_path / "old.py"
        target.write_text("x = 1\n")

        c1 = PersistentSpecCache(tmp_path / "cache")
        try:
            c1.set("old", target)
            c1.flush()
        finally:
            c1.close()

        # Re-open after pretending minport upgraded.
        with patch("minport._persistent_cache._minport_version", "999.0.0"):
            c2 = PersistentSpecCache(tmp_path / "cache")
            try:
                hit, _ = c2.get("old")
            finally:
                c2.close()

        assert not hit


class TestSpecCacheContextManager:
    def test_yields_none_when_disabled_via_env(self, tmp_path: Path) -> None:
        with patch.dict(os.environ, {"MINPORT_NO_CACHE": "1"}, clear=False), \
             spec_cache(tmp_path / "cache") as cache:
            assert cache is None

    def test_yields_cache_normally(self, tmp_path: Path) -> None:
        with patch.dict(os.environ, {}, clear=False) as env:
            env.pop("MINPORT_NO_CACHE", None)
            with spec_cache(tmp_path / "cache") as cache:
                assert isinstance(cache, PersistentSpecCache)


class TestDefaultCacheDir:
    def test_minport_cache_dir_env_overrides(self, tmp_path: Path) -> None:
        with patch.dict(os.environ, {"MINPORT_CACHE_DIR": str(tmp_path / "x")}):
            assert default_cache_dir() == tmp_path / "x"

    def test_xdg_cache_home_used_when_set(self, tmp_path: Path) -> None:
        env = {"XDG_CACHE_HOME": str(tmp_path / "xdg")}
        with patch.dict(os.environ, env, clear=False) as actual_env:
            actual_env.pop("MINPORT_CACHE_DIR", None)
            assert default_cache_dir() == tmp_path / "xdg" / "minport"

    def test_falls_back_to_home_cache(self, tmp_path: Path) -> None:
        with patch.dict(os.environ, {"HOME": str(tmp_path)}, clear=False) as env:
            env.pop("MINPORT_CACHE_DIR", None)
            env.pop("XDG_CACHE_HOME", None)
            assert default_cache_dir() == tmp_path / ".cache" / "minport"
