r"""stderr progress reporter for ``minport check``.

Renders ``checked N/M files (Xs elapsed)`` on a single line via ``\r``.
No-op when disabled (``--quiet`` / non-TTY / GitHub output / zero files).
Throttles updates to ~10Hz so large file counts do not flood stderr.
"""

from __future__ import annotations

import time
from typing import IO, TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable


class ProgressCallback(Protocol):
    """Per-file progress hook injected into :func:`minport.checker.check`."""

    def __call__(self, completed: int, total: int) -> None: ...


class ProgressReporter:
    """Single-line stderr progress reporter."""

    _MIN_INTERVAL_SEC = 0.1  # ~10Hz

    def __init__(
        self,
        *,
        stream: IO[str],
        enabled: bool,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._stream = stream
        self._enabled = enabled
        self._now = now
        self._start = self._now()
        self._last_emit = float("-inf")
        self._last_line_len = 0

    def update(self, completed: int, total: int) -> None:
        """Render the progress line for the current ``completed``/``total``."""
        if not self._enabled or total <= 0:
            return
        now = self._now()
        is_final = completed >= total
        if not is_final and (now - self._last_emit) < self._MIN_INTERVAL_SEC:
            return
        self._last_emit = now
        elapsed = now - self._start
        line = f"checked {completed}/{total} files ({elapsed:.1f}s elapsed)"
        pad = max(0, self._last_line_len - len(line))
        self._stream.write(f"\r{line}{' ' * pad}")
        self._stream.flush()
        self._last_line_len = len(line)

    def close(self) -> None:
        """Clear the progress line so subsequent output starts clean."""
        if not self._enabled or self._last_line_len == 0:
            return
        self._stream.write("\r" + " " * self._last_line_len + "\r")
        self._stream.flush()
        self._last_line_len = 0
