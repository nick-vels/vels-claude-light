"""Bridge to Claude Code CLI.

Responsible for:
- Locating the Claude CLI binary (VS Code extension preferred, fallback to PATH).
- Cleaning proxy env vars so VPN works at the OS level while the SDK sees no proxy.
- Spawning ``claude -p --output-format stream-json --include-partial-messages``.
- Parsing the newline-delimited JSON events it emits.
- Classifying errors into actionable categories.
"""
from __future__ import annotations

import glob
import json
import os
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path


class ClaudeBinaryNotFound(RuntimeError):
    """Raised when no Claude CLI binary can be located."""


def resolve_claude_binary(config_value: str) -> str:
    """Resolve the Claude CLI binary.

    - If *config_value* is ``auto``: look in the VS Code extension, then PATH.
    - Otherwise: treat *config_value* as an explicit path; error if missing.
    """
    if config_value and config_value != "auto":
        path = Path(config_value).expanduser()
        if not path.exists():
            raise ClaudeBinaryNotFound(f"CLAUDE_BINARY={config_value} does not exist")
        return str(path)

    # VS Code extension native binary
    home = Path.home()
    ext_base = ".vscode/extensions"
    native = "resources/native-binary/claude"
    patterns = [
        str(home / ext_base / "anthropic.claude-code-*-darwin-arm64" / native),
        str(home / ext_base / "anthropic.claude-code-*-darwin-x64" / native),
        str(home / ext_base / "anthropic.claude-code-*-linux-x64" / native),
    ]
    for pattern in patterns:
        matches = sorted(glob.glob(pattern), reverse=True)  # newest version first
        if matches:
            return matches[0]

    # PATH fallback
    from shutil import which

    path_binary = which("claude")
    if path_binary:
        return path_binary

    raise ClaudeBinaryNotFound(
        "Claude CLI not found. Install via `npm install -g @anthropic-ai/claude-code` "
        "or set CLAUDE_BINARY to an absolute path."
    )


_PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "CLAUDECODE")


def build_subprocess_env() -> dict[str, str]:
    """Copy of os.environ with proxy vars removed.

    The bot talks to Telegram through a system VPN while the Claude CLI uses the
    Anthropic API directly; inherited proxy env vars break SDK handshakes.
    """
    env = os.environ.copy()
    for key in _PROXY_VARS:
        env.pop(key, None)
    return env


class EventType(Enum):
    INIT = auto()
    TEXT = auto()
    TOOL_USE = auto()
    USAGE = auto()
    RESULT = auto()
    ERROR = auto()


@dataclass
class Event:
    type: EventType
    text: str = ""
    metadata: dict | None = None


def parse_event(raw_line: str) -> Event | None:
    """Parse a single newline-delimited stream-json line into an Event.

    Returns ``None`` for lines we deliberately ignore (malformed JSON, empty
    lines, non-text deltas, full ``assistant`` text which duplicates deltas).
    """
    if not raw_line or not raw_line.strip():
        return None
    try:
        data = json.loads(raw_line)
    except json.JSONDecodeError:
        return None

    kind = data.get("type")

    if kind == "system" and data.get("subtype") == "init":
        sid = data.get("session_id")
        if sid:
            return Event(type=EventType.INIT, metadata={"session_id": sid})
        return None

    if kind == "stream_event":
        event = data.get("event") or {}
        delta = event.get("delta") or {}
        if delta.get("type") == "text_delta":
            text = delta.get("text", "")
            if text:
                return Event(type=EventType.TEXT, text=text)
        return None

    if kind == "assistant":
        # Extract tool_use items; ignore the full text (duplicate of text_delta).
        message = data.get("message") or {}
        for block in message.get("content", []) or []:
            if block.get("type") == "tool_use":
                return Event(type=EventType.TOOL_USE, text=block.get("name", ""))
        return None

    if kind == "result":
        usage = data.get("usage") or {}
        return Event(
            type=EventType.RESULT,
            text=data.get("result", "") or "",
            metadata={
                "session_id": data.get("session_id"),
                "usage": usage,
                "cost_usd": data.get("total_cost_usd", 0.0),
            },
        )

    if kind == "error":
        return Event(
            type=EventType.ERROR,
            text=str(data.get("error") or data.get("message") or "unknown"),
            metadata=data,
        )

    return None
