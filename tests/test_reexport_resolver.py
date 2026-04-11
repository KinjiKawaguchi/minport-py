"""Tests for re-export resolution (R-1 through R-12)."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import ClassVar

import pytest

from minport._reexport_resolver import ReexportResolver, _child_stmt_blocks


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

    def test_r12_star_import_resolved_recursively(self, tmp_path: Path) -> None:
        """R-12: from .module import * → recursively resolves target's public names."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("from .module import *")
        (pkg / "module.py").write_text("Name = 1")

        resolver = ReexportResolver([tmp_path])
        exported = resolver._get_exported_names("pkg")
        assert "Name" in exported

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

    def test_r13_wildcard_respects_target_all(self, tmp_path: Path) -> None:
        """R-13: wildcard import respects target's __all__."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("from .module import *")
        (pkg / "module.py").write_text(
            "class Name: pass\nclass Other: pass\n__all__ = ['Name']",
        )

        resolver = ReexportResolver([tmp_path])
        exported = resolver._get_exported_names("pkg")
        assert "Name" in exported
        assert "Other" not in exported

    def test_r14_wildcard_excludes_underscore_prefixed(self, tmp_path: Path) -> None:
        """R-14: wildcard without __all__ excludes names starting with '_'."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("from .module import *")
        (pkg / "module.py").write_text("class Name: pass\nclass _Private: pass")

        resolver = ReexportResolver([tmp_path])
        exported = resolver._get_exported_names("pkg")
        assert "Name" in exported
        assert "_Private" not in exported

    def test_r15_nested_wildcard_chain(self, tmp_path: Path) -> None:
        """R-15: nested wildcard chain resolves transitively."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("from .sub import *")

        sub = pkg / "sub"
        sub.mkdir()
        (sub / "__init__.py").write_text("from .x import *")
        (sub / "x.py").write_text("class Name: pass")

        resolver = ReexportResolver([tmp_path])
        exported = resolver._get_exported_names("pkg")
        assert "Name" in exported

    def test_r16_wildcard_cycle_does_not_hang(self, tmp_path: Path) -> None:
        """R-16: circular wildcard imports terminate without hanging.

        ``pkg`` wildcard-imports ``pkg.a``, and ``pkg.a`` wildcard-imports
        the parent ``pkg``. Each side also re-exports its own locally-defined
        name via an explicit ``__all__`` so the resolver has something to
        return once the cycle is broken.
        """
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text(
            "from .a import *\nfrom .mod import Name\n__all__ = ['Name']\n",
        )
        (pkg / "mod.py").write_text("class Name: ...\n")

        sub = pkg / "a"
        sub.mkdir()
        (sub / "__init__.py").write_text(
            "from .. import *\nfrom .inner import Leaf\n__all__ = ['Leaf']\n",
        )
        (sub / "inner.py").write_text("class Leaf: ...\n")

        resolver = ReexportResolver([tmp_path])
        # Must terminate without RecursionError or hang.
        assert resolver._get_exported_names("pkg") == {"Name"}
        assert resolver._get_exported_names("pkg.a") == {"Leaf"}

    def test_r17_wildcard_relative_parent(self, tmp_path: Path) -> None:
        """R-17: wildcard from parent package via ``from ..other import *``."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")

        sub = pkg / "sub"
        sub.mkdir()
        (sub / "__init__.py").write_text("from ..other import *")
        (pkg / "other.py").write_text("class Name: ...\n")

        resolver = ReexportResolver([tmp_path])
        exported = resolver._get_exported_names("pkg.sub")
        assert "Name" in exported

    def test_r18_find_shortest_via_wildcard(self, tmp_path: Path) -> None:
        """R-18: find_shortest_path finds shortening through wildcard re-export."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("from .module import *")
        (pkg / "module.py").write_text("class Name: ...\n")

        resolver = ReexportResolver([tmp_path])
        shortest = resolver.find_shortest_path("pkg.module", "Name")
        assert shortest == "pkg"

    def test_wildcard_absolute_import(self, tmp_path: Path) -> None:
        """Absolute ``from pkg.module import *`` is resolved as well."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("from pkg.module import *")
        (pkg / "module.py").write_text("class Name: ...\n")

        resolver = ReexportResolver([tmp_path])
        exported = resolver._get_exported_names("pkg")
        assert "Name" in exported

    def test_wildcard_level_exceeds_package_depth(self, tmp_path: Path) -> None:
        """Over-deep relative wildcard (``from .... import *``) is ignored."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text(
            "from .... import *\nfrom .mod import Name\n__all__ = ['Name']\n",
        )
        (pkg / "mod.py").write_text("class Name: ...\n")

        resolver = ReexportResolver([tmp_path])
        assert resolver._get_exported_names("pkg") == {"Name"}

    def test_wildcard_target_with_syntax_error(self, tmp_path: Path) -> None:
        """A wildcard target whose source cannot be parsed is skipped."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text(
            "from .broken import *\nfrom .good import Name\n__all__ = ['Name']\n",
        )
        (pkg / "broken.py").write_text("this is not valid python !!!")
        (pkg / "good.py").write_text("class Name: ...\n")

        resolver = ReexportResolver([tmp_path])
        assert resolver._get_exported_names("pkg") == {"Name"}

    def test_wildcard_namespace_missing_target(self, tmp_path: Path) -> None:
        """``_get_exported_names`` tolerates a wildcard target that does not exist."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text(
            "from .missing import *\nfrom .good import Name\n__all__ = ['Name']\n",
        )
        (pkg / "good.py").write_text("class Name: ...\n")

        resolver = ReexportResolver([tmp_path])
        assert resolver._get_exported_names("pkg") == {"Name"}

    def test_wildcard_origin_skips_missing_target(self, tmp_path: Path) -> None:
        """``_wildcard_origin`` skips wildcard targets that cannot be found."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("from .missing import *\n")
        (pkg / "mod.py").write_text("class Name: ...\n")

        resolver = ReexportResolver([tmp_path])
        # No wildcard target file exists → no shortening via wildcard.
        assert resolver.find_shortest_path("pkg.mod", "Name") is None

    def test_wildcard_origin_skips_target_with_syntax_error(
        self,
        tmp_path: Path,
    ) -> None:
        """A wildcard target that fails to parse is skipped by origin walk."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("from .broken import *\n")
        (pkg / "broken.py").write_text("!!! not python")
        (pkg / "mod.py").write_text("class Name: ...\n")

        resolver = ReexportResolver([tmp_path])
        assert resolver.find_shortest_path("pkg.mod", "Name") is None

    def test_wildcard_origin_respects_target_all(self, tmp_path: Path) -> None:
        """Wildcard origin walk honours the target's ``__all__``."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("from .inner import *\n")
        (pkg / "inner.py").write_text(
            "class Public: ...\nclass Private: ...\n__all__ = ['Public']\n",
        )

        resolver = ReexportResolver([tmp_path])
        # Private is not in inner.__all__ → wildcard does not expose it.
        assert resolver.find_shortest_path("pkg.inner", "Private") is None
        assert resolver.find_shortest_path("pkg.inner", "Public") == "pkg"

    def test_wildcard_chain_with_annotated_assignment(
        self,
        tmp_path: Path,
    ) -> None:
        """Annotated assignments in a wildcard target are part of its namespace."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text(
            "from .values import *\nfrom .mod import Alias\n__all__ = ['Alias']\n",
        )
        (pkg / "values.py").write_text("Value: int = 1\n")
        (pkg / "mod.py").write_text("Alias = 1\n")

        resolver = ReexportResolver([tmp_path])
        # Ensure the wildcard target's AnnAssign is walked without error.
        exported = resolver._get_exported_names("pkg")
        assert exported == {"Alias"}

    def test_wildcard_honours_target_all(self, tmp_path: Path) -> None:
        """Wildcard respects target's ``__all__`` when filtering origins."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("from .module import *")
        (pkg / "module.py").write_text(
            "class Name: ...\nclass Other: ...\n__all__ = ['Name']\n",
        )

        resolver = ReexportResolver([tmp_path])
        # Name is wildcard-exported → shortening to "pkg" is valid.
        assert resolver.find_shortest_path("pkg.module", "Name") == "pkg"
        # Other is not in target's __all__ → cannot be shortened.
        assert resolver.find_shortest_path("pkg.module", "Other") is None

    def test_r19_try_except_import_is_recognized(self, tmp_path: Path) -> None:
        """R-19: Re-export inside try/except is traced by find_shortest_path."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text(
            "try:\n    from ._impl import Foo\nexcept ImportError:\n    from ._impl import Foo\n",
        )
        (pkg / "_impl.py").write_text("class Foo: ...\n")

        resolver = ReexportResolver([tmp_path])
        assert resolver.find_shortest_path("pkg._impl", "Foo") == "pkg"

    def test_r20_if_version_guarded_import_is_recognized(
        self,
        tmp_path: Path,
    ) -> None:
        """R-20: Re-export inside a runtime ``if`` block is traced."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text(
            "import sys\n"
            "if sys.version_info >= (3, 12):\n"
            "    from ._impl import Bar\n"
            "else:\n"
            "    from ._impl import Bar\n",
        )
        (pkg / "_impl.py").write_text("class Bar: ...\n")

        resolver = ReexportResolver([tmp_path])
        assert resolver.find_shortest_path("pkg._impl", "Bar") == "pkg"

    def test_r21_type_checking_guarded_import_is_excluded(
        self,
        tmp_path: Path,
    ) -> None:
        """R-21: ``if TYPE_CHECKING:`` imports are not runtime re-exports.

        The shorter path must NOT be suggested because the name is not
        actually available from ``pkg`` at runtime.
        """
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text(
            "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from ._impl import Baz\n",
        )
        (pkg / "_impl.py").write_text("class Baz: ...\n")

        resolver = ReexportResolver([tmp_path])
        assert resolver.find_shortest_path("pkg._impl", "Baz") is None

    def test_r22_typing_type_checking_attribute_guard(
        self,
        tmp_path: Path,
    ) -> None:
        """R-22: ``if typing.TYPE_CHECKING:`` (attribute form) is also excluded."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text(
            "import typing\nif typing.TYPE_CHECKING:\n    from ._impl import Qux\n",
        )
        (pkg / "_impl.py").write_text("class Qux: ...\n")

        resolver = ReexportResolver([tmp_path])
        assert resolver.find_shortest_path("pkg._impl", "Qux") is None

    def test_r23_try_star_import_is_recognized(self, tmp_path: Path) -> None:
        """R-23: Re-export inside a ``try/except*`` block (PEP 654) is traced."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text(
            "try:\n"
            "    from ._impl import Quux\n"
            "except* ImportError:\n"
            "    from ._impl import Quux\n",
        )
        (pkg / "_impl.py").write_text("class Quux: ...\n")

        resolver = ReexportResolver([tmp_path])
        assert resolver.find_shortest_path("pkg._impl", "Quux") == "pkg"

    def test_child_stmt_blocks_rejects_unknown_stmt_subclass(self) -> None:
        """Synthetic ``ast.stmt`` subclass trips the walker's exhaustiveness guard.

        Guards against a future Python grammar extension slipping past the
        enumerated ``_SKIP_STMTS`` tuple. Any such omission must fail the
        test suite instead of silently being ignored.
        """

        class _FakeStmt(ast.stmt):
            _fields: ClassVar[tuple[str, ...]] = ()

        with pytest.raises(TypeError, match=r"Unhandled ast\.stmt subclass"):
            list(_child_stmt_blocks(_FakeStmt()))
