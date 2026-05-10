"""Tests for the stderr progress reporter."""

from __future__ import annotations

import io
from typing import TYPE_CHECKING

from minport._progress import ProgressReporter
from minport.cli import main

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


class _FakeTTY(io.StringIO):
    """StringIO that pretends to be a TTY."""

    def isatty(self) -> bool:
        return True


class _FakeClock:
    """Monotonic clock stub returning user-supplied values in order."""

    def __init__(self, values: list[float]) -> None:
        self._values = list(values)
        self._last = values[0] if values else 0.0

    def __call__(self) -> float:
        if self._values:
            self._last = self._values.pop(0)
        return self._last


class TestProgressReporter:
    def test_disabled_writes_nothing(self) -> None:
        stream = _FakeTTY()
        reporter = ProgressReporter(stream=stream, enabled=False)
        reporter.update(1, 10)
        reporter.update(10, 10)
        reporter.close()
        assert stream.getvalue() == ""

    def test_zero_total_writes_nothing(self) -> None:
        stream = _FakeTTY()
        reporter = ProgressReporter(stream=stream, enabled=True)
        reporter.update(0, 0)
        reporter.close()
        assert stream.getvalue() == ""

    def test_first_update_emits_carriage_return_line(self) -> None:
        stream = _FakeTTY()
        clock = _FakeClock([0.0, 0.5])  # start, first update
        reporter = ProgressReporter(stream=stream, enabled=True, now=clock)
        reporter.update(1, 5)
        out = stream.getvalue()
        assert out.startswith("\r")
        assert "checked 1/5 files" in out
        assert "0.5s elapsed" in out

    def test_throttle_drops_rapid_intermediate_updates(self) -> None:
        stream = _FakeTTY()
        # start=0, then first update emits, second throttled, third is final (always).
        clock = _FakeClock([0.0, 0.0, 0.05, 0.05])
        reporter = ProgressReporter(stream=stream, enabled=True, now=clock)
        reporter.update(1, 10)
        first = stream.getvalue()
        reporter.update(2, 10)
        second = stream.getvalue()
        reporter.update(10, 10)
        third = stream.getvalue()
        assert "checked 1/10" in first
        assert second == first  # throttled
        assert "checked 10/10" in third

    def test_final_update_always_emits(self) -> None:
        stream = _FakeTTY()
        clock = _FakeClock([0.0, 0.0, 0.01])
        reporter = ProgressReporter(stream=stream, enabled=True, now=clock)
        reporter.update(1, 2)
        before = stream.getvalue()
        reporter.update(2, 2)
        after = stream.getvalue()
        # Even within throttle window, the final update emits.
        assert after != before
        assert "checked 2/2" in after

    def test_close_clears_line(self) -> None:
        stream = _FakeTTY()
        clock = _FakeClock([0.0, 0.0])
        reporter = ProgressReporter(stream=stream, enabled=True, now=clock)
        reporter.update(1, 1)
        reporter.close()
        out = stream.getvalue()
        # Last write must be a clearing sequence: "\r" + spaces + "\r".
        assert out.endswith("\r")
        # The clear segment must be at least as long as the last line so terminal is wiped.
        cleared_segment = out.rsplit("\r", 2)[1]
        assert cleared_segment.strip() == ""

class TestProgressInCLI:
    """Behavioral tests against the real `minport check` CLI."""

    def _make_violation_tree(self, root: Path) -> Path:
        pkg = root / "pkg"
        pkg.mkdir()
        sub = pkg / "sub"
        sub.mkdir()
        (pkg / "__init__.py").write_text("")
        (sub / "__init__.py").write_text("from .module import Name\n")
        (sub / "module.py").write_text("Name = 1\n")
        target = root / "test.py"
        target.write_text("from pkg.sub.module import Name\n")
        return target

    def test_progress_not_emitted_when_stderr_is_not_tty(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Default capsys stderr is non-TTY → no progress output."""
        target = self._make_violation_tree(tmp_path)
        exit_code = main(["check", str(target), "--src", str(tmp_path)])
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "checked 1/1" not in captured.err

    def test_quiet_suppresses_progress_even_on_tty(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        target = self._make_violation_tree(tmp_path)
        # Force stderr.isatty() to return True without actually re-binding the stream.
        monkeypatch.setattr("sys.stderr.isatty", lambda: True, raising=False)
        exit_code = main(["check", str(target), "--src", str(tmp_path), "--quiet"])
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "checked" not in captured.err

    def test_github_format_suppresses_progress(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        target = self._make_violation_tree(tmp_path)
        monkeypatch.setattr("sys.stderr.isatty", lambda: True, raising=False)
        exit_code = main(
            [
                "check",
                str(target),
                "--src",
                str(tmp_path),
                "--output-format",
                "github",
            ],
        )
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "checked" not in captured.err
        # GitHub annotations must remain on stdout untouched.
        assert "::error " in captured.out
