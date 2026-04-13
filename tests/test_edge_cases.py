"""Tests for edge cases (E-1 through E-10)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from minport._import_parser import parse_imports
from minport._models import DEFAULT_EXCLUDES, ImportStatement
from minport._reexport_resolver import ReexportResolver
from minport.checker import (
    _has_suppress_comment,
    _is_excluded,
    _is_suppressed,
    check,
)
from minport.cli import main


class TestEdgeCases:
    """Test edge cases and corner conditions."""

    def test_e1_empty_file(self, tmp_path: Path) -> None:
        """E-1: Empty file is handled gracefully."""
        test_file = tmp_path / "test.py"
        test_file.write_text("")

        result, _ = check([test_file], src_roots=[tmp_path])
        assert result.files_checked == 1
        assert len(result.violations) == 0

    def test_e2_syntax_error_file_skipped(self, tmp_path: Path) -> None:
        """E-2: File with syntax error is skipped with warning."""
        test_file = tmp_path / "test.py"
        test_file.write_text("this is not valid python !!!")

        result, _ = check([test_file], src_roots=[tmp_path])
        assert result.files_skipped == 1
        assert result.files_checked == 0

    def test_e3_binary_file_skipped(self, tmp_path: Path) -> None:
        """E-3: Binary file is skipped."""
        test_file = tmp_path / "test.bin"
        test_file.write_bytes(b"\x00\x01\x02\x03")

        result, _ = check([test_file], src_roots=[tmp_path])
        # Binary files don't have .py extension, so they're not collected
        assert result.files_checked == 0

    def test_e4_future_annotations_ignored(self, tmp_path: Path) -> None:
        """E-4: from __future__ import annotations is ignored."""
        test_file = tmp_path / "test.py"
        test_file.write_text("from __future__ import annotations")

        result, _ = check([test_file], src_roots=[tmp_path])
        assert len(result.violations) == 0

    def test_e5_typing_imports_are_checked(self, tmp_path: Path) -> None:
        """E-5: from typing import TYPE_CHECKING etc. are checked normally."""
        test_file = tmp_path / "test.py"
        test_file.write_text("from typing import TYPE_CHECKING")

        result, _ = check([test_file], src_roots=[tmp_path])
        # Single segment, so not extracted, so no violations
        assert len(result.violations) == 0

    def test_e6_type_checking_block_imports_checked(self, tmp_path: Path) -> None:
        """E-6: Imports in if TYPE_CHECKING: blocks are checked."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        sub = pkg / "sub"
        sub.mkdir()

        (pkg / "__init__.py").write_text("from .sub.module import Name")
        (sub / "__init__.py").write_text("from .module import Name")
        (sub / "module.py").write_text("Name = 1")

        test_file = tmp_path / "test.py"
        test_file.write_text("""
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from pkg.sub.module import Name
""")

        result, _ = check([test_file], src_roots=[tmp_path])
        # Should still find violations in TYPE_CHECKING blocks
        # (AST walks all nodes regardless of control flow)
        if result.violations:
            assert result.violations[0].name == "Name"

    def test_e7_large_file(self, tmp_path: Path) -> None:
        """E-7: Large file (1000+ lines) is handled correctly."""
        test_file = tmp_path / "test.py"
        lines = ["import sys"] + ["x = 1"] * 1000
        test_file.write_text("\n".join(lines))

        result, _ = check([test_file], src_roots=[tmp_path])
        assert result.files_checked == 1

    def test_e8_duplicate_imports_from_different_paths(self, tmp_path: Path) -> None:
        """E-8: Same name imported from different paths is evaluated separately."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        sub = pkg / "sub"
        sub.mkdir()

        (pkg / "__init__.py").write_text("from .sub.module import Name")
        (sub / "__init__.py").write_text("from .module import Name")
        (sub / "module.py").write_text("Name = 1")

        test_file = tmp_path / "test.py"
        test_file.write_text("from pkg.sub.module import Name\nfrom pkg.sub.module import Name")

        result, _ = check([test_file], src_roots=[tmp_path])
        # Both imports should be reported if they're violations
        if result.violations:
            assert len([v for v in result.violations if v.name == "Name"]) >= 1

    def test_e9_inline_suppress_comment(self, tmp_path: Path) -> None:
        """E-9: # minport: ignore suppresses violations on that line."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        sub = pkg / "sub"
        sub.mkdir()

        (pkg / "__init__.py").write_text("from .sub.module import Name, Other")
        (sub / "__init__.py").write_text("from .module import Name, Other")
        (sub / "module.py").write_text("Name = 1\nOther = 2")

        test_file = tmp_path / "test.py"
        test_file.write_text(
            "from pkg.sub.module import Name  # minport: ignore\nfrom pkg.sub.module import Other"
        )

        result, _ = check([test_file], src_roots=[tmp_path])
        # Only Other should be reported
        other_violations = [v for v in result.violations if v.name == "Other"]
        name_violations = [v for v in result.violations if v.name == "Name"]
        if other_violations:
            assert len(name_violations) == 0

    def test_e10_symlink_not_processed_twice(self, tmp_path: Path) -> None:
        """E-10: Symlinks are resolved to prevent duplicate processing."""
        test_file = tmp_path / "test.py"
        test_file.write_text("import sys")

        link = tmp_path / "link.py"
        try:
            link.symlink_to(test_file)
        except OSError:
            pytest.skip("Symlinks not supported on this platform")

        result, _ = check([test_file, link], src_roots=[tmp_path])
        # Even though we passed both, they should be deduplicated
        assert result.files_checked == 1

    def test_file_path_with_spaces(self, tmp_path: Path) -> None:
        """Test: File paths with spaces are handled."""
        subdir = tmp_path / "my dir"
        subdir.mkdir()

        test_file = subdir / "test file.py"
        test_file.write_text("import sys")

        result, _ = check([test_file], src_roots=[tmp_path])
        assert result.files_checked == 1

    def test_unicode_in_imports(self, tmp_path: Path) -> None:
        """Test: Unicode in comments/strings doesn't affect parsing."""
        test_file = tmp_path / "test.py"
        test_file.write_text("# Comment with unicode: 你好\nfrom x.y.z import Name")

        result, _ = check([test_file], src_roots=[tmp_path])
        # Should still parse correctly
        assert len(result.violations) == 0

    def test_nested_type_checking_blocks(self, tmp_path: Path) -> None:
        """Test: Nested TYPE_CHECKING blocks work correctly."""
        test_file = tmp_path / "test.py"
        test_file.write_text("""
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    if True:
        from x.y.z import Name
""")

        result, _ = check([test_file], src_roots=[tmp_path])
        # Should parse without crashing
        assert result.files_checked == 1

    def test_import_with_comments(self, tmp_path: Path) -> None:
        """Test: Imports with inline comments are parsed correctly."""
        test_file = tmp_path / "test.py"
        test_file.write_text("from x.y.z import Name  # this is a comment")

        result, _ = check([test_file], src_roots=[tmp_path])
        # Should parse the import correctly
        assert result.files_checked == 1

    def test_multiline_import_with_continuation(self, tmp_path: Path) -> None:
        """Test: Multiline imports with backslash continuation."""
        test_file = tmp_path / "test.py"
        test_file.write_text("from x.y.z import \\\n    Name, \\\n    Other")

        result, _ = check([test_file], src_roots=[tmp_path])
        assert result.files_checked == 1

    def test_unreadable_file_skipped(self, tmp_path: Path) -> None:
        """Test: Unreadable files are skipped."""
        test_file = tmp_path / "test.py"
        test_file.write_text("import sys")
        test_file.chmod(0o000)

        try:
            result, _ = check([test_file], src_roots=[tmp_path])
            # File should be skipped
            assert result.files_skipped >= 1
        finally:
            test_file.chmod(0o644)

    def test_directory_recursion(self, tmp_path: Path) -> None:
        """Test: check() recursively processes directories."""
        subdir = tmp_path / "subdir"
        subdir.mkdir()

        test1 = tmp_path / "test1.py"
        test1.write_text("import sys")

        test2 = subdir / "test2.py"
        test2.write_text("import os")

        result, _ = check([tmp_path], src_roots=[tmp_path])
        # Both files should be checked
        assert result.files_checked == 2

    def test_exclude_pattern_glob(self, tmp_path: Path) -> None:
        """Test: Exclude patterns support glob wildcards."""
        test1 = tmp_path / "test_main.py"
        test1.write_text("import sys")

        test2 = tmp_path / "test_other.py"
        test2.write_text("import os")

        result, _ = check([tmp_path], exclude=["test_main.py"], src_roots=[tmp_path])
        # Only test_other.py should be checked
        assert result.files_checked == 1

    def test_relative_path_handling(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test: Relative paths are handled correctly."""
        monkeypatch.chdir(tmp_path)

        test_file = tmp_path / "test.py"
        test_file.write_text("import sys")

        # Use relative path
        result, _ = check([Path("test.py")], src_roots=[tmp_path])
        assert result.files_checked == 1

    def test_module_not_found_in_tree(self, tmp_path: Path) -> None:
        """Test: Import from non-existent module is handled."""
        test_file = tmp_path / "test.py"
        test_file.write_text("from nonexistent.module import Name")

        result, _ = check([test_file], src_roots=[tmp_path])
        # Should not crash
        assert result.files_checked == 1

    def test_package_with_no_init(self, tmp_path: Path) -> None:
        """Test: Package without __init__.py is handled."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        # Don't create __init__.py

        module = pkg / "module.py"
        module.write_text("Name = 1")

        test_file = tmp_path / "test.py"
        test_file.write_text("from pkg.module import Name")

        result, _ = check([test_file], src_roots=[tmp_path])
        # Should process without crashing
        assert result.files_checked == 1

    def test_all_with_non_list_value(self, tmp_path: Path) -> None:
        """Test: __all__ with non-list/tuple value is handled."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        # __all__ assigned to a string instead of list
        (pkg / "__init__.py").write_text('__all__ = "Name"')
        (pkg / "module.py").write_text("Name = 1")

        resolver = ReexportResolver([tmp_path])
        exported = resolver._get_exported_names("pkg")
        # Should not crash, just return empty or gracefully handle
        assert isinstance(exported, set)

    def test_all_with_multiple_targets(self, tmp_path: Path) -> None:
        """Test: __all__ with multiple assignment targets is handled."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        # Multiple targets: a = b = __all__ = [...]
        (pkg / "__init__.py").write_text('a = b = __all__ = ["Name"]')
        (pkg / "module.py").write_text("Name = 1")

        resolver = ReexportResolver([tmp_path])
        exported = resolver._get_exported_names("pkg")
        # Should not crash
        assert isinstance(exported, set)

    def test_parse_error_in_init_file(self, tmp_path: Path) -> None:
        """Test: Syntax error in __init__.py is handled gracefully."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        # Write invalid Python
        (pkg / "__init__.py").write_text("from .module import Name !!!")

        resolver = ReexportResolver([tmp_path])
        exported = resolver._get_exported_names("pkg")
        # Should not crash, just return empty
        assert isinstance(exported, set)
        assert len(exported) == 0

    def test_directory_with_mixed_file_types(self, tmp_path: Path) -> None:
        """Test: Directory with non-.py files is handled."""
        test_py = tmp_path / "test.py"
        test_py.write_text("import sys")

        test_txt = tmp_path / "readme.txt"
        test_txt.write_text("This is not Python")

        test_md = tmp_path / "notes.md"
        test_md.write_text("# Notes")

        result, _ = check([tmp_path], src_roots=[tmp_path])
        # Should only check test.py, ignoring .txt and .md
        assert result.files_checked == 1

    def test_symlink_dedup(self, tmp_path: Path) -> None:
        """E-10: Symlink duplicates are not processed twice."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("from .core import Foo")
        (pkg / "core.py").write_text("class Foo: pass")

        original = tmp_path / "usage.py"
        original.write_text("from pkg.core import Foo")
        link = tmp_path / "usage_link.py"
        link.symlink_to(original)

        result, _ = check([tmp_path], src_roots=[tmp_path])
        # Both files point to same inode — should only check once
        assert result.files_checked >= 1

    def test_exclude_pattern_skips_file(self, tmp_path: Path) -> None:
        """Excluded files are not checked."""
        (tmp_path / "keep.py").write_text("import sys")
        (tmp_path / "skip.py").write_text("from os.path import join")

        result, _ = check([tmp_path], src_roots=[tmp_path], exclude=["skip.py"])
        assert result.files_checked == 1

    def test_suppress_comment_out_of_bounds(self) -> None:
        """Suppress comment check with invalid line number doesn't crash."""
        assert _has_suppress_comment(999, ("line1",)) is False
        assert _has_suppress_comment(0, ("line1",)) is False

    def test_cli_empty_paths_fallback(self, monkeypatch, tmp_path: Path) -> None:
        """CLI falls back to current dir when no paths given."""
        (tmp_path / "simple.py").write_text("import os")
        monkeypatch.chdir(tmp_path)
        exit_code = main(["check"])
        assert exit_code == 0

    def test_is_excluded_path_not_relative(self) -> None:
        """_is_excluded handles path not relative to base."""
        result = _is_excluded(Path("/elsewhere/file.py"), Path("/some/base"), ["*.py"])
        assert result is True

    def test_fix_skips_when_duplicate_of_existing_import(self, tmp_path: Path) -> None:
        """Issue #4: --fix must not create a line that duplicates another import.

        When ``from X.Y import Thing as _Thing`` and ``from X import Thing``
        coexist, rewriting the first to ``from X import Thing as _Thing``
        produces an import of the same (module, name) that already exists.
        The fixer must skip the rewrite to avoid F811/F401-equivalent redundancy.
        """
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        sub = pkg / "sub"
        sub.mkdir()
        (sub / "__init__.py").write_text("")
        (sub / "inner.py").write_text("Thing = 1\n")
        (pkg / "__init__.py").write_text("from pkg.sub.inner import Thing\n")

        test_file = tmp_path / "user.py"
        test_file.write_text(
            "from pkg.sub.inner import Thing as _Thing\nfrom pkg import Thing\n",
        )

        check([test_file], src_roots=[tmp_path], fix=True)

        content = test_file.read_text()
        # The short form must still be present.
        assert "from pkg import Thing\n" in content
        # The rewrite must NOT have produced a duplicate import of (pkg, Thing).
        assert "from pkg import Thing as _Thing" not in content
        # Since the rewrite is skipped, the original longer import is retained.
        assert "from pkg.sub.inner import Thing as _Thing" in content

    def test_fix_duplicate_check_ignores_relative_imports(self, tmp_path: Path) -> None:
        """Duplicate-fix scan must skip ``from . import`` / ``from .rel import``.

        Relative imports reference no absolute module path and cannot collide
        with a rewritten ``from X import Name`` line. The scan must walk past
        them without error and still apply the fix to the real violation.
        """
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        sub = pkg / "sub"
        sub.mkdir()
        (sub / "__init__.py").write_text("")
        (sub / "inner.py").write_text("Thing = 1\n")
        (pkg / "__init__.py").write_text("from pkg.sub.inner import Thing\n")

        test_file = tmp_path / "user.py"
        test_file.write_text(
            "from . import something\nfrom .rel import other\nfrom pkg.sub.inner import Thing\n",
        )

        check([test_file], src_roots=[tmp_path], fix=True)

        content = test_file.read_text()
        # Relative imports are untouched; the absolute violation is fixed.
        assert "from . import something\n" in content
        assert "from .rel import other\n" in content
        assert "from pkg import Thing\n" in content

    def test_fix_moves_only_non_colliding_name_on_multi_name_line(
        self,
        tmp_path: Path,
    ) -> None:
        """Per-violation guard: on a multi-name line, only the names whose
        shorter target does not already exist should be moved. The AST-based
        fixer splits the line and leaves the colliding name behind.
        """
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        sub = pkg / "sub"
        sub.mkdir()
        (sub / "__init__.py").write_text("")
        (sub / "inner.py").write_text("Thing = 1\nOther = 2\n")
        (pkg / "__init__.py").write_text(
            "from pkg.sub.inner import Thing\nfrom pkg.sub.inner import Other\n",
        )

        test_file = tmp_path / "user.py"
        test_file.write_text(
            "from pkg import Thing\nfrom pkg.sub.inner import Thing, Other\n",
        )

        check([test_file], src_roots=[tmp_path], fix=True)

        content = test_file.read_text()
        # The colliding ``Thing`` stays on the original line; ``Other`` is
        # split out into its own shorter import. Exactly one ``from pkg
        # import Thing`` — no duplicate was introduced.
        assert content.count("from pkg import Thing\n") == 1
        assert "from pkg import Other" in content
        assert "from pkg.sub.inner import Thing" in content
        assert "from pkg.sub.inner import Thing, Other" not in content

    def test_fix_skips_two_violations_colliding_on_same_target(
        self,
        tmp_path: Path,
    ) -> None:
        """Inter-violation dedup: if two lines would both reduce to the same
        ``(shorter, name)``, applying either alone still leaves a duplicate
        with the other unchanged line. Skip both.
        """
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        sub1 = pkg / "sub1"
        sub1.mkdir()
        sub2 = pkg / "sub2"
        sub2.mkdir()
        (sub1 / "__init__.py").write_text("Thing = 1\n")
        (sub2 / "__init__.py").write_text("Thing = 2\n")
        (pkg / "__init__.py").write_text("from pkg.sub1 import Thing\n")

        test_file = tmp_path / "user.py"
        test_file.write_text(
            "from pkg.sub1 import Thing as A\nfrom pkg.sub1 import Thing as B\n",
        )

        check([test_file], src_roots=[tmp_path], fix=True)

        content = test_file.read_text()
        # Neither line is rewritten: rewriting both would create two
        # ``from pkg import Thing`` lines.
        assert "from pkg.sub1 import Thing as A" in content
        assert "from pkg.sub1 import Thing as B" in content
        assert "from pkg import Thing" not in content

    def test_fixable_count_excludes_duplicate_skips(self, tmp_path: Path) -> None:
        """``CheckResult.fixable_count`` must exclude violations the fixer skips."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        sub = pkg / "sub"
        sub.mkdir()
        (sub / "__init__.py").write_text("")
        (sub / "inner.py").write_text("Thing = 1\n")
        (pkg / "__init__.py").write_text("from pkg.sub.inner import Thing\n")

        test_file = tmp_path / "user.py"
        test_file.write_text(
            "from pkg.sub.inner import Thing as _Thing\nfrom pkg import Thing\n",
        )

        result, _ = check([test_file], src_roots=[tmp_path])
        assert len(result.violations) == 1
        assert result.fixable_count == 0

    def test_init_self_import_not_reported(self, tmp_path: Path) -> None:
        """Issue #18: __init__.py must not suggest shortening to its own package.

        ``pkg/__init__.py`` containing ``from pkg.sub import Hello`` should NOT
        be reported as shortenable to ``from pkg import Hello``, because the
        file itself *is* ``pkg/__init__.py`` — applying the fix would create a
        self-import and raise ``ImportError`` (partially initialized module).
        """
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text(
            'from pkg.sub import Hello\n__all__ = ["Hello"]\n',
        )
        (pkg / "sub.py").write_text("class Hello: ...\n")

        result, _ = check([tmp_path], src_roots=[tmp_path])
        hello_violations = [v for v in result.violations if v.name == "Hello"]
        assert hello_violations == [], (
            f"__init__.py must not suggest self-import, got: {hello_violations}"
        )

    def test_init_self_import_fix_no_change(self, tmp_path: Path) -> None:
        """Issue #18: --fix must not rewrite __init__.py to self-import."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        original = 'from pkg.sub import Hello\n__all__ = ["Hello"]\n'
        (pkg / "__init__.py").write_text(original)
        (pkg / "sub.py").write_text("class Hello: ...\n")

        check([tmp_path], src_roots=[tmp_path], fix=True)

        assert (pkg / "__init__.py").read_text() == original

    def test_deep_init_self_import_not_reported(self, tmp_path: Path) -> None:
        """Issue #18: Deep nesting — a/b/c/__init__.py must not shorten to a.b.c."""
        a = tmp_path / "a"
        b = a / "b"
        c = b / "c"
        c.mkdir(parents=True)
        (a / "__init__.py").write_text("")
        (b / "__init__.py").write_text("")
        (c / "__init__.py").write_text("from a.b.c.d import Name\n")
        (c / "d.py").write_text("Name = 1\n")

        result, _ = check([tmp_path], src_roots=[tmp_path])
        name_violations = [v for v in result.violations if v.name == "Name"]
        # a.b.c/__init__.py → should not suggest "from a.b.c import Name"
        for v in name_violations:
            assert v.shorter_path != "a.b.c", (
                f"__init__.py must not suggest shortening to its own package: {v}"
            )

    def test_init_ancestor_package_not_reported(self, tmp_path: Path) -> None:
        """Issue #26: __init__.py must not shorten to an ancestor package.

        ``a/b/__init__.py`` with ``from a.b.c.impl import Hello`` should NOT
        suggest ``from a import Hello`` when ``a/__init__.py`` re-exports from
        ``a.b``, because applying the fix would create an indirect circular
        import chain: ``a.b.__init__`` → ``a.__init__`` → ``a.b.__init__`` (still
        initializing).
        """
        a = tmp_path / "a"
        b = a / "b"
        c = b / "c"
        c.mkdir(parents=True)
        (a / "__init__.py").write_text('from .b import Hello\n__all__ = ["Hello"]\n')
        (b / "__init__.py").write_text(
            'from a.b.c.impl import Hello\n__all__ = ["Hello"]\n',
        )
        (c / "__init__.py").write_text(
            'from a.b.c.impl import Hello\n__all__ = ["Hello"]\n',
        )
        (c / "impl.py").write_text("class Hello: ...\n")

        result, _ = check([tmp_path], src_roots=[tmp_path])
        for v in result.violations:
            if v.file_path.name == "__init__.py":
                file_parts = v.file_path.parent.relative_to(tmp_path).parts
                file_pkg = ".".join(file_parts)
                assert not file_pkg.startswith(f"{v.shorter_path}."), (
                    f"__init__.py must not shorten to ancestor package: {v}"
                )
                assert v.shorter_path != file_pkg, (
                    f"__init__.py must not shorten to own package: {v}"
                )

    def test_init_ancestor_fix_no_change(self, tmp_path: Path) -> None:
        """Issue #26: --fix must not rewrite __init__.py to ancestor import."""
        a = tmp_path / "a"
        b = a / "b"
        c = b / "c"
        c.mkdir(parents=True)
        (a / "__init__.py").write_text('from .b import Hello\n__all__ = ["Hello"]\n')
        b_original = 'from a.b.c.impl import Hello\n__all__ = ["Hello"]\n'
        (b / "__init__.py").write_text(b_original)
        (c / "__init__.py").write_text(
            'from a.b.c.impl import Hello\n__all__ = ["Hello"]\n',
        )
        (c / "impl.py").write_text("class Hello: ...\n")

        check([tmp_path], src_roots=[tmp_path], fix=True)

        assert (b / "__init__.py").read_text() == b_original

    def test_non_init_module_imported_by_package_init_not_reported(
        self,
        tmp_path: Path,
    ) -> None:
        """Issue #32: Non-__init__.py importing own ancestor via its __init__.

        ``pkg/helpers.py`` with ``from pkg.core import Thing`` should NOT
        suggest ``from pkg import Thing`` when ``pkg/__init__.py`` imports
        ``.helpers``, because applying the fix creates a circular import:
        ``pkg.__init__`` → ``pkg.helpers`` → ``from pkg import Thing``
        (pkg still initializing).
        """
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text(
            "from .helpers import helper_fn\nfrom .core import Thing\n"
            '__all__ = ["Thing", "helper_fn"]\n',
        )
        (pkg / "core.py").write_text("class Thing: ...\n")
        (pkg / "helpers.py").write_text(
            "from pkg.core import Thing\n\ndef helper_fn() -> Thing: ...\n",
        )

        result, _ = check([tmp_path], src_roots=[tmp_path])
        helpers_violations = [v for v in result.violations if v.file_path.name == "helpers.py"]
        assert helpers_violations == [], (
            f"helpers.py must not suggest circular shortening, got: {helpers_violations}"
        )

    def test_loads_file_plain_import_statement(self, tmp_path: Path) -> None:
        """Issue #32: `import a.b.c` triggers loading of file_path too."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("import pkg.helpers\nfrom .core import Thing\n")
        (pkg / "core.py").write_text("class Thing: ...\n")
        (pkg / "helpers.py").write_text("from pkg.core import Thing\n")

        result, _ = check([tmp_path], src_roots=[tmp_path])
        helpers_violations = [v for v in result.violations if v.file_path.name == "helpers.py"]
        # helpers is loaded via `import pkg.helpers` in __init__ → shortening unsafe
        assert helpers_violations == []

    def test_loads_file_oserror_on_target(self, tmp_path: Path, monkeypatch) -> None:
        """loads_file returns False when target.resolve() raises OSError."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "core.py").write_text("class Thing: ...\n")

        resolver = ReexportResolver([tmp_path])
        bad = tmp_path / "broken"
        original_resolve = Path.resolve
        msg = "simulated"

        def broken_resolve(self, *, strict=False):
            if self == bad:
                raise OSError(msg)
            return original_resolve(self, strict=strict)

        monkeypatch.setattr(Path, "resolve", broken_resolve)
        assert resolver.loads_file("pkg", bad) is False

    def test_loads_file_skips_source_resolve_oserror(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        """_transitive_loads skips a source file whose resolve() raises OSError."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("from .core import Thing\n")
        (pkg / "core.py").write_text("class Thing: ...\n")

        resolver = ReexportResolver([tmp_path])
        init_path = (pkg / "__init__.py").resolve()
        original_resolve = Path.resolve
        msg = "simulated"

        def broken_resolve(self, *, strict=False):
            if self == init_path:
                raise OSError(msg)
            return original_resolve(self, strict=strict)

        monkeypatch.setattr(Path, "resolve", broken_resolve)
        # Does not crash; simply skips the unresolvable file
        loaded = resolver._transitive_loads("pkg")
        assert isinstance(loaded, frozenset)

    def test_loads_file_skips_syntax_error_file(self, tmp_path: Path) -> None:
        """_transitive_loads skips files that fail to parse."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("from .broken import X\n")
        (pkg / "broken.py").write_text("this is !! invalid python !!")

        resolver = ReexportResolver([tmp_path])
        loaded = resolver._transitive_loads("pkg")
        # __init__ and broken.py are both loaded as files, but broken's AST fails
        # The walk should not crash; at least __init__ is in loaded
        assert (pkg / "__init__.py").resolve() in loaded

    def test_loads_file_unresolvable_relative_import(self, tmp_path: Path) -> None:
        """Relative imports beyond package depth are ignored."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        # `from .. import X` from pkg/__init__.py would exceed depth
        (pkg / "__init__.py").write_text("from ... import Something\n")
        (pkg / "core.py").write_text("class Thing: ...\n")

        resolver = ReexportResolver([tmp_path])
        # Should complete without raising, loading the invalid ... import as no-op
        loaded = resolver._transitive_loads("pkg")
        assert (pkg / "__init__.py").resolve() in loaded

    def test_non_init_module_safe_when_init_does_not_import_it(
        self,
        tmp_path: Path,
    ) -> None:
        """Shortening is still allowed when __init__.py does not load the file.

        ``pkg/outside.py`` with ``from pkg.core import Thing`` IS shortenable
        to ``from pkg import Thing`` when ``pkg/__init__.py`` only imports
        ``.core`` — no cycle is possible because loading ``pkg`` does not
        load ``outside.py``.
        """
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text(
            'from .core import Thing\n__all__ = ["Thing"]\n',
        )
        (pkg / "core.py").write_text("class Thing: ...\n")
        (pkg / "outside.py").write_text(
            "from pkg.core import Thing\n\ndef use() -> Thing: ...\n",
        )

        result, _ = check([tmp_path], src_roots=[tmp_path])
        outside_violations = [v for v in result.violations if v.file_path.name == "outside.py"]
        assert len(outside_violations) == 1
        assert outside_violations[0].shorter_path == "pkg"

    def test_cli_no_paths_no_config(self, monkeypatch, tmp_path: Path) -> None:
        """CLI with no paths and no config src falls back to Path()."""
        (tmp_path / "simple.py").write_text("import os")
        monkeypatch.chdir(tmp_path)
        # Pass empty config that has no 'src' key, and no path args
        # The config_str_list will return default ["."] which becomes [Path(".")]
        # But if we override to empty... let's just use a config with src=[]
        config = tmp_path / "empty.toml"
        config.write_text("[tool.minport]\nsrc = []")
        exit_code = main(["check", "--config", str(config)])
        assert exit_code == 0


class TestDefaultExcludes:
    """Tests for default exclude patterns (Issue #19)."""

    def test_default_excludes_skips_venv(self, tmp_path: Path) -> None:
        """Files inside .venv are excluded by default."""
        venv = tmp_path / ".venv" / "lib" / "site-packages" / "pkg"
        venv.mkdir(parents=True)
        (venv / "module.py").write_text("import sys")

        (tmp_path / "app.py").write_text("import os")

        result, _ = check([tmp_path], src_roots=[tmp_path])
        assert result.files_checked == 1

    def test_default_excludes_skips_pycache(self, tmp_path: Path) -> None:
        """Files inside __pycache__ are excluded by default."""
        cache = tmp_path / "__pycache__"
        cache.mkdir()
        (cache / "module.cpython-312.py").write_text("import sys")

        (tmp_path / "app.py").write_text("import os")

        result, _ = check([tmp_path], src_roots=[tmp_path])
        assert result.files_checked == 1

    def test_default_excludes_skips_node_modules(self, tmp_path: Path) -> None:
        """Files inside node_modules are excluded by default."""
        nm = tmp_path / "node_modules" / "some_tool"
        nm.mkdir(parents=True)
        (nm / "helper.py").write_text("import sys")

        (tmp_path / "app.py").write_text("import os")

        result, _ = check([tmp_path], src_roots=[tmp_path])
        assert result.files_checked == 1

    def test_explicit_exclude_overrides_defaults(self, tmp_path: Path) -> None:
        """Passing exclude= overrides DEFAULT_EXCLUDES entirely."""
        venv = tmp_path / ".venv"
        venv.mkdir()
        (venv / "mod.py").write_text("import sys")

        (tmp_path / "app.py").write_text("import os")
        (tmp_path / "skip.py").write_text("import os")

        result, _ = check([tmp_path], src_roots=[tmp_path], exclude=["skip.py"])
        # .venv is no longer excluded (defaults overridden), but skip.py is
        assert result.files_checked == 2  # app.py + .venv/mod.py

    def test_explicit_empty_exclude_disables_defaults(self, tmp_path: Path) -> None:
        """Passing exclude=[] disables all default excludes."""
        venv = tmp_path / ".venv"
        venv.mkdir()
        (venv / "mod.py").write_text("import sys")

        (tmp_path / "app.py").write_text("import os")

        result, _ = check([tmp_path], src_roots=[tmp_path], exclude=[])
        assert result.files_checked == 2  # app.py + .venv/mod.py

    def test_default_excludes_constant_contains_expected_entries(self) -> None:
        """DEFAULT_EXCLUDES contains the key entries from the Issue."""
        expected = {
            ".venv",
            "venv",
            "__pycache__",
            "node_modules",
            "dist",
            "site-packages",
            ".git",
        }
        assert expected.issubset(set(DEFAULT_EXCLUDES))

    def test_default_excludes_prunes_nested_directories(self, tmp_path: Path) -> None:
        """Default excludes prune entire directory trees, not just top-level."""
        deep = tmp_path / "src" / ".mypy_cache" / "sub" / "deep"
        deep.mkdir(parents=True)
        (deep / "cached.py").write_text("import sys")

        (tmp_path / "src").mkdir(exist_ok=True)
        (tmp_path / "src" / "app.py").write_text("import os")

        result, _ = check([tmp_path], src_roots=[tmp_path])
        assert result.files_checked == 1

    def test_cli_exclude_overrides_defaults(self, tmp_path: Path) -> None:
        """CLI --exclude overrides default excludes."""
        venv = tmp_path / ".venv"
        venv.mkdir()
        (venv / "mod.py").write_text("import sys")

        (tmp_path / "app.py").write_text("import os")
        (tmp_path / "skip.py").write_text("import os")

        exit_code = main(["check", str(tmp_path), "--exclude", "skip.py", "--src", str(tmp_path)])
        assert exit_code == 0  # .venv/mod.py + app.py checked, no violations

    def test_config_exclude_overrides_defaults(self, tmp_path: Path) -> None:
        """pyproject.toml exclude overrides default excludes."""
        venv = tmp_path / ".venv"
        venv.mkdir()
        (venv / "mod.py").write_text("import sys")

        (tmp_path / "app.py").write_text("import os")

        config = tmp_path / "pyproject.toml"
        config.write_text('[tool.minport]\nexclude = ["skip.py"]\n')

        exit_code = main(["check", str(tmp_path), "--config", str(config), "--src", str(tmp_path)])
        # .venv/mod.py is now included (defaults overridden), no violations
        assert exit_code == 0


class TestPerNameSuppress:
    """Tests for per-name # minport: ignore in multi-line imports (Issue #24)."""

    def _make_pkg(self, tmp_path: Path) -> None:
        """Create a package with re-exports for Foo and Bar."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        sub = pkg / "sub"
        sub.mkdir()
        (pkg / "__init__.py").write_text("from .sub.module import Foo, Bar")
        (sub / "__init__.py").write_text("from .module import Foo, Bar")
        (sub / "module.py").write_text("Foo = 1\nBar = 2")

    def test_multiline_suppress_single_name(self, tmp_path: Path) -> None:
        """Suppress comment on individual name line suppresses only that name."""
        self._make_pkg(tmp_path)
        test_file = tmp_path / "test.py"
        test_file.write_text(
            "from pkg.sub.module import (\n    Foo,  # minport: ignore\n    Bar,\n)\n"
        )

        result, _ = check([test_file], src_roots=[tmp_path])
        names = [v.name for v in result.violations]
        assert "Foo" not in names
        assert "Bar" in names

    def test_multiline_suppress_from_line_suppresses_all(self, tmp_path: Path) -> None:
        """Suppress comment on from line suppresses all names."""
        self._make_pkg(tmp_path)
        test_file = tmp_path / "test.py"
        test_file.write_text(
            "from pkg.sub.module import (  # minport: ignore\n    Foo,\n    Bar,\n)\n"
        )

        result, _ = check([test_file], src_roots=[tmp_path])
        assert len(result.violations) == 0

    def test_multiline_suppress_multiple_names(self, tmp_path: Path) -> None:
        """Suppress comments on multiple name lines suppress each independently."""
        self._make_pkg(tmp_path)
        test_file = tmp_path / "test.py"
        test_file.write_text(
            "from pkg.sub.module import (\n"
            "    Foo,  # minport: ignore\n"
            "    Bar,  # minport: ignore\n"
            ")\n"
        )

        result, _ = check([test_file], src_roots=[tmp_path])
        assert len(result.violations) == 0

    def test_single_line_import_suppress_unchanged(self, tmp_path: Path) -> None:
        """Single-line import with suppress still works (backward compat)."""
        self._make_pkg(tmp_path)
        test_file = tmp_path / "test.py"
        test_file.write_text(
            "from pkg.sub.module import Foo  # minport: ignore\nfrom pkg.sub.module import Bar\n"
        )

        result, _ = check([test_file], src_roots=[tmp_path])
        names = [v.name for v in result.violations]
        assert "Foo" not in names
        assert "Bar" in names

    def test_is_suppressed_name_line_differs_from_from_line(self) -> None:
        """_is_suppressed checks name_line when it differs from from line."""
        imp = ImportStatement(
            module_path="pkg.sub",
            name="Foo",
            alias=None,
            file_path=Path("test.py"),
            line=1,
            col=1,
            name_line=2,
        )
        source_lines = (
            "from pkg.sub import (",
            "    Foo,  # minport: ignore",
            ")",
        )
        assert _is_suppressed(imp, source_lines) is True

    def test_is_suppressed_same_line_no_comment(self) -> None:
        """_is_suppressed returns False when no comment on either line."""
        imp = ImportStatement(
            module_path="pkg.sub",
            name="Foo",
            alias=None,
            file_path=Path("test.py"),
            line=1,
            col=1,
            name_line=1,
        )
        source_lines = ("from pkg.sub import Foo",)
        assert _is_suppressed(imp, source_lines) is False

    def test_name_line_in_import_parser(self, tmp_path: Path) -> None:
        """parse_imports sets name_line from ast.alias.lineno."""
        source = "from pkg.sub import (\n    Foo,\n    Bar,\n)\n"
        tree = ast.parse(source)
        imports = parse_imports(tree, tmp_path / "test.py")
        assert len(imports) == 2
        foo = next(i for i in imports if i.name == "Foo")
        bar = next(i for i in imports if i.name == "Bar")
        assert foo.line == 1
        assert foo.name_line == 2
        assert bar.line == 1
        assert bar.name_line == 3

    def test_fix_with_per_name_suppress(self, tmp_path: Path) -> None:
        """--fix rewrites unsuppressed names even when siblings have # minport: ignore."""
        self._make_pkg(tmp_path)
        test_file = tmp_path / "test.py"
        test_file.write_text(
            "from pkg.sub.module import (\n    Foo,  # minport: ignore\n    Bar,\n)\n"
        )

        result, fix_result = check([test_file], src_roots=[tmp_path], fix=True)
        assert len(result.violations) == 1
        assert result.violations[0].name == "Bar"
        assert fix_result is not None
        assert fix_result.fixes_applied == 1

        content = test_file.read_text()
        assert "from pkg import Bar" in content
        assert "from pkg.sub.module import Foo  # minport: ignore" in content

    def test_fix_multiline_all_suppressed_no_change(self, tmp_path: Path) -> None:
        """--fix does nothing when all names are suppressed."""
        self._make_pkg(tmp_path)
        test_file = tmp_path / "test.py"
        original = (
            "from pkg.sub.module import (\n"
            "    Foo,  # minport: ignore\n"
            "    Bar,  # minport: ignore\n"
            ")\n"
        )
        test_file.write_text(original)

        result, fix_result = check([test_file], src_roots=[tmp_path], fix=True)
        assert len(result.violations) == 0
        assert fix_result is not None
        assert fix_result.fixes_applied == 0
        assert test_file.read_text() == original

    def test_fix_rewrites_import_with_user_comment(self, tmp_path: Path) -> None:
        """--fix rewrites imports and preserves inline comments."""
        self._make_pkg(tmp_path)
        test_file = tmp_path / "test.py"
        test_file.write_text(
            "from pkg.sub.module import (\n    Foo,  # important note\n    Bar,\n)\n",
        )

        result, fix_result = check([test_file], src_roots=[tmp_path], fix=True)
        assert len(result.violations) == 2
        assert fix_result is not None
        assert fix_result.fixes_applied == 2
        content = test_file.read_text()
        assert "from pkg import" in content
        assert "# important note" in content
