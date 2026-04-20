"""JSON persistence for chat_id → session_id mapping.

One file: ``data/sessions.json``. Atomic write via temp + rename.
All reads/writes are async (aiofiles) so the bot's event loop stays unblocked.
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import aiofiles


class Storage:
    """In-memory cache + JSON file persistence."""

    def __init__(self, path: Path):
        self._path = Path(path)
        self._lock = asyncio.Lock()
        self._cache: dict[str, dict] | None = None

    async def _load(self) -> dict[str, dict]:
        if self._cache is not None:
            return self._cache
        if not self._path.exists():
            self._cache = {}
            return self._cache
        async with aiofiles.open(self._path, encoding="utf-8") as f:
            data = await f.read()
        self._cache = json.loads(data) if data.strip() else {}
        return self._cache

    async def _save(self) -> None:
        if self._cache is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        async with aiofiles.open(tmp, "w", encoding="utf-8") as f:
            await f.write(json.dumps(self._cache, indent=2, ensure_ascii=False))
        os.replace(tmp, self._path)

    async def get_session(self, chat_id: int) -> dict | None:
        async with self._lock:
            data = await self._load()
            return data.get(str(chat_id))

    async def set_session(self, chat_id: int, session_id: str) -> None:
        async with self._lock:
            data = await self._load()
            entry = data.get(str(chat_id)) or {"message_count": 0}
            entry["session_id"] = session_id
            entry["last_activity"] = datetime.now(timezone.utc).isoformat()
            data[str(chat_id)] = entry
            await self._save()

    async def bump_message_count(self, chat_id: int) -> None:
        async with self._lock:
            data = await self._load()
            entry = data.get(str(chat_id))
            if not entry:
                return
            entry["message_count"] = entry.get("message_count", 0) + 1
            entry["last_activity"] = datetime.now(timezone.utc).isoformat()
            await self._save()

    async def clear_session(self, chat_id: int) -> None:
        async with self._lock:
            data = await self._load()
            data.pop(str(chat_id), None)
            await self._save()
