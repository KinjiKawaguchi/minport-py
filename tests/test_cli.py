"""Tests for CLI functionality (CLI-1 through CLI-8)."""

from __future__ import annotations

from pathlib import Path

import pytest

from minport.cli import main


class TestCLI:
    """Test CLI entry point."""

    def test_cli1_no_violations_exit_code_0(self, tmp_path: Path) -> None:
        """CLI-1: No violations → exit code 0."""
        test_file = tmp_path / "test.py"
        test_file.write_text("import sys\nprint('hello')")

        exit_code = main(["check", str(test_file)])
        assert exit_code == 0

    def test_cli2_violations_exist_exit_code_1(self, tmp_path: Path) -> None:
        """CLI-2: Violations found → exit code 1."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        sub = pkg / "sub"
        sub.mkdir()

        (sub / "module.py").write_text("Name = 1")
        (sub / "__init__.py").write_text("from .module import Name")
        (pkg / "__init__.py").write_text("")

        test_file = tmp_path / "test.py"
        test_file.write_text("from pkg.sub.module import Name")

        exit_code = main(["check", str(test_file), "--src", str(tmp_path)])
        assert exit_code == 1

    def test_cli3_fix_flag_modifies_files(self, tmp_path: Path) -> None:
        """CLI-3: --fix flag modifies files and returns exit code 1."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        sub = pkg / "sub"
        sub.mkdir()

        (sub / "module.py").write_text("Name = 1")
        (sub / "__init__.py").write_text("from .module import Name")
        (pkg / "__init__.py").write_text("")

        test_file = tmp_path / "test.py"
        test_file.write_text("from pkg.sub.module import Name")

        exit_code = main(["check", str(test_file), "--fix", "--src", str(tmp_path)])
        # Exit code is 1 because violations were found (even though they were fixed)
        assert exit_code == 1

        # File should be modified
        content = test_file.read_text()
        assert "from pkg.sub import Name" in content

    def test_cli4_help_flag(self, capsys: pytest.CaptureFixture[str]) -> None:
        """CLI-4: --help displays help."""
        with pytest.raises(SystemExit) as exc_info:
            main(["--help"])
        assert exc_info.value.code == 0

        captured = capsys.readouterr()
        assert "minport" in captured.out or "usage" in captured.out.lower()

    def test_cli5_nonexistent_path_error(self) -> None:
        """CLI-5: Non-existent path returns exit code 2."""
        exit_code = main(["check", "/nonexistent/path/to/file.py"])
        assert exit_code == 2

    def test_cli6_exclude_pattern(self, tmp_path: Path) -> None:
        """CLI-6: --exclude pattern works."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        sub = pkg / "sub"
        sub.mkdir()

        (pkg / "__init__.py").write_text("")
        (sub / "__init__.py").write_text("from .module import Name")
        (sub / "module.py").write_text("Name = 1")

        test_file = tmp_path / "test.py"
        test_file.write_text("from pkg.sub.module import Name")

        excluded_file = tmp_path / "excluded.py"
        excluded_file.write_text("from pkg.sub.module import Name")

        # Without exclude: both files have violations
        exit_code = main(["check", str(tmp_path), "--src", str(tmp_path)])
        assert exit_code == 1

        # With exclude: only test.py is checked, excluded.py is skipped
        exit_code = main(
            ["check", str(tmp_path), "--exclude", "excluded.py", "--src", str(tmp_path)]
        )
        # Should still find violations in test.py
        assert exit_code == 1

    def test_cli7_src_flag_for_import_resolution(self, tmp_path: Path) -> None:
        """CLI-7: --src specifies source root for import resolution."""
        src = tmp_path / "src"
        src.mkdir()

        pkg = src / "pkg"
        pkg.mkdir()
        sub = pkg / "sub"
        sub.mkdir()

        (pkg / "__init__.py").write_text("from .sub.module import Name")
        (sub / "__init__.py").write_text("from .module import Name")
        (sub / "module.py").write_text("Name = 1")

        test_file = tmp_path / "test.py"
        test_file.write_text("from pkg.sub.module import Name")

        exit_code = main(["check", str(test_file), "--src", str(src)])
        # Should find the source root and detect violations
        assert exit_code in (0, 1)

    def test_cli8_config_from_pyproject(self, tmp_path: Path) -> None:
        """CLI-8: pyproject.toml [tool.minport] is loaded."""
        config_file = tmp_path / "pyproject.toml"
        config_file.write_text('[tool.minport]\nsrc = ["src"]\nexclude = ["tests/*"]\n')

        test_file = tmp_path / "test.py"
        test_file.write_text("import sys")

        exit_code = main(["check", str(test_file), "--config", str(config_file)])
        assert exit_code in (0, 1)

    def test_cli_no_subcommand_shows_help(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test: No subcommand shows help."""
        exit_code = main([])
        assert exit_code == 0

        captured = capsys.readouterr()
        # Should show help or usage
        assert "minport" in captured.out or len(captured.out) > 0

    def test_cli_check_subcommand(self, tmp_path: Path) -> None:
        """Test: check subcommand works."""
        test_file = tmp_path / "test.py"
        test_file.write_text("import sys")

        exit_code = main(["check", str(test_file)])
        assert exit_code == 0

    def test_cli_multiple_paths(self, tmp_path: Path) -> None:
        """Test: Multiple paths can be checked."""
        test1 = tmp_path / "test1.py"
        test1.write_text("import sys")

        test2 = tmp_path / "test2.py"
        test2.write_text("import os")

        exit_code = main(["check", str(test1), str(test2)])
        assert exit_code == 0

    def test_cli_default_path_is_current_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test: Default path is current directory."""
        monkeypatch.chdir(tmp_path)

        test_file = tmp_path / "test.py"
        test_file.write_text("import sys")

        exit_code = main(["check"])
        assert exit_code == 0

    def test_cli_output_format_text(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test: Text output format shows violations."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        sub = pkg / "sub"
        sub.mkdir()

        (pkg / "__init__.py").write_text("from .sub.module import Name")
        (sub / "__init__.py").write_text("from .module import Name")
        (sub / "module.py").write_text("Name = 1")

        test_file = tmp_path / "test.py"
        test_file.write_text("from pkg.sub.module import Name")

        exit_code = main(["check", str(test_file), "--src", str(tmp_path)])
        captured = capsys.readouterr()

        # Should mention the violation
        if exit_code == 1:
            assert "MP001" in captured.out or "can be shortened" in captured.out

    def test_cli_fix_output_shows_fixes_applied(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test: Fix output shows how many fixes were applied."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        sub = pkg / "sub"
        sub.mkdir()

        (pkg / "__init__.py").write_text("")
        (sub / "__init__.py").write_text("from .module import Name")
        (sub / "module.py").write_text("Name = 1")

        test_file = tmp_path / "test.py"
        # Import from deeper level that can be shortened
        test_file.write_text("from pkg.sub.module import Name")

        exit_code = main(["check", str(test_file), "--fix", "--src", str(tmp_path)])
        captured = capsys.readouterr()

        assert exit_code == 1
        assert "fixed 1 in 1 file" in captured.out

    def test_cli_with_invalid_toml(self, tmp_path: Path) -> None:
        """Test: Invalid TOML config file is skipped."""
        config_file = tmp_path / "pyproject.toml"
        config_file.write_text("this is not valid toml !!!")

        test_file = tmp_path / "test.py"
        test_file.write_text("import sys")

        # Should not crash, should handle gracefully
        exit_code = main(["check", str(test_file), "--config", str(config_file)])
        assert exit_code == 0

    def test_cli_config_with_invalid_type_for_src(self, tmp_path: Path) -> None:
        """Test: Config with non-string src value is handled."""
        config_file = tmp_path / "pyproject.toml"
        config_file.write_text('[tool.minport]\nsrc = [123, "valid"]')

        test_file = tmp_path / "test.py"
        test_file.write_text("import sys")

        # Should not crash, should use default
        exit_code = main(["check", str(test_file), "--config", str(config_file)])
        assert exit_code == 0

    def test_cli_config_with_tool_not_dict(self, tmp_path: Path) -> None:
        """Test: Config where [tool] is not a dict is handled."""
        config_file = tmp_path / "pyproject.toml"
        config_file.write_text('tool = "string"')

        test_file = tmp_path / "test.py"
        test_file.write_text("import sys")

        # Should not crash, should use default
        exit_code = main(["check", str(test_file), "--config", str(config_file)])
        assert exit_code == 0

    def test_cli_config_with_minport_not_dict(self, tmp_path: Path) -> None:
        """Test: Config where [tool.minport] is not a dict is handled."""
        config_file = tmp_path / "pyproject.toml"
        config_file.write_text('[tool]\nminport = "string"')

        test_file = tmp_path / "test.py"
        test_file.write_text("import sys")

        # Should not crash, should use default
        exit_code = main(["check", str(test_file), "--config", str(config_file)])
        assert exit_code == 0

    def test_summary_shown_when_no_violations(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Summary line is emitted even when no violations are found."""
        test_file = tmp_path / "test.py"
        test_file.write_text("import sys\n")

        exit_code = main(["check", str(test_file)])
        captured = capsys.readouterr()

        assert exit_code == 0
        assert "Found 0 errors" in captured.out
        assert "checked 1 file" in captured.out

    def test_summary_shown_when_no_python_files(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Summary distinguishes 'no files walked' from 'no violations'."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        exit_code = main(["check", str(empty_dir)])
        captured = capsys.readouterr()

        assert exit_code == 0
        assert "Found 0 errors" in captured.out
        assert "checked 0 files" in captured.out

    def test_summary_includes_checked_count_when_violations(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Summary includes the checked-files count even when violations exist."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        sub = pkg / "sub"
        sub.mkdir()

        (pkg / "__init__.py").write_text("")
        (sub / "__init__.py").write_text("from .module import Name\n")
        (sub / "module.py").write_text("Name = 1\n")

        test_file = tmp_path / "test.py"
        test_file.write_text("from pkg.sub.module import Name\n")

        exit_code = main(["check", str(test_file), "--src", str(tmp_path)])
        captured = capsys.readouterr()

        assert exit_code == 1
        assert "checked 1 file" in captured.out

    def test_quiet_suppresses_summary_when_clean(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """--quiet suppresses the summary line on a clean run."""
        test_file = tmp_path / "test.py"
        test_file.write_text("import sys\n")

        exit_code = main(["check", str(test_file), "--quiet"])
        captured = capsys.readouterr()

        assert exit_code == 0
        assert captured.out == ""

    def test_quiet_still_prints_violations(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """--quiet suppresses the summary but still prints per-violation lines."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        sub = pkg / "sub"
        sub.mkdir()

        (pkg / "__init__.py").write_text("")
        (sub / "__init__.py").write_text("from .module import Name\n")
        (sub / "module.py").write_text("Name = 1\n")

        test_file = tmp_path / "test.py"
        test_file.write_text("from pkg.sub.module import Name\n")

        exit_code = main(["check", str(test_file), "--quiet", "--src", str(tmp_path)])
        captured = capsys.readouterr()

        assert exit_code == 1
        assert "MP001" in captured.out
        assert "Found" not in captured.out

    def test_cli_default_paths_from_config(self, tmp_path: Path, monkeypatch) -> None:
        """Test: Default paths from config are used when no paths specified."""
        config_file = tmp_path / "pyproject.toml"
        config_file.write_text('[tool.minport]\nsrc = ["."]')

        test_file = tmp_path / "test.py"
        test_file.write_text("import sys")

        monkeypatch.chdir(tmp_path)
        exit_code = main(["check", "--config", str(config_file)])
        assert exit_code == 0

    def test_extend_exclude_cli(self, tmp_path: Path) -> None:
        """--extend-exclude adds patterns to the exclude list."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        sub = pkg / "sub"
        sub.mkdir()

        (pkg / "__init__.py").write_text("")
        (sub / "__init__.py").write_text("from .module import Name")
        (sub / "module.py").write_text("Name = 1")

        kept = tmp_path / "kept.py"
        kept.write_text("from pkg.sub.module import Name")
        skipped = tmp_path / "skipped.py"
        skipped.write_text("from pkg.sub.module import Name")

        exit_code = main(
            [
                "check",
                str(tmp_path),
                "--extend-exclude",
                "skipped.py",
                "--src",
                str(tmp_path),
            ]
        )
        assert exit_code == 1

    def test_extend_exclude_from_pyproject(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """extend-exclude in pyproject.toml adds patterns to the exclude list."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        sub = pkg / "sub"
        sub.mkdir()

        (pkg / "__init__.py").write_text("")
        (sub / "__init__.py").write_text("from .module import Name")
        (sub / "module.py").write_text("Name = 1")

        kept = tmp_path / "kept.py"
        kept.write_text("from pkg.sub.module import Name")
        skipped = tmp_path / "gen_file.py"
        skipped.write_text("from pkg.sub.module import Name")

        config_file = tmp_path / "pyproject.toml"
        config_file.write_text('[tool.minport]\nextend-exclude = ["gen_file.py"]\n')

        exit_code = main(
            [
                "check",
                str(tmp_path),
                "--config",
                str(config_file),
                "--src",
                str(tmp_path),
            ]
        )
        captured = capsys.readouterr()

        assert exit_code == 1
        assert "gen_file.py" not in captured.out

    def test_output_format_github_violations(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """--output-format github で ::error 形式が出力される。"""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        sub = pkg / "sub"
        sub.mkdir()

        (pkg / "__init__.py").write_text("")
        (sub / "__init__.py").write_text("from .module import Name\n")
        (sub / "module.py").write_text("Name = 1\n")

        test_file = tmp_path / "test.py"
        test_file.write_text("from pkg.sub.module import Name\n")

        exit_code = main(
            ["check", str(test_file), "--output-format", "github", "--src", str(tmp_path)]
        )
        captured = capsys.readouterr()

        assert exit_code == 1
        assert "::error " in captured.out
        assert "file=" in captured.out
        assert "title=MP001" in captured.out
        assert "can be shortened" in captured.out

    def test_output_format_github_no_summary(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """--output-format github はサマリを出力しない。"""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        sub = pkg / "sub"
        sub.mkdir()

        (pkg / "__init__.py").write_text("")
        (sub / "__init__.py").write_text("from .module import Name\n")
        (sub / "module.py").write_text("Name = 1\n")

        test_file = tmp_path / "test.py"
        test_file.write_text("from pkg.sub.module import Name\n")

        exit_code = main(
            ["check", str(test_file), "--output-format", "github", "--src", str(tmp_path)]
        )
        captured = capsys.readouterr()

        assert exit_code == 1
        assert "::error " in captured.out
        assert "Found" not in captured.out

    def test_output_format_github_no_violations_silent(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """--output-format github は違反なしのとき何も出力しない。"""
        test_file = tmp_path / "test.py"
        test_file.write_text("import sys\n")

        exit_code = main(["check", str(test_file), "--output-format", "github"])
        captured = capsys.readouterr()

        assert exit_code == 0
        assert captured.out == ""

    def test_output_format_default_is_text(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """--output-format 未指定時は text フォーマット(既存動作を維持)。"""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        sub = pkg / "sub"
        sub.mkdir()

        (pkg / "__init__.py").write_text("")
        (sub / "__init__.py").write_text("from .module import Name\n")
        (sub / "module.py").write_text("Name = 1\n")

        test_file = tmp_path / "test.py"
        test_file.write_text("from pkg.sub.module import Name\n")

        exit_code = main(["check", str(test_file), "--src", str(tmp_path)])
        captured = capsys.readouterr()

        assert exit_code == 1
        assert "::error " not in captured.out
        assert "MP001" in captured.out

    def test_extend_exclude_merges_with_exclude(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """exclude and extend-exclude are merged together."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        sub = pkg / "sub"
        sub.mkdir()

        (pkg / "__init__.py").write_text("")
        (sub / "__init__.py").write_text("from .module import Name")
        (sub / "module.py").write_text("Name = 1")

        (tmp_path / "a.py").write_text("from pkg.sub.module import Name")
        (tmp_path / "b.py").write_text("from pkg.sub.module import Name")
        (tmp_path / "c.py").write_text("from pkg.sub.module import Name")

        exit_code = main(
            [
                "check",
                str(tmp_path),
                "--exclude",
                "a.py",
                "--extend-exclude",
                "b.py",
                "--src",
                str(tmp_path),
            ]
        )
        captured = capsys.readouterr()

        assert exit_code == 1
        assert "a.py" not in captured.out
        assert "b.py" not in captured.out
        assert "c.py" in captured.out
