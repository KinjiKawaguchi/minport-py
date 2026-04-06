"""Shared fixtures for minport tests."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


@pytest.fixture
def tmp_package(tmp_path: Path) -> Path:
    """Create a minimal package structure for testing."""
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    return pkg


@pytest.fixture
def sample_ast() -> ast.Module:
    """Return a parsed empty module."""
    return ast.parse("")
