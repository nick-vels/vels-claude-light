"""Save incoming Telegram files to the bot's working directory.

Files are placed under ``<working_dir>/.telegram-uploads/`` so Claude Code
(running with ``cwd=working_dir``) can open them with its Read tool. The
file path is passed to Claude inside the prompt string — no special flag
on the CLI is needed since Read handles images, PDFs, text, and Jupyter
notebooks natively.
"""
from __future__ import annotations

import logging
import re
import time
from pathlib import Path

from aiogram import Bot

logger = logging.getLogger(__name__)

UPLOAD_SUBDIR = ".telegram-uploads"
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_NAME_LEN = 80


def sanitize_name(name: str) -> str:
    """ASCII-only, [A-Za-z0-9._-] — safe for any filesystem and shell."""
    cleaned = _SAFE_NAME_RE.sub("_", name).strip("._")
    if not cleaned:
        cleaned = "file"
    if len(cleaned) > _MAX_NAME_LEN:
        stem, dot, ext = cleaned.rpartition(".")
        if dot and len(ext) <= 10:
            cleaned = stem[: _MAX_NAME_LEN - len(ext) - 1] + "." + ext
        else:
            cleaned = cleaned[:_MAX_NAME_LEN]
    return cleaned


async def save_to_uploads(
    bot: Bot,
    *,
    file_id: str,
    file_name: str,
    working_dir: str,
) -> Path:
    """Download a Telegram file into ``working_dir/.telegram-uploads/``.

    If the name collides with an existing file, a unix-timestamp prefix is
    prepended. Returns the absolute path of the saved file. Raises on
    network / Telegram errors — caller decides how to report to the user.
    """
    safe = sanitize_name(file_name)
    dest_dir = Path(working_dir) / UPLOAD_SUBDIR
    dest_dir.mkdir(parents=True, exist_ok=True)

    dest = dest_dir / safe
    if dest.exists():
        dest = dest_dir / f"{int(time.time())}_{safe}"

    file = await bot.get_file(file_id)
    if not file.file_path:
        raise RuntimeError("Telegram did not return a file_path")

    with open(dest, "wb") as fh:
        await bot.download_file(file.file_path, fh)

    size = dest.stat().st_size
    logger.info("saved upload: %s (%d bytes)", dest, size)
    return dest
