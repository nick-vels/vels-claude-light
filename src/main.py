"""Entry point: load `.env`, construct `BotConfig`, run bot."""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from src.bot import BotConfig, VelsClaudeLightBot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)


def _parse_user_ids(raw: str) -> set[int]:
    ids: set[int] = set()
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        ids.add(int(part))
    return ids


def load_config() -> BotConfig:
    # .env is optional — if env vars are already set (systemd EnvironmentFile), skip
    env_path = Path(".env")
    if env_path.exists():
        load_dotenv(env_path)

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set in .env")

    allowed = _parse_user_ids(os.environ.get("ALLOWED_USER_IDS", ""))
    if not allowed:
        raise RuntimeError("ALLOWED_USER_IDS is empty — bot would ignore everyone")

    working_dir = os.environ.get("WORKING_DIR", "").strip()
    if not working_dir:
        raise RuntimeError("WORKING_DIR is not set in .env")
    wd = Path(working_dir).expanduser()
    if not wd.is_dir():
        raise RuntimeError(f"WORKING_DIR does not exist or is not a directory: {wd}")

    sessions = os.environ.get("SESSIONS_FILE", "data/sessions.json").strip()

    return BotConfig(
        token=token,
        allowed_user_ids=allowed,
        working_dir=str(wd),
        claude_binary=os.environ.get("CLAUDE_BINARY", "auto").strip(),
        permission_mode=os.environ.get("PERMISSION_MODE", "bypassPermissions").strip(),
        timeout_minutes=int(os.environ.get("CLAUDE_TIMEOUT_MINUTES", "30")),
        sessions_file=sessions,
        max_message_length=int(os.environ.get("MAX_MESSAGE_LENGTH", "4096")),
        code_as_file_threshold=int(os.environ.get("CODE_AS_FILE_THRESHOLD", "500")),
    )


async def _async_main() -> int:
    try:
        cfg = load_config()
    except Exception as e:
        logger.error("config error: %s", e)
        return 2

    bot = VelsClaudeLightBot(cfg)
    logger.info(
        "starting Vels Claude Light (working_dir=%s, allowed=%s)",
        cfg.working_dir,
        sorted(cfg.allowed_user_ids),
    )
    try:
        await bot.run()
    except KeyboardInterrupt:
        logger.info("shutdown requested")
    except Exception:
        logger.exception("bot crashed")
        return 1
    return 0


def main() -> int:
    return asyncio.run(_async_main())


if __name__ == "__main__":
    sys.exit(main())
