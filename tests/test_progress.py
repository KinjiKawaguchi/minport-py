"""Tests for the stderr progress reporter."""

from __future__ import annotations

import io
import re
from pathlib import Path
from typing import TYPE_CHECKING

from minport._progress import ProgressReporter, ProgressTracker, _default_terminal_width
from minport.cli import main

if TYPE_CHECKING:
    import pytest


_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def _strip_ansi(s: str) -> str:
    return _ANSI_RE.sub("", s)


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


def _reporter(
    stream: _FakeTTY,
    *,
    clock: _FakeClock | None = None,
    width: int = 80,
    color: bool = False,
) -> ProgressReporter:
    return ProgressReporter(
        stream=stream,
        enabled=True,
        now=clock if clock is not None else _FakeClock([0.0] * 32),
        color=color,
        terminal_width=lambda: width,
    )


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
        reporter = _reporter(stream)
        reporter.update(0, 0)
        reporter.close()
        assert stream.getvalue() == ""

    def test_first_update_hides_cursor_and_renders_line(self) -> None:
        stream = _FakeTTY()
        clock = _FakeClock([0.0, 0.5])  # init, first update
        reporter = _reporter(stream, clock=clock)
        reporter.update(1, 5)
        out = stream.getvalue()
        assert "\x1b[?25l" in out  # cursor hidden
        assert "\x1b[2K\r" in out  # line cleared
        plain = _strip_ansi(out)
        assert "1/5" in plain
        assert "20%" in plain
        assert "0.5s" in plain

    def test_throttle_drops_rapid_intermediate_updates(self) -> None:
        stream = _FakeTTY()
        # init=0, then first update emits, second throttled, third final (always emits)
        clock = _FakeClock([0.0, 0.0, 0.05, 0.05])
        reporter = _reporter(stream, clock=clock)
        reporter.update(1, 10)
        before_throttle = stream.getvalue()
        reporter.update(2, 10)
        after_throttle = stream.getvalue()
        reporter.update(10, 10)
        after_final = stream.getvalue()
        plain_first = _strip_ansi(before_throttle)
        assert "1/10" in plain_first
        assert after_throttle == before_throttle  # second was throttled
        plain_final = _strip_ansi(after_final)
        assert "10/10" in plain_final

    def test_final_update_always_emits_even_when_throttled(self) -> None:
        stream = _FakeTTY()
        clock = _FakeClock([0.0, 0.0, 0.01])
        reporter = _reporter(stream, clock=clock)
        reporter.update(1, 2)
        before = stream.getvalue()
        reporter.update(2, 2)
        after = stream.getvalue()
        assert after != before
        assert "2/2" in _strip_ansi(after)

    def test_close_clears_line_and_restores_cursor(self) -> None:
        stream = _FakeTTY()
        clock = _FakeClock([0.0, 0.0])
        reporter = _reporter(stream, clock=clock)
        reporter.update(1, 1)
        reporter.close()
        out = stream.getvalue()
        assert out.endswith("\x1b[?25h")  # cursor restored last
        assert out.count("\x1b[2K\r") >= 2  # cleared during update + on close

    def test_close_without_any_update_is_safe_noop(self) -> None:
        stream = _FakeTTY()
        reporter = _reporter(stream)
        reporter.close()
        # Cursor was never hidden, so no show-cursor either.
        assert "\x1b[?25h" not in stream.getvalue()

    def test_spinner_advances_between_updates(self) -> None:
        stream = _FakeTTY()
        clock = _FakeClock([0.0, 0.0, 0.5, 1.0])
        reporter = _reporter(stream, clock=clock, width=120)
        reporter.update(1, 100)
        reporter.update(2, 100)
        plain = _strip_ansi(stream.getvalue())
        # Two distinct spinner glyphs at the start of each rendered frame
        frames = [seg for seg in plain.split("\r") if seg.strip()]
        glyphs = {f[0] for f in frames if f}
        assert len(glyphs) == 2

    def test_progress_bar_appears_when_terminal_is_wide_enough(self) -> None:
        stream = _FakeTTY()
        clock = _FakeClock([0.0, 0.0])
        reporter = _reporter(stream, clock=clock, width=80)
        reporter.update(50, 100)
        plain = _strip_ansi(stream.getvalue())
        assert "█" in plain
        assert "░" in plain
        assert "[" in plain
        assert "]" in plain

    def test_progress_bar_dropped_when_terminal_is_narrow(self) -> None:
        stream = _FakeTTY()
        clock = _FakeClock([0.0, 0.0])
        reporter = _reporter(stream, clock=clock, width=20)
        reporter.update(50, 100)
        plain = _strip_ansi(stream.getvalue())
        assert "█" not in plain
        assert "[" not in plain
        # Counts and elapsed still rendered
        assert "50/100" in plain

    def test_color_codes_emitted_when_color_enabled(self) -> None:
        stream = _FakeTTY()
        clock = _FakeClock([0.0, 0.0])
        reporter = _reporter(stream, clock=clock, color=True)
        reporter.update(50, 100)
        out = stream.getvalue()
        assert "\x1b[36m" in out  # cyan spinner
        assert "\x1b[1m" in out  # bold counts
        assert "\x1b[2m" in out  # dim suffix
        assert "\x1b[32m" in out  # green filled bar

    def test_no_color_env_disables_color(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NO_COLOR", "1")
        stream = _FakeTTY()
        reporter = ProgressReporter(
            stream=stream,
            enabled=True,
            now=_FakeClock([0.0, 0.0]),
            terminal_width=lambda: 80,
        )
        reporter.update(50, 100)
        assert "\x1b[36m" not in stream.getvalue()
        assert "\x1b[32m" not in stream.getvalue()


class TestDefaultTerminalWidth:
    def test_returns_positive_int(self) -> None:
        width = _default_terminal_width()
        assert isinstance(width, int)
        assert width > 0


class TestElapsedFormatting:
    def test_sub_minute_uses_seconds_with_decimal(self) -> None:
        assert ProgressReporter._format_elapsed(0.0) == "0.0s"
        assert ProgressReporter._format_elapsed(12.345) == "12.3s"
        assert ProgressReporter._format_elapsed(59.9) == "59.9s"

    def test_minute_or_more_switches_to_mmss(self) -> None:
        assert ProgressReporter._format_elapsed(60.0) == "1m00s"
        assert ProgressReporter._format_elapsed(125.0) == "2m05s"
        assert ProgressReporter._format_elapsed(3599.0) == "59m59s"

    def test_hour_or_more_switches_to_hhmm(self) -> None:
        assert ProgressReporter._format_elapsed(3600.0) == "1h00m"
        assert ProgressReporter._format_elapsed(7325.0) == "2h02m"


class TestProgressTracker:
    def _calls(self) -> tuple[list[tuple[int, int]], object]:
        seen: list[tuple[int, int]] = []

        def cb(completed: int, total: int) -> None:
            seen.append((completed, total))

        return seen, cb

    def test_start_emits_initial_zero_over_user_total(self) -> None:
        seen, cb = self._calls()
        tracker = ProgressTracker(cb, [Path("a.py"), Path("b.py")])
        tracker.start()
        assert seen == [(0, 2)]

    def test_advance_user_increments_numerator(self) -> None:
        seen, cb = self._calls()
        tracker = ProgressTracker(cb, [Path("a.py"), Path("b.py")])
        tracker.start()
        tracker.advance_user()
        tracker.advance_user()
        assert seen[-1] == (2, 2)

    def test_resolver_parse_grows_total_for_non_user_files(self) -> None:
        seen, cb = self._calls()
        tracker = ProgressTracker(cb, [Path("a.py")])
        tracker.start()
        tracker.file_parsed_by_resolver(Path("/site-packages/numpy/__init__.py"))
        tracker.file_parsed_by_resolver(Path("/site-packages/numpy/core.py"))
        # numerator unchanged, denominator grew by 2
        assert seen[-1] == (0, 3)

    def test_resolver_parse_skips_user_files(self) -> None:
        seen, cb = self._calls()
        user = Path("a.py")
        tracker = ProgressTracker(cb, [user])
        tracker.start()
        tracker.file_parsed_by_resolver(user)
        # Only the start() emit; user-file parses do not re-emit.
        assert seen == [(0, 1)]


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
        target = self._make_violation_tree(tmp_path)
        exit_code = main(["check", str(target), "--src", str(tmp_path)])
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "1/1" not in _strip_ansi(captured.err)

    def test_quiet_suppresses_progress_even_on_tty(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        target = self._make_violation_tree(tmp_path)
        monkeypatch.setattr("sys.stderr.isatty", lambda: True, raising=False)
        exit_code = main(["check", str(target), "--src", str(tmp_path), "--quiet"])
        captured = capsys.readouterr()
        assert exit_code == 1
        assert captured.err == ""

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
        assert captured.err == ""
        assert "::error " in captured.out
