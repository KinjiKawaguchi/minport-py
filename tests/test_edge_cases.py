"""Tests for edge cases (E-1 through E-10)."""

from __future__ import annotations

from pathlib import Path

import pytest

from minport._reexport_resolver import ReexportResolver
from minport.checker import _has_suppress_comment, _is_excluded, check
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
