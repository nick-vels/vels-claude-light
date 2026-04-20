"""Shared pytest fixtures."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def tmp_sessions_file(tmp_path: Path) -> Path:
    """Return a path to a not-yet-created sessions.json inside a tmp dir."""
    return tmp_path / "sessions.json"
