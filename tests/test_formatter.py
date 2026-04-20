"""Smoke tests for the markdown → Telegram-HTML formatter."""
from __future__ import annotations

from src.formatter import format_for_telegram, strip_html_tags


def test_plain_text_passthrough() -> None:
    assert format_for_telegram("hello world") == "hello world"


def test_inline_code() -> None:
    html = format_for_telegram("use `ls -la` here")
    assert "<code>ls -la</code>" in html


def test_fenced_code_block() -> None:
    html = format_for_telegram("```python\nprint('hi')\n```")
    assert "<pre>" in html or "<code>" in html
    assert "print" in html


def test_bold_and_italic() -> None:
    html = format_for_telegram("**bold** and *italic*")
    assert "<b>" in html
    assert "<i>" in html


def test_strip_html_tags_removes_tags() -> None:
    assert strip_html_tags("<b>hi</b>") == "hi"
