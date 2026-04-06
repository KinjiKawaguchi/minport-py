"""Tests for import statement parsing (P-1 through P-8)."""

from __future__ import annotations

import ast
from pathlib import Path

from minport._import_parser import parse_imports


class TestParseImports:
    """Test parse_imports() function."""

    def test_p1_basic_from_import(self) -> None:
        """P-1: Basic from X.Y.Z import Name extraction."""
        source = "from x.y.z import Name"
        tree = ast.parse(source)
        result = parse_imports(tree, Path("test.py"))

        assert len(result) == 1
        assert result[0].module_path == "x.y.z"
        assert result[0].name == "Name"
        assert result[0].alias is None
        assert result[0].line == 1

    def test_p2_alias_handling(self) -> None:
        """P-2: Alias (as) handling."""
        source = "from x.y import Name as Alias"
        tree = ast.parse(source)
        result = parse_imports(tree, Path("test.py"))

        assert len(result) == 1
        assert result[0].module_path == "x.y"
        assert result[0].name == "Name"
        assert result[0].alias == "Alias"

    def test_p3_multiple_names_in_import(self) -> None:
        """P-3: Multiple names in one import statement."""
        source = "from x.y import A, B, C"
        tree = ast.parse(source)
        result = parse_imports(tree, Path("test.py"))

        assert len(result) == 3
        assert result[0].name == "A"
        assert result[1].name == "B"
        assert result[2].name == "C"
        for imp in result:
            assert imp.module_path == "x.y"

    def test_p4_import_without_from_ignored(self) -> None:
        """P-4: import X.Y.Z (no from) is ignored."""
        source = "import x.y.z"
        tree = ast.parse(source)
        result = parse_imports(tree, Path("test.py"))

        assert len(result) == 0

    def test_p5_relative_imports_ignored(self) -> None:
        """P-5: Relative imports ignored."""
        source = "from . import Name\nfrom .module import Other"
        tree = ast.parse(source)
        result = parse_imports(tree, Path("test.py"))

        assert len(result) == 0

    def test_p6_single_segment_not_extracted(self) -> None:
        """P-6: Single-segment from X import Name — no "." so not extracted."""
        source = "from x import Name"
        tree = ast.parse(source)
        result = parse_imports(tree, Path("test.py"))

        # Single segment imports have no ".", so they are not extracted
        assert len(result) == 0

    def test_p7_multiline_imports(self) -> None:
        """P-7: Multi-line imports with proper line numbers."""
        source = "from x.y import (\n    A,\n    B,\n    C\n)"
        tree = ast.parse(source)
        result = parse_imports(tree, Path("test.py"))

        assert len(result) == 3
        # All should be on line 1 (AST reports the line of the from keyword)
        for imp in result:
            assert imp.line == 1

    def test_p8_comments_and_strings_ignored(self) -> None:
        """P-8: Comments and strings are naturally ignored by AST."""
        source = """# from x.y import NotImported
\"\"\"from x.y import AlsoNotImported\"\"\"
from a.b import RealImport
"""
        tree = ast.parse(source)
        result = parse_imports(tree, Path("test.py"))

        assert len(result) == 1
        assert result[0].name == "RealImport"

    def test_future_imports_ignored(self) -> None:
        """Test: from __future__ imports are ignored."""
        source = "from __future__ import annotations"
        tree = ast.parse(source)
        result = parse_imports(tree, Path("test.py"))

        assert len(result) == 0

    def test_col_offset_calculation(self) -> None:
        """Test: col_offset is reported correctly (1-indexed)."""
        source = "from x.y import Name"
        tree = ast.parse(source)
        result = parse_imports(tree, Path("test.py"))

        # The 'from' keyword starts at column 0, so col_offset should be 1
        assert result[0].col == 1

    def test_file_path_preserved(self) -> None:
        """Test: file_path is correctly preserved."""
        source = "from x.y import Name"
        tree = ast.parse(source)
        file_path = Path("src/mymodule.py")
        result = parse_imports(tree, file_path)

        assert result[0].file_path == file_path

    def test_mixed_imports_with_ignored(self) -> None:
        """Test: mix of extractable and ignorable imports."""
        source = """import single
from x import SingleSegment
from a.b import Name
from . import Relative
"""
        tree = ast.parse(source)
        result = parse_imports(tree, Path("test.py"))

        # Only the a.b import should be extracted
        assert len(result) == 1
        assert result[0].module_path == "a.b"
        assert result[0].name == "Name"
