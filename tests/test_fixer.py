"""Tests for auto-fix functionality (F-1 through F-8)."""

from __future__ import annotations

import ast
from pathlib import Path

from minport._fixer import fix_file, fix_files
from minport._models import Violation


class TestFixer:
    """Test fix_file() and fix_files() functions."""

    def test_f1_single_import_line_shortened(self, tmp_path: Path) -> None:
        """F-1: Single import line is shortened."""
        test_file = tmp_path / "test.py"
        test_file.write_text("from x.y.z import Name\n")

        violation = Violation(
            file_path=test_file,
            line=1,
            col=1,
            original_path="x.y.z",
            shorter_path="x.y",
            name="Name",
            alias=None,
            code="MP001",
            message="test",
        )

        result = fix_file(test_file, [violation])
        assert result is True

        content = test_file.read_text()
        assert "from x.y import Name" in content

    def test_f2_alias_preserved_in_fix(self, tmp_path: Path) -> None:
        """F-2: Alias is preserved when shortening."""
        test_file = tmp_path / "test.py"
        test_file.write_text("from x.y.z import Name as MyAlias\n")

        violation = Violation(
            file_path=test_file,
            line=1,
            col=1,
            original_path="x.y.z",
            shorter_path="x.y",
            name="Name",
            alias="MyAlias",
            code="MP001",
            message="test",
        )

        fix_file(test_file, [violation])
        content = test_file.read_text()
        assert "from x.y import Name as MyAlias" in content

    def test_f3_multiple_violations_in_file(self, tmp_path: Path) -> None:
        """F-3: Multiple violations in same file are all fixed."""
        test_file = tmp_path / "test.py"
        test_file.write_text("from x.y.z import A\nfrom x.y.z import B\n")

        violations = [
            Violation(
                file_path=test_file,
                line=1,
                col=1,
                original_path="x.y.z",
                shorter_path="x.y",
                name="A",
                alias=None,
                code="MP001",
                message="test",
            ),
            Violation(
                file_path=test_file,
                line=2,
                col=1,
                original_path="x.y.z",
                shorter_path="x.y",
                name="B",
                alias=None,
                code="MP001",
                message="test",
            ),
        ]

        result = fix_file(test_file, violations)
        assert result is True

        content = test_file.read_text()
        assert "from x.y import A" in content
        assert "from x.y import B" in content

    def test_f4_fixed_file_is_syntactically_valid(self, tmp_path: Path) -> None:
        """F-4: Fixed file is syntactically valid (ast.parse succeeds)."""
        test_file = tmp_path / "test.py"
        test_file.write_text("from x.y.z import Name\nprint(Name)\n")

        violation = Violation(
            file_path=test_file,
            line=1,
            col=1,
            original_path="x.y.z",
            shorter_path="x.y",
            name="Name",
            alias=None,
            code="MP001",
            message="test",
        )

        fix_file(test_file, [violation])
        content = test_file.read_text()
        # Should not raise
        ast.parse(content)

    def test_f5_no_fix_without_flag(self, tmp_path: Path) -> None:
        """F-5: Without --fix flag, file is not modified (tested in CLI)."""
        # This is tested in CLI tests, but we can verify fix_file behavior
        test_file = tmp_path / "test.py"
        original = "from x.y.z import Name\n"
        test_file.write_text(original)

        # Only test fix_file returns False when given empty violations
        result = fix_file(test_file, [])
        assert result is False

    def test_f6_no_violations_no_modification(self, tmp_path: Path) -> None:
        """F-6: File with no violations is not modified."""
        test_file = tmp_path / "test.py"
        original = "from x.y import Name\n"
        test_file.write_text(original)

        result = fix_file(test_file, [])
        assert result is False
        assert test_file.read_text() == original

    def test_f7_name_conflict_not_fixed(self, tmp_path: Path) -> None:
        """F-7: Name conflicts are not fixed (checker responsibility)."""
        # This is actually handled by the checker not creating violations
        # in the first place, but we test the fixer behavior anyway
        test_file = tmp_path / "test.py"
        test_file.write_text("from x.y.z import Name\n")

        # If a violation is passed with a None shorter_path, don't fix
        violation = Violation(
            file_path=test_file,
            line=1,
            col=1,
            original_path="x.y.z",
            shorter_path="x.y.z",  # Same as original
            name="Name",
            alias=None,
            code="MP001",
            message="test",
        )

        result = fix_file(test_file, [violation])
        # Should not modify since the paths are the same
        assert result is False

    def test_f8_fix_result_counts(self, tmp_path: Path) -> None:
        """F-8: FixResult reports correct files_modified and fixes_applied."""
        file1 = tmp_path / "test1.py"
        file1.write_text("from x.y.z import Name\n")

        file2 = tmp_path / "test2.py"
        file2.write_text("from a.b.c import Other\n")

        violations = {
            file1: [
                Violation(
                    file_path=file1,
                    line=1,
                    col=1,
                    original_path="x.y.z",
                    shorter_path="x.y",
                    name="Name",
                    alias=None,
                    code="MP001",
                    message="test",
                ),
            ],
            file2: [
                Violation(
                    file_path=file2,
                    line=1,
                    col=1,
                    original_path="a.b.c",
                    shorter_path="a.b",
                    name="Other",
                    alias=None,
                    code="MP001",
                    message="test",
                ),
            ],
        }

        result = fix_files(violations)
        assert result.files_modified == 2
        assert result.fixes_applied == 2

    def test_fix_file_with_unreadable_file(self, tmp_path: Path) -> None:
        """Test: fix_file returns False for unreadable files."""
        test_file = tmp_path / "test.py"
        test_file.write_text("from x.y.z import Name\n")
        test_file.chmod(0o000)  # Make unreadable

        violation = Violation(
            file_path=test_file,
            line=1,
            col=1,
            original_path="x.y.z",
            shorter_path="x.y",
            name="Name",
            alias=None,
            code="MP001",
            message="test",
        )

        result = fix_file(test_file, [violation])
        assert result is False

        # Clean up
        test_file.chmod(0o644)

    def test_fix_preserves_line_endings(self, tmp_path: Path) -> None:
        """Test: Line endings are preserved."""
        test_file = tmp_path / "test.py"
        test_file.write_text("from x.y.z import Name\nprint('hello')\n")

        violation = Violation(
            file_path=test_file,
            line=1,
            col=1,
            original_path="x.y.z",
            shorter_path="x.y",
            name="Name",
            alias=None,
            code="MP001",
            message="test",
        )

        fix_file(test_file, [violation])
        content = test_file.read_text()
        # Should still have proper line endings
        assert content.count("\n") == 2

    def test_fix_with_out_of_bounds_line(self, tmp_path: Path) -> None:
        """Test: Violations with out-of-bounds line numbers are skipped."""
        test_file = tmp_path / "test.py"
        test_file.write_text("from x.y.z import Name\n")

        violation = Violation(
            file_path=test_file,
            line=999,  # Out of bounds
            col=1,
            original_path="x.y.z",
            shorter_path="x.y",
            name="Name",
            alias=None,
            code="MP001",
            message="test",
        )

        result = fix_file(test_file, [violation])
        assert result is False

    def test_fix_multiple_violations_reverse_order(self, tmp_path: Path) -> None:
        """Test: Violations processed in reverse line order to preserve line numbers."""
        test_file = tmp_path / "test.py"
        test_file.write_text("from x.y.z import A\nfrom x.y.z import B\nfrom x.y.z import C\n")

        violations = [
            Violation(
                file_path=test_file,
                line=3,
                col=1,
                original_path="x.y.z",
                shorter_path="x.y",
                name="C",
                alias=None,
                code="MP001",
                message="test",
            ),
            Violation(
                file_path=test_file,
                line=1,
                col=1,
                original_path="x.y.z",
                shorter_path="x.y",
                name="A",
                alias=None,
                code="MP001",
                message="test",
            ),
            Violation(
                file_path=test_file,
                line=2,
                col=1,
                original_path="x.y.z",
                shorter_path="x.y",
                name="B",
                alias=None,
                code="MP001",
                message="test",
            ),
        ]

        result = fix_file(test_file, violations)
        assert result is True

        content = test_file.read_text()
        assert "from x.y import A" in content
        assert "from x.y import B" in content
        assert "from x.y import C" in content

    def test_multi_name_partial_move_splits_line(self, tmp_path: Path) -> None:
        """Regression for issue #2.

        ``from x.y.z import A, B`` where only ``A`` can be shortened to
        ``x.y`` must not move ``B`` along with it. The fixer has to split
        the statement so that ``B`` remains importable from ``x.y.z``.
        """
        test_file = tmp_path / "test.py"
        test_file.write_text("from x.y.z import A, B\n")

        violation = Violation(
            file_path=test_file,
            line=1,
            col=1,
            original_path="x.y.z",
            shorter_path="x.y",
            name="A",
            alias=None,
            code="MP001",
            message="test",
        )

        fix_file(test_file, [violation])
        content = test_file.read_text()

        assert "from x.y import A" in content
        assert "from x.y.z import B" in content
        assert "from x.y import A, B" not in content
        ast.parse(content)

    def test_multi_name_all_moved_to_same_shorter_path(self, tmp_path: Path) -> None:
        """All names on a line move to the same shorter path → single rewrite."""
        test_file = tmp_path / "test.py"
        test_file.write_text("from x.y.z import A, B\n")

        violations = [
            Violation(
                file_path=test_file,
                line=1,
                col=1,
                original_path="x.y.z",
                shorter_path="x.y",
                name="A",
                alias=None,
                code="MP001",
                message="test",
            ),
            Violation(
                file_path=test_file,
                line=1,
                col=1,
                original_path="x.y.z",
                shorter_path="x.y",
                name="B",
                alias=None,
                code="MP001",
                message="test",
            ),
        ]

        fix_file(test_file, violations)
        content = test_file.read_text()

        assert "from x.y import A, B" in content
        assert "from x.y.z" not in content
        ast.parse(content)

    def test_multi_name_split_to_different_shorter_paths(
        self,
        tmp_path: Path,
    ) -> None:
        """Names moving to different shorter paths produce one line each."""
        test_file = tmp_path / "test.py"
        test_file.write_text("from x.y.z import A, B, C\n")

        violations = [
            Violation(
                file_path=test_file,
                line=1,
                col=1,
                original_path="x.y.z",
                shorter_path="x",
                name="A",
                alias=None,
                code="MP001",
                message="test",
            ),
            Violation(
                file_path=test_file,
                line=1,
                col=1,
                original_path="x.y.z",
                shorter_path="x.y",
                name="B",
                alias=None,
                code="MP001",
                message="test",
            ),
        ]

        fix_file(test_file, violations)
        content = test_file.read_text()

        assert "from x import A" in content
        assert "from x.y import B" in content
        assert "from x.y.z import C" in content
        ast.parse(content)

    def test_multi_name_partial_move_preserves_alias(self, tmp_path: Path) -> None:
        """Alias on the moved name is preserved; untouched name keeps its alias too."""
        test_file = tmp_path / "test.py"
        test_file.write_text("from x.y.z import A as AA, B as BB\n")

        violation = Violation(
            file_path=test_file,
            line=1,
            col=1,
            original_path="x.y.z",
            shorter_path="x.y",
            name="A",
            alias="AA",
            code="MP001",
            message="test",
        )

        fix_file(test_file, [violation])
        content = test_file.read_text()

        assert "from x.y import A as AA" in content
        assert "from x.y.z import B as BB" in content
        ast.parse(content)

    def test_fix_syntax_error_file_skipped(self, tmp_path: Path) -> None:
        """Fixer returns False for files that cannot be parsed."""
        test_file = tmp_path / "broken.py"
        test_file.write_text("from x.y.z import (\n")  # unterminated

        violation = Violation(
            file_path=test_file,
            line=1,
            col=1,
            original_path="x.y.z",
            shorter_path="x.y",
            name="Name",
            alias=None,
            code="MP001",
            message="test",
        )

        assert fix_file(test_file, [violation]) is False

    def test_fix_skips_import_with_inline_comment(self, tmp_path: Path) -> None:
        """Inline comments on the import line block the rewrite (preserves the comment)."""
        test_file = tmp_path / "test.py"
        original = "from x.y.z import Name  # keep this\n"
        test_file.write_text(original)

        violation = Violation(
            file_path=test_file,
            line=1,
            col=1,
            original_path="x.y.z",
            shorter_path="x.y",
            name="Name",
            alias=None,
            code="MP001",
            message="test",
        )

        assert fix_file(test_file, [violation]) is False
        assert test_file.read_text() == original

    def test_fix_skips_import_after_semicolon(self, tmp_path: Path) -> None:
        """An import preceded by another statement on the same line is left alone."""
        test_file = tmp_path / "test.py"
        original = "a = 1; from x.y.z import Name\n"
        test_file.write_text(original)

        violation = Violation(
            file_path=test_file,
            line=1,
            col=7,
            original_path="x.y.z",
            shorter_path="x.y",
            name="Name",
            alias=None,
            code="MP001",
            message="test",
        )

        assert fix_file(test_file, [violation]) is False
        assert test_file.read_text() == original

    def test_fix_skips_stale_violation_mismatched_module(
        self,
        tmp_path: Path,
    ) -> None:
        """A violation whose original_path does not match the node is skipped."""
        test_file = tmp_path / "test.py"
        original = "from x.y.z import Name\n"
        test_file.write_text(original)

        violation = Violation(
            file_path=test_file,
            line=1,
            col=1,
            original_path="totally.different",
            shorter_path="totally",
            name="Name",
            alias=None,
            code="MP001",
            message="test",
        )

        assert fix_file(test_file, [violation]) is False
        assert test_file.read_text() == original

    def test_fix_preserves_tab_indentation(self, tmp_path: Path) -> None:
        """Tab-indented imports keep their tab prefix so the result still parses."""
        test_file = tmp_path / "test.py"
        test_file.write_text("if True:\n\tfrom x.y.z import A, B\n\tprint(A, B)\n")

        violation = Violation(
            file_path=test_file,
            line=2,
            col=2,
            original_path="x.y.z",
            shorter_path="x.y",
            name="A",
            alias=None,
            code="MP001",
            message="test",
        )

        fix_file(test_file, [violation])
        content = test_file.read_text()

        assert "\tfrom x.y import A" in content
        assert "\tfrom x.y.z import B" in content
        ast.parse(content)  # no TabError

    def test_fix_skips_import_with_trailing_semicolon_code(
        self,
        tmp_path: Path,
    ) -> None:
        """Code after an import on the same line blocks the rewrite."""
        test_file = tmp_path / "test.py"
        original = "from x.y.z import A; y = 1\n"
        test_file.write_text(original)

        violation = Violation(
            file_path=test_file,
            line=1,
            col=1,
            original_path="x.y.z",
            shorter_path="x.y",
            name="A",
            alias=None,
            code="MP001",
            message="test",
        )

        assert fix_file(test_file, [violation]) is False
        assert test_file.read_text() == original

    def test_fix_file_without_trailing_newline(self, tmp_path: Path) -> None:
        """A final import line without a trailing newline is handled."""
        test_file = tmp_path / "test.py"
        test_file.write_text("from x.y.z import Name")

        violation = Violation(
            file_path=test_file,
            line=1,
            col=1,
            original_path="x.y.z",
            shorter_path="x.y",
            name="Name",
            alias=None,
            code="MP001",
            message="test",
        )

        assert fix_file(test_file, [violation]) is True
        assert test_file.read_text() == "from x.y import Name"

    def test_fix_with_import_not_matching_pattern(self, tmp_path: Path) -> None:
        """Test: When import pattern doesn't match, line is left unchanged."""
        test_file = tmp_path / "test.py"
        # Use a relative import which won't have the expected pattern
        test_file.write_text("from .module import Name\n")

        violation = Violation(
            file_path=test_file,
            line=1,
            col=1,
            original_path="x.y.z",
            shorter_path="x.y",
            name="Name",
            alias=None,
            code="MP001",
            message="test",
        )

        fix_file(test_file, [violation])
        # Pattern won't match, so file is unchanged
        content = test_file.read_text()
        assert "from .module import Name" in content
