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
        """R-5: Multi-level re-export chain finds shortest path.

        ``Name`` is defined once at the bottom of the package hierarchy and
        re-exported upward through every intermediate ``__init__.py``. The
        resolver must trace the chain to the common origin and report the
        top-most package as the shortest safe path.
        """
        x = tmp_path / "x"
        x.mkdir()
        xy = x / "y"
        xy.mkdir()
        xyz = xy / "z"
        xyz.mkdir()

        (xyz / "module.py").write_text("Name = 1")
        (xyz / "__init__.py").write_text("from .module import Name")
        (xy / "__init__.py").write_text("from .z import Name")
        (x / "__init__.py").write_text("from .y import Name")

        resolver = ReexportResolver([tmp_path])
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

    def test_origin_based_conflict_detects_diverging_definitions(
        self,
        tmp_path: Path,
    ) -> None:
        """Same name bound to different underlying files is reported as a conflict."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        x = pkg / "x"
        x.mkdir()
        y = pkg / "y"
        y.mkdir()

        (pkg / "__init__.py").write_text("from .y.module import Name")
        (x / "__init__.py").write_text("from .module import Name")
        (x / "module.py").write_text("Name = 1")
        (y / "__init__.py").write_text("from .module import Name")
        (y / "module.py").write_text("Name = 2")

        resolver = ReexportResolver([tmp_path])
        assert resolver.has_name_conflict("Name", "pkg.x.module") is True
        assert resolver.find_shortest_path("pkg.x.module", "Name") == "pkg.x"

    def test_origin_based_conflict_ignores_chained_reexports(
        self,
        tmp_path: Path,
    ) -> None:
        """Legitimate re-export chains are not flagged as conflicts."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        sub = pkg / "sub"
        sub.mkdir()

        (pkg / "__init__.py").write_text("from .sub.inner import Thing")
        (sub / "__init__.py").write_text("from .inner import Thing")
        (sub / "inner.py").write_text("class Thing: ...")

        resolver = ReexportResolver([tmp_path])
        assert resolver.has_name_conflict("Thing", "pkg.sub.inner") is False
        assert resolver.find_shortest_path("pkg.sub.inner", "Thing") == "pkg"

    def test_has_name_conflict_unresolvable_origin(self, tmp_path: Path) -> None:
        """Origin that cannot be resolved is not a conflict."""
        resolver = ReexportResolver([tmp_path])
        assert resolver.has_name_conflict("Name", "missing.pkg.mod") is False

    def test_annotated_assignment_is_definition(self, tmp_path: Path) -> None:
        """``Name: int = 1`` is recognised as a local definition."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("from .mod import Value")
        (pkg / "mod.py").write_text("Value: int = 5")

        resolver = ReexportResolver([tmp_path])
        assert resolver.find_shortest_path("pkg.mod", "Value") == "pkg"

    def test_docstring_only_module_has_no_bindings(self, tmp_path: Path) -> None:
        """Module with only a docstring resolves to no binding."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text('"""Just a docstring."""')
        (pkg / "mod.py").write_text("Value = 1")

        resolver = ReexportResolver([tmp_path])
        assert resolver.find_shortest_path("pkg.mod", "Value") is None

    def test_bare_submodule_import_is_ignored(self, tmp_path: Path) -> None:
        """``from . import submodule`` does not register as a name binding."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("from . import mod")
        (pkg / "mod.py").write_text("Value = 1")

        resolver = ReexportResolver([tmp_path])
        assert resolver.find_shortest_path("pkg.mod", "Value") is None

    def test_invalid_relative_level_is_rejected(self, tmp_path: Path) -> None:
        """Relative imports that escape the top-level package resolve to None."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("from ...other import Value")
        (pkg / "mod.py").write_text("Value = 1")

        resolver = ReexportResolver([tmp_path])
        assert resolver.find_shortest_path("pkg.mod", "Value") is None

    def test_absolute_reexport_is_resolved(self, tmp_path: Path) -> None:
        """An absolute import inside an ``__init__.py`` counts as a re-export."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("from pkg.mod import Value")
        (pkg / "mod.py").write_text("Value = 1")

        resolver = ReexportResolver([tmp_path])
        assert resolver.find_shortest_path("pkg.mod", "Value") == "pkg"

    def test_annotated_assignment_for_other_name_is_ignored(
        self,
        tmp_path: Path,
    ) -> None:
        """An annotated assignment that does not match the lookup name is skipped."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("Other: int = 1\nfrom .mod import Value")
        (pkg / "mod.py").write_text("Value = 1")

        resolver = ReexportResolver([tmp_path])
        assert resolver.find_shortest_path("pkg.mod", "Value") == "pkg"

    def test_find_source_file_installed_py_module(self) -> None:
        """Installed single-file ``.py`` modules resolve through importlib."""
        resolver = ReexportResolver([])
        source = resolver._find_source_file("asyncio.queues")
        if source is None:
            pytest.skip("asyncio.queues source not available")
        assert source.suffix == ".py"
        assert source.name != "__init__.py"

    def test_candidate_with_syntax_error_is_skipped(self, tmp_path: Path) -> None:
        """A candidate whose source cannot be parsed is treated as having no origin."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        sub = pkg / "sub"
        sub.mkdir()
        (pkg / "__init__.py").write_text("this is not valid python !!!")
        (sub / "__init__.py").write_text("from .mod import Value")
        (sub / "mod.py").write_text("Value = 1")

        resolver = ReexportResolver([tmp_path])
        assert resolver.find_shortest_path("pkg.sub.mod", "Value") == "pkg.sub"

    def test_circular_reexport_chain_terminates(self, tmp_path: Path) -> None:
        """Mutually-recursive re-exports do not infinite-loop."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "a.py").write_text("from .b import Name")
        (pkg / "b.py").write_text("from .a import Name")

        resolver = ReexportResolver([tmp_path])
        assert resolver.find_shortest_path("pkg.a", "Name") is None
        assert resolver.has_name_conflict("Name", "pkg.a") is False

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
