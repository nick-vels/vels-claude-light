"""Tests for JSON session storage."""
from __future__ import annotations

from pathlib import Path

from src.storage import Storage


async def test_get_session_missing_returns_none(tmp_sessions_file: Path) -> None:
    storage = Storage(tmp_sessions_file)
    assert await storage.get_session(42) is None


async def test_set_and_get_session(tmp_sessions_file: Path) -> None:
    storage = Storage(tmp_sessions_file)
    await storage.set_session(42, "session-abc")
    session = await storage.get_session(42)
    assert session is not None
    assert session["session_id"] == "session-abc"
    assert session["message_count"] == 0


async def test_bump_message_count(tmp_sessions_file: Path) -> None:
    storage = Storage(tmp_sessions_file)
    await storage.set_session(42, "s1")
    await storage.bump_message_count(42)
    await storage.bump_message_count(42)
    session = await storage.get_session(42)
    assert session["message_count"] == 2


async def test_clear_session(tmp_sessions_file: Path) -> None:
    storage = Storage(tmp_sessions_file)
    await storage.set_session(42, "s1")
    await storage.clear_session(42)
    assert await storage.get_session(42) is None


async def test_persistence_across_instances(tmp_sessions_file: Path) -> None:
    s1 = Storage(tmp_sessions_file)
    await s1.set_session(42, "abc")
    s2 = Storage(tmp_sessions_file)
    session = await s2.get_session(42)
    assert session["session_id"] == "abc"


async def test_atomic_write_leaves_no_temp_files(tmp_sessions_file: Path) -> None:
    storage = Storage(tmp_sessions_file)
    await storage.set_session(42, "abc")
    # Temp file from atomic rename must not linger
    temp_files = list(tmp_sessions_file.parent.glob("*.tmp"))
    assert temp_files == []
