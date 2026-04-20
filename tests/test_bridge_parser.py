"""Tests for the Claude CLI stream-json parser."""
from __future__ import annotations

import json

from src.bridge import EventType, parse_event


def _j(obj: dict) -> str:
    return json.dumps(obj)


def test_parse_init_extracts_session_id() -> None:
    raw = _j({"type": "system", "subtype": "init", "session_id": "abc-123"})
    ev = parse_event(raw)
    assert ev is not None
    assert ev.type == EventType.INIT
    assert ev.metadata == {"session_id": "abc-123"}


def test_parse_text_delta() -> None:
    raw = _j({
        "type": "stream_event",
        "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "hello"}},
    })
    ev = parse_event(raw)
    assert ev is not None
    assert ev.type == EventType.TEXT
    assert ev.text == "hello"


def test_parse_non_text_delta_ignored() -> None:
    raw = _j({
        "type": "stream_event",
        "event": {"type": "content_block_start", "content_block": {"type": "tool_use"}},
    })
    assert parse_event(raw) is None


def test_parse_tool_use() -> None:
    raw = _j({
        "type": "assistant",
        "message": {
            "content": [{"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}]
        },
    })
    ev = parse_event(raw)
    # Full assistant events are ignored (text is duplicated from text_delta);
    # tool_use inside is a separate event we emit for the timer's tool counter.
    assert ev is not None
    assert ev.type == EventType.TOOL_USE
    assert ev.text == "Bash"


def test_parse_result_with_usage() -> None:
    raw = _j({
        "type": "result",
        "result": "done",
        "session_id": "abc-123",
        "usage": {"input_tokens": 100, "output_tokens": 50},
        "total_cost_usd": 0.012,
    })
    ev = parse_event(raw)
    assert ev is not None
    assert ev.type == EventType.RESULT
    assert ev.metadata["session_id"] == "abc-123"
    assert ev.metadata["usage"]["input_tokens"] == 100


def test_parse_malformed_json_returns_none() -> None:
    assert parse_event("not json at all") is None


def test_parse_empty_line_returns_none() -> None:
    assert parse_event("") is None
    assert parse_event("   ") is None


# ---------------------------------------------------------------------------
# classify_error tests
# ---------------------------------------------------------------------------

from src.bridge import (  # noqa: E402
    AuthError,
    ClaudeError,
    ContextOverflow,
    RateLimit,
    classify_error,
)


def test_classify_rate_limit() -> None:
    err = classify_error(1, "429 too many requests")
    assert isinstance(err, RateLimit)


def test_classify_context_overflow() -> None:
    err = classify_error(1, "prompt is too long (exceeds maximum 200000)")
    assert isinstance(err, ContextOverflow)


def test_classify_auth() -> None:
    err = classify_error(1, "401 Unauthorized")
    assert isinstance(err, AuthError)


def test_classify_unknown_falls_back_to_base() -> None:
    err = classify_error(2, "something weird")
    assert isinstance(err, ClaudeError)
    assert not isinstance(err, (RateLimit, ContextOverflow, AuthError))
