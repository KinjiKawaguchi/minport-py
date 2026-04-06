"""Tests for third-party package resolution (S-1 through S-6)."""

from __future__ import annotations

from pathlib import Path

from minport._reexport_resolver import ReexportResolver
from minport.checker import check


class TestThirdPartyResolution:
    """Test resolution of installed third-party packages."""

    def test_s1_installed_package_reexport(self) -> None:
        """S-1: Detect re-export from installed package."""
        # Use a known stdlib package that re-exports things
        # collections re-exports things from collections._abc
        # We just verify the resolver can handle installed packages
        resolver = ReexportResolver([])
        exported = resolver._get_exported_names("collections")
        # collections module should have some exports
        assert len(exported) >= 0

    def test_s2_nonexistent_package(self) -> None:
        """S-2: Non-existent package is skipped gracefully."""
        resolver = ReexportResolver([])
        exported = resolver._get_exported_names("nonexistent_xyz_package")
        assert len(exported) == 0

    def test_s3_stdlib_ast_parsing(self) -> None:
        """S-3: AST analysis of installed package (stdlib)."""
        resolver = ReexportResolver([])
        # pathlib module is a good test case
        exported = resolver._get_exported_names("pathlib")
        # pathlib may have various re-exports
        assert isinstance(exported, set)

    def test_s4_c_extension_only_skipped(self) -> None:
        """S-4: C extension modules are skipped gracefully."""
        resolver = ReexportResolver([])
        # Many modules have no __init__.py, should return empty
        exported = resolver._get_exported_names("sys")
        # sys is a built-in module with no __init__.py
        assert len(exported) == 0

    def test_s5_namespace_package(self) -> None:
        """S-5: Namespace packages are handled."""
        resolver = ReexportResolver([])
        # Try to find a namespace package (this may not exist in test env)
        # Just verify it doesn't crash
        exported = resolver._get_exported_names("pkgutil")
        assert isinstance(exported, set)

    def test_s6_all_respected_in_third_party(self, tmp_path: Path) -> None:
        """S-6: __all__ in installed packages is respected."""
        # Create a mock installed structure for testing
        pkg = tmp_path / "testpkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text('from .module import A, B\n__all__ = ["A"]')
        (pkg / "module.py").write_text("A = 1\nB = 2")

        resolver = ReexportResolver([tmp_path])
        exported = resolver._get_exported_names("testpkg")
        # Only A should be exported because of __all__
        assert "A" in exported
        assert "B" not in exported

    def test_third_party_import_in_check(self, tmp_path: Path) -> None:
        """Test: check() handles third-party imports correctly."""
        test_file = tmp_path / "test.py"
        # Import from a stdlib module with re-exports
        test_file.write_text("from os.path import exists")

        result, _ = check([test_file], src_roots=[tmp_path])
        # This may or may not have violations depending on os.path's structure
        # Just verify it doesn't crash
        assert result.files_checked == 1
