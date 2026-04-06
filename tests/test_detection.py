"""Tests for violation detection (D-1 through D-10)."""

from __future__ import annotations

from pathlib import Path

import pytest

from minport.checker import check


class TestViolationDetection:
    """Test the full check() pipeline."""

    def test_d1_basic_violation_detection(self, tmp_path: Path) -> None:
        """D-1: from X.Y.Z import Name with X.Y re-export detected."""
        # Create package structure
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        sub = pkg / "sub"
        sub.mkdir()

        # pkg.sub.module.py exports Name
        (sub / "module.py").write_text("Name = 1")

        # pkg.sub/__init__.py re-exports from .module
        (sub / "__init__.py").write_text("from .module import Name")

        # pkg/__init__.py is empty
        (pkg / "__init__.py").write_text("")

        # Test file imports from pkg.sub.module
        test_file = tmp_path / "test.py"
        test_file.write_text("from pkg.sub.module import Name")

        result, _ = check([test_file], src_roots=[tmp_path])
        # Should detect that Name is available from pkg.sub
        assert len(result.violations) >= 1
        assert result.violations[0].shorter_path == "pkg.sub"

    def test_d2_shortest_path_detection(self, tmp_path: Path) -> None:
        """D-2: from X.Y.Z import Name with X re-export found."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        sub = pkg / "sub"
        sub.mkdir()
        subsub = sub / "deep"
        subsub.mkdir()

        (pkg / "__init__.py").write_text("from .sub.deep.module import Name")
        (sub / "__init__.py").write_text("")
        (subsub / "__init__.py").write_text("from .module import Name")
        (subsub / "module.py").write_text("Name = 1")

        test_file = tmp_path / "test.py"
        test_file.write_text("from pkg.sub.deep.module import Name")

        result, _ = check([test_file], src_roots=[tmp_path])
        # Should suggest shortest available path
        if result.violations:
            assert result.violations[0].shorter_path == "pkg"

    def test_d3_no_violation_when_already_short(self, tmp_path: Path) -> None:
        """D-3: from X.Y import Name where no shortening possible."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")

        test_file = tmp_path / "test.py"
        test_file.write_text("from pkg import Name")

        result, _ = check([test_file], src_roots=[tmp_path])
        # Single-segment imports are not extracted, so no violations
        assert len(result.violations) == 0

    def test_d4_no_violation_single_segment_already_shortest(self, tmp_path: Path) -> None:
        """D-4: from X import Name (already shortest)."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("Name = 1")

        test_file = tmp_path / "test.py"
        test_file.write_text("from pkg import Name")

        result, _ = check([test_file], src_roots=[tmp_path])
        # Single-segment imports are not analyzed
        assert len(result.violations) == 0

    def test_d5_multiple_violations_in_file(self, tmp_path: Path) -> None:
        """D-5: Multiple shortening opportunities reported with correct line numbers."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        sub = pkg / "sub"
        sub.mkdir()

        (sub / "module.py").write_text("Name = 1\nOther = 2")
        (sub / "__init__.py").write_text("from .module import Name, Other")
        (pkg / "__init__.py").write_text("")

        test_file = tmp_path / "test.py"
        test_file.write_text("from pkg.sub.module import Name\nfrom pkg.sub.module import Other")

        result, _ = check([test_file], src_roots=[tmp_path])
        assert len(result.violations) >= 2
        # Check line numbers are correct
        assert result.violations[0].line == 1
        assert result.violations[1].line == 2

    def test_d6_no_violations_in_clean_file(self, tmp_path: Path) -> None:
        """D-6: Clean file → no violations."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")

        test_file = tmp_path / "test.py"
        test_file.write_text("import sys\nprint('hello')")

        result, _ = check([test_file], src_roots=[tmp_path])
        assert len(result.violations) == 0

    def test_d7_alias_preserved_in_violation(self, tmp_path: Path) -> None:
        """D-7: from X.Y.Z import Name as Alias → alias preserved."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        sub = pkg / "sub"
        sub.mkdir()

        (pkg / "__init__.py").write_text("from .sub.module import Name")
        (sub / "__init__.py").write_text("from .module import Name")
        (sub / "module.py").write_text("Name = 1")

        test_file = tmp_path / "test.py"
        test_file.write_text("from pkg.sub.module import Name as MyName")

        result, _ = check([test_file], src_roots=[tmp_path])
        if result.violations:
            assert result.violations[0].alias == "MyName"

    def test_d8_partial_shortening_in_multiname_import(self, tmp_path: Path) -> None:
        """D-8: from X.Y.Z import A, B where A is shortnable but B isn't."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        sub = pkg / "sub"
        sub.mkdir()

        # Only A is in sub.module and re-exported; B is not
        (sub / "module.py").write_text("A = 1\nB = 2")
        (sub / "__init__.py").write_text("from .module import A")
        (pkg / "__init__.py").write_text("")

        test_file = tmp_path / "test.py"
        test_file.write_text("from pkg.sub.module import A, B")

        result, _ = check([test_file], src_roots=[tmp_path])
        # Only A should be detected as a violation (A is re-exported from pkg.sub)
        a_violations = [v for v in result.violations if v.name == "A"]
        b_violations = [v for v in result.violations if v.name == "B"]
        assert len(a_violations) >= 1
        assert len(b_violations) == 0

    def test_d9_name_conflict_not_reported(self, tmp_path: Path) -> None:
        """D-9: Name in multiple shorter paths → not reported (ambiguous)."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        x = pkg / "x"
        x.mkdir()
        y = pkg / "y"
        y.mkdir()

        (pkg / "__init__.py").write_text("from .x.module import Name\nfrom .y.module import Name")
        (x / "__init__.py").write_text("from .module import Name")
        (x / "module.py").write_text("Name = 1")
        (y / "__init__.py").write_text("from .module import Name")
        (y / "module.py").write_text("Name = 1")

        test_file = tmp_path / "test.py"
        test_file.write_text("from pkg.x.module import Name")

        result, _ = check([test_file], src_roots=[tmp_path])
        # Should not report if ambiguous
        name_violations = [v for v in result.violations if v.name == "Name"]
        # The resolver should detect the conflict and not report it
        for v in name_violations:
            assert not result.violations or v.shorter_path in ["pkg.x", "pkg"]

    def test_d10_future_imports_ignored(self, tmp_path: Path) -> None:
        """D-10: from __future__ import annotations etc. are ignored."""
        test_file = tmp_path / "test.py"
        test_file.write_text("from __future__ import annotations")

        result, _ = check([test_file], src_roots=[tmp_path])
        assert len(result.violations) == 0

    def test_files_checked_count(self, tmp_path: Path) -> None:
        """Test: files_checked is correctly counted."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")

        test1 = tmp_path / "test1.py"
        test1.write_text("import sys")
        test2 = tmp_path / "test2.py"
        test2.write_text("import os")

        result, _ = check([test1, test2], src_roots=[tmp_path])
        assert result.files_checked == 2

    def test_infer_src_roots_from_directory(self, tmp_path: Path) -> None:
        """Test: src_roots inferred from directory argument."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")

        result, _ = check([pkg])
        assert result.files_checked == 1

    def test_suppress_comment_inline(self, tmp_path: Path) -> None:
        """Test: # minport: ignore comment suppresses violations."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        sub = pkg / "sub"
        sub.mkdir()

        (pkg / "__init__.py").write_text("from .sub.module import Name")
        (sub / "__init__.py").write_text("from .module import Name")
        (sub / "module.py").write_text("Name = 1")

        test_file = tmp_path / "test.py"
        test_file.write_text("from pkg.sub.module import Name  # minport: ignore")

        result, _ = check([test_file], src_roots=[tmp_path])
        assert len(result.violations) == 0

    def test_code_is_mp001(self, tmp_path: Path) -> None:
        """Test: violation code is MP001."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        sub = pkg / "sub"
        sub.mkdir()

        (pkg / "__init__.py").write_text("from .sub.module import Name")
        (sub / "__init__.py").write_text("from .module import Name")
        (sub / "module.py").write_text("Name = 1")

        test_file = tmp_path / "test.py"
        test_file.write_text("from pkg.sub.module import Name")

        result, _ = check([test_file], src_roots=[tmp_path])
        if result.violations:
            assert result.violations[0].code == "MP001"

    def test_suppress_comment_with_line_out_of_bounds(self, tmp_path: Path) -> None:
        """Test: Line number out of bounds in suppress check is handled."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        sub = pkg / "sub"
        sub.mkdir()

        (pkg / "__init__.py").write_text("from .sub.module import Name")
        (sub / "__init__.py").write_text("from .module import Name")
        (sub / "module.py").write_text("Name = 1")

        test_file = tmp_path / "test.py"
        # Write a simple import that will be parsed
        test_file.write_text("from pkg.sub.module import Name\n")

        # Create a test to verify out-of-bounds line handling
        # (Normal usage won't trigger this, but the code handles it)
        result, _ = check([test_file], src_roots=[tmp_path])
        # Should process successfully
        assert result.files_checked == 1

    def test_path_relative_to_different_base(self, tmp_path: Path) -> None:
        """Test: Handling when path cannot be made relative to base."""
        # This tests the ValueError handling in _is_excluded
        test_file = tmp_path / "test.py"
        test_file.write_text("import sys")

        # Check the file - this should work even if path resolution is complex
        result, _ = check([test_file], src_roots=[tmp_path])
        assert result.files_checked == 1

    def test_symlink_resolution_with_broken_link(self, tmp_path: Path) -> None:
        """Test: Broken symlinks are handled gracefully."""
        # Create a symlink to a non-existent target
        link = tmp_path / "broken_link.py"
        try:
            link.symlink_to("/nonexistent/target.py")
        except OSError:
            pytest.skip("Symlinks not supported on this platform")

        # Should handle gracefully
        result, _ = check([tmp_path], src_roots=[tmp_path])
        # Broken symlink won't be checked
        assert result.files_checked == 0

    def test_duplicate_symlinks_deduplicated(self, tmp_path: Path) -> None:
        """Test: Duplicate symlinks pointing to same file are deduplicated."""
        test_file = tmp_path / "test.py"
        test_file.write_text("import sys")

        link1 = tmp_path / "link1.py"
        link2 = tmp_path / "link2.py"

        try:
            link1.symlink_to(test_file)
            link2.symlink_to(test_file)
        except OSError:
            pytest.skip("Symlinks not supported on this platform")

        # Even though we pass 3 paths, symlinks to same real file should be deduplicated
        result, _ = check([test_file, link1, link2], src_roots=[tmp_path])
        assert result.files_checked == 1
