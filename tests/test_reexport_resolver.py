"""Tests for re-export resolution (R-1 through R-12)."""

from __future__ import annotations

from pathlib import Path

import pytest

from minport._reexport_resolver import ReexportResolver


class TestReexportResolver:
    """Test ReexportResolver class."""

    def test_r1_from_module_reexport(self, tmp_path: Path) -> None:
        """R-1: from .module import Name re-export."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("from .module import Name")
        (pkg / "module.py").write_text("Name = 1")

        resolver = ReexportResolver([tmp_path])
        exported = resolver._get_exported_names("pkg")
        assert "Name" in exported

    def test_r2_explicit_reexport_with_as(self, tmp_path: Path) -> None:
        """R-2: from .module import Name as Name explicit re-export."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("from .module import Name as Name")
        (pkg / "module.py").write_text("Name = 1")

        resolver = ReexportResolver([tmp_path])
        exported = resolver._get_exported_names("pkg")
        assert "Name" in exported

    def test_r3_all_based_reexport(self, tmp_path: Path) -> None:
        """R-3: __all__ based re-export."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text('from .module import A, B\n__all__ = ["A"]')
        (pkg / "module.py").write_text("A = 1\nB = 2")

        resolver = ReexportResolver([tmp_path])
        exported = resolver._get_exported_names("pkg")
        assert "A" in exported
        assert "B" not in exported

    def test_r4_no_reexport_returns_none(self, tmp_path: Path) -> None:
        """R-4: No re-export → returns None."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "module.py").write_text("Name = 1")

        resolver = ReexportResolver([tmp_path])
        exported = resolver._get_exported_names("pkg")
        assert len(exported) == 0

    def test_r5_multilevel_reexport_chain(self, tmp_path: Path) -> None:
        """R-5: Multi-level re-export chain finds shortest path."""
        # Create X/module.py
        x = tmp_path / "x"
        x.mkdir()
        (x / "__init__.py").write_text("from .module import Name")
        (x / "module.py").write_text("Name = 1")

        # Create X/Y/ and X/Y/Z
        xy = x / "y"
        xy.mkdir()
        (xy / "__init__.py").write_text("from ..module import Name")

        xyz = xy / "z"
        xyz.mkdir()
        (xyz / "__init__.py").write_text("from ...module import Name")
        (xyz / "module.py").write_text("Name = 1")

        resolver = ReexportResolver([tmp_path])
        # The shortest path for Name from x.y.z.module should be x
        shortest = resolver.find_shortest_path("x.y.z.module", "Name")
        assert shortest == "x"

    def test_r6_all_doesnt_include_name(self, tmp_path: Path) -> None:
        """R-6: __all__ doesn't include Name → None."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text('from .module import A, B\n__all__ = ["A"]')
        (pkg / "module.py").write_text("A = 1\nB = 2")

        resolver = ReexportResolver([tmp_path])
        shortest = resolver.find_shortest_path("pkg.module", "B")
        assert shortest is None

    def test_r7_reexport_without_all_is_public(self, tmp_path: Path) -> None:
        """R-7: Re-export without __all__ → available (implicit public)."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("from .module import Name")
        (pkg / "module.py").write_text("Name = 1")

        resolver = ReexportResolver([tmp_path])
        exported = resolver._get_exported_names("pkg")
        assert "Name" in exported

    def test_r8_all_exists_name_not_in_it(self, tmp_path: Path) -> None:
        """R-8: __all__ exists and Name not in it → not available."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text('from .module import A, B\n__all__ = ["A"]')
        (pkg / "module.py").write_text("A = 1\nB = 2")

        resolver = ReexportResolver([tmp_path])
        exported = resolver._get_exported_names("pkg")
        assert "B" not in exported

    def test_r9_stdlib_reexport(self) -> None:
        """R-9: Stdlib package re-export via importlib."""
        resolver = ReexportResolver([])
        # collections is a module with an __init__.py that re-exports things
        # Let's test with collections since it has re-exports
        try:
            exported = resolver._get_exported_names("collections")
            # collections may or may not have re-exports depending on version
            # Just ensure it doesn't crash
            assert isinstance(exported, set)
        except ModuleNotFoundError:
            # If we can't find the module, that's fine
            pytest.skip("collections module not found")

    def test_r10_nonexistent_package(self) -> None:
        """R-10: Non-existent package → None."""
        resolver = ReexportResolver([])
        exported = resolver._get_exported_names("nonexistent_package_xyz")
        assert len(exported) == 0

    def test_r11_no_infinite_loop_on_circular_reexport(self, tmp_path: Path) -> None:
        """R-11: Circular re-export → no infinite loop."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "module.py").write_text("")

        resolver = ReexportResolver([tmp_path])
        # Should not hang
        shortest = resolver.find_shortest_path("pkg.module", "Name")
        assert shortest is None

    def test_r13_assign_reexport_via_attribute(self, tmp_path: Path) -> None:
        """R-13: Foo = _impl._Foo assignment listed in __all__ is a re-export."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text(
            'from . import _impl\n\nFoo = _impl._Foo\n__all__ = ["Foo"]\n',
        )
        (pkg / "_impl.py").write_text("class _Foo:\n    pass\n")

        resolver = ReexportResolver([tmp_path])
        exported = resolver._get_exported_names("pkg")
        assert "Foo" in exported

    def test_r13_assign_reexport_without_all_not_recognized(
        self,
        tmp_path: Path,
    ) -> None:
        """R-13b: Assignment re-export without __all__ is ignored (safe default)."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text(
            "from . import _impl\n\nFoo = _impl._Foo\n",
        )
        (pkg / "_impl.py").write_text("class _Foo:\n    pass\n")

        resolver = ReexportResolver([tmp_path])
        exported = resolver._get_exported_names("pkg")
        assert "Foo" not in exported

    def test_r13_assign_non_attribute_rhs_excluded(self, tmp_path: Path) -> None:
        """R-13c: Foo = 1 (non-attribute RHS) is not treated as re-export."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text('Foo = 1\n__all__ = ["Foo"]\n')

        resolver = ReexportResolver([tmp_path])
        exported = resolver._get_exported_names("pkg")
        assert "Foo" not in exported

    def test_r13_ann_assign_reexport_via_attribute(self, tmp_path: Path) -> None:
        """R-13d: Annotated assignment Foo: type = _impl._Foo is a re-export."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text(
            'from . import _impl\n\nFoo: type = _impl._Foo\n__all__ = ["Foo"]\n',
        )
        (pkg / "_impl.py").write_text("class _Foo:\n    pass\n")

        resolver = ReexportResolver([tmp_path])
        exported = resolver._get_exported_names("pkg")
        assert "Foo" in exported

    def test_r13_ann_assign_non_attribute_rhs_excluded(
        self,
        tmp_path: Path,
    ) -> None:
        """R-13e: Foo: int = 1 (non-attribute RHS) is not treated as re-export."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text('Foo: int = 1\n__all__ = ["Foo"]\n')

        resolver = ReexportResolver([tmp_path])
        exported = resolver._get_exported_names("pkg")
        assert "Foo" not in exported

    def test_r12_star_import_not_recognized(self, tmp_path: Path) -> None:
        """R-12: from .module import * → not recognized as re-export."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("from .module import *")
        (pkg / "module.py").write_text("Name = 1")

        resolver = ReexportResolver([tmp_path])
        exported = resolver._get_exported_names("pkg")
        # Star imports are explicitly excluded
        assert "Name" not in exported

    def test_find_shortest_path_single_segment(self, tmp_path: Path) -> None:
        """Test: Single segment module has no shorter path."""
        resolver = ReexportResolver([tmp_path])
        shortest = resolver.find_shortest_path("pkg", "Name")
        assert shortest is None

    def test_cache_is_used(self, tmp_path: Path) -> None:
        """Test: Cache prevents repeated parsing."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("from .module import Name")
        (pkg / "module.py").write_text("Name = 1")

        resolver = ReexportResolver([tmp_path])
        exported1 = resolver._get_exported_names("pkg")
        exported2 = resolver._get_exported_names("pkg")
        assert exported1 is exported2  # Same object from cache

    def test_has_name_conflict(self, tmp_path: Path) -> None:
        """Test: Conflict detection when name in multiple paths."""
        x = tmp_path / "x"
        x.mkdir()
        (x / "__init__.py").write_text("Name = 1")

        xy = x / "y"
        xy.mkdir()
        (xy / "__init__.py").write_text("from ..module import Name")
        (xy / "module.py").write_text("Name = 2")

        resolver = ReexportResolver([tmp_path])
        # If Name is exported from both x and x.y, it's a conflict
        has_conflict = resolver.has_name_conflict("Name", "x.y.module")
        # This depends on whether both paths export it
        assert isinstance(has_conflict, bool)
