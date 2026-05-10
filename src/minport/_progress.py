r"""stderr progress reporter for ``minport check``.

Renders an animated single-line progress display:

    ⠋ [████████░░░░░░░░] 250/500 · 50% · 1.2s

- Hides the cursor while active (restored on close).
- Spinner uses braille frames and advances per emit.
- Throttles updates to ~10Hz, except the final update which always emits.
- Bar width adapts to the terminal; the bar is dropped when too narrow.
- Honors ``NO_COLOR`` (https://no-color.org/) by suppressing ANSI color codes.
- No-op when disabled (``--quiet`` / non-TTY / GitHub output / zero files).
"""

from __future__ import annotations

import os
import shutil
import time
from typing import IO, TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable


_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
_HIDE_CURSOR = "\x1b[?25l"
_SHOW_CURSOR = "\x1b[?25h"
_CLEAR_LINE = "\x1b[2K\r"

_DIM = "\x1b[2m"
_BOLD = "\x1b[1m"
_CYAN = "\x1b[36m"
_GREEN = "\x1b[32m"
_RESET = "\x1b[0m"

# Visible characters that frame the bar / separators / spinner+space.
_BAR_CHROME_COLS = 2  # "[" and "]"
_SPINNER_COLS = 2  # spinner glyph + trailing space
_MIN_BAR_WIDTH = 4  # below this, drop the bar entirely


class ProgressCallback(Protocol):
    """Per-file progress hook injected into :func:`minport.checker.check`."""

    def __call__(self, completed: int, total: int) -> None: ...


class ProgressReporter:
    """Animated single-line stderr progress reporter."""

    _MIN_INTERVAL_SEC = 0.1  # ~10Hz

    def __init__(
        self,
        *,
        stream: IO[str],
        enabled: bool,
        now: Callable[[], float] = time.monotonic,
        color: bool | None = None,
        terminal_width: Callable[[], int] | None = None,
    ) -> None:
        self._stream = stream
        self._enabled = enabled
        self._now = now
        self._start = self._now()
        self._last_emit = float("-inf")
        self._spinner_index = 0
        self._cursor_hidden = False
        if color is None:
            color = enabled and not os.environ.get("NO_COLOR")
        self._color = color
        self._term_width = terminal_width or _default_terminal_width

    def update(self, completed: int, total: int) -> None:
        """Render progress for ``completed``/``total`` if not throttled."""
        if not self._enabled or total <= 0:
            return
        now = self._now()
        is_final = completed >= total
        if not is_final and (now - self._last_emit) < self._MIN_INTERVAL_SEC:
            return
        self._last_emit = now

        if not self._cursor_hidden:
            self._stream.write(_HIDE_CURSOR)
            self._cursor_hidden = True

        elapsed = now - self._start
        line = self._render(completed, total, elapsed)
        self._stream.write(_CLEAR_LINE + line)
        self._stream.flush()

        self._spinner_index = (self._spinner_index + 1) % len(_SPINNER_FRAMES)

    def close(self) -> None:
        """Clear the progress line and restore the cursor."""
        if not self._enabled or not self._cursor_hidden:
            return
        self._stream.write(_CLEAR_LINE + _SHOW_CURSOR)
        self._stream.flush()
        self._cursor_hidden = False

    def _render(self, completed: int, total: int, elapsed: float) -> str:
        spinner = _SPINNER_FRAMES[self._spinner_index]
        clamped = min(max(completed, 0), total)
        percent = int(clamped * 100 / total)
        counts = f"{clamped}/{total}"
        elapsed_s = f"{elapsed:.1f}s"

        sp = self._paint(spinner, _CYAN)
        counts_c = self._paint(counts, _BOLD)
        sep = self._paint("·", _DIM)
        pct_c = self._paint(f"{percent}%", _DIM)
        elapsed_c = self._paint(elapsed_s, _DIM)
        suffix = f" {counts_c} {sep} {pct_c} {sep} {elapsed_c}"

        raw_suffix_cols = len(f" {counts} · {percent}% · {elapsed_s}")
        width = self._term_width()
        bar_width = width - _SPINNER_COLS - _BAR_CHROME_COLS - raw_suffix_cols
        if bar_width < _MIN_BAR_WIDTH:
            return f"{sp}{suffix}"

        filled = int(bar_width * clamped / total)
        empty = bar_width - filled
        bar_inner = self._paint("█" * filled, _GREEN) + self._paint("░" * empty, _DIM)
        return f"{sp} [{bar_inner}]{suffix}"

    def _paint(self, text: str, code: str) -> str:
        if not self._color:
            return text
        return f"{code}{text}{_RESET}"


def _default_terminal_width() -> int:
    return shutil.get_terminal_size((80, 24)).columns
