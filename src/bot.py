"""Telegram bot — aiogram Dispatcher, auth, handlers, per-chat FIFO queue."""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from aiogram import BaseMiddleware, Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import BotCommand, Message, TelegramObject

from src.bridge import (
    ClaudeBridge,
    ClaudeError,
    ContextOverflow,
    EventType,
    resolve_claude_binary,
)
from src.storage import Storage
from src.streaming import Streamer

logger = logging.getLogger(__name__)

BOT_COMMANDS = [
    BotCommand(command="new", description="Начать новую сессию"),
    BotCommand(command="clear", description="Синоним /new"),
    BotCommand(command="compact", description="Сжать историю"),
    BotCommand(command="stop", description="Остановить генерацию"),
    BotCommand(command="status", description="Состояние сессии"),
]


class AuthMiddleware(BaseMiddleware):
    def __init__(self, allowed_user_ids: set[int]) -> None:
        self._allowed = allowed_user_ids

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if user is None or user.id not in self._allowed:
            logger.warning("auth_rejected user_id=%s", user.id if user else None)
            return
        return await handler(event, data)


@dataclass
class ChatState:
    """Per-chat runtime state: active bridge, queue, lock."""

    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    queue: deque = field(default_factory=deque)
    active_bridge: ClaudeBridge | None = None
    active_streaming: Any = None  # StreamingState
    active_task: asyncio.Task | None = None


@dataclass
class BotConfig:
    token: str
    allowed_user_ids: set[int]
    working_dir: str
    claude_binary: str
    permission_mode: str
    timeout_minutes: int
    sessions_file: str
    max_message_length: int
    code_as_file_threshold: int


class VelsClaudeLightBot:
    def __init__(self, cfg: BotConfig) -> None:
        self._cfg = cfg
        session = AiohttpSession()
        session._proxy = None  # Telegram reachable without proxy; VPN at OS level
        self._bot = Bot(
            token=cfg.token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
            session=session,
        )
        self._dp = Dispatcher()
        self._dp.message.middleware(AuthMiddleware(cfg.allowed_user_ids))

        self._storage = Storage(cfg.sessions_file)
        self._binary = resolve_claude_binary(cfg.claude_binary)
        self._streamer = Streamer(
            self._bot,
            max_length=cfg.max_message_length,
            code_threshold=cfg.code_as_file_threshold,
        )
        self._chats: dict[int, ChatState] = defaultdict(ChatState)

        self._register_handlers()

    # --- lifecycle --------------------------------------------------------

    async def run(self) -> None:
        await self._bot.set_my_commands(BOT_COMMANDS)
        await self._bot.delete_webhook(drop_pending_updates=True)
        me = await self._bot.get_me()
        logger.info("bot ready: @%s (%s)", me.username, me.id)
        try:
            await self._dp.start_polling(self._bot)
        finally:
            await self._bot.session.close()

    # --- handler registration --------------------------------------------

    def _register_handlers(self) -> None:
        self._dp.message.register(self._cmd_start, CommandStart())
        # Commands /new /clear /compact /stop /status land in Task 9
        self._dp.message.register(self._on_text)

    # --- handlers ---------------------------------------------------------

    async def _cmd_start(self, msg: Message) -> None:
        await msg.answer(
            "🤖 <b>Vels Claude Light</b>\n\n"
            "Просто пишите сообщения — Claude Code ответит.\n\n"
            "<b>Команды:</b>\n"
            "/new — начать новую сессию (сбрасывает контекст)\n"
            "/clear — синоним /new\n"
            "/compact — сжать текущую историю диалога\n"
            "/stop — остановить генерацию\n"
            "/status — состояние сессии\n\n"
            f"<b>Рабочая директория:</b> <code>{self._cfg.working_dir}</code>",
        )

    async def _on_text(self, msg: Message) -> None:
        """Default handler: push user text into FIFO queue for this chat."""
        if not msg.text:
            return
        chat = self._chats[msg.chat.id]
        # If nothing is running, run immediately; otherwise queue
        if chat.active_task is None or chat.active_task.done():
            chat.active_task = asyncio.create_task(
                self._run_one(msg.chat.id, msg.text, msg)
            )
        else:
            chat.queue.append((msg.text, msg))
            pending = len(chat.queue)
            await msg.answer(f"⏳ В очереди ({pending} впереди)")

    async def _run_one(self, chat_id: int, text: str, reply_to: Message) -> None:
        chat = self._chats[chat_id]
        async with chat.lock:
            try:
                await self._exec_claude(chat_id, text, reply_to, chat)
            finally:
                # Drain queue
                if chat.queue:
                    next_text, next_msg = chat.queue.popleft()
                    chat.active_task = asyncio.create_task(
                        self._run_one(chat_id, next_text, next_msg)
                    )

    async def _exec_claude(
        self,
        chat_id: int,
        prompt: str,
        reply_to: Message,
        chat: ChatState,
    ) -> None:
        session = await self._storage.get_session(chat_id)
        session_id = session["session_id"] if session else None

        bridge = ClaudeBridge(
            binary=self._binary,
            working_dir=self._cfg.working_dir,
            permission_mode=self._cfg.permission_mode,
            timeout_minutes=self._cfg.timeout_minutes,
        )
        chat.active_bridge = bridge
        state = await self._streamer.start(chat_id)
        chat.active_streaming = state

        try:
            async for event in bridge.run(prompt=prompt, session_id=session_id):
                if event.type == EventType.INIT:
                    sid = (event.metadata or {}).get("session_id")
                    if sid:
                        await self._storage.set_session(chat_id, sid)
                elif event.type == EventType.TEXT:
                    self._streamer.append(state, event.text)
                elif event.type == EventType.RESULT:
                    meta = event.metadata or {}
                    sid = meta.get("session_id")
                    if sid:
                        await self._storage.set_session(chat_id, sid)
            await self._streamer.finalize(state)
            await self._storage.bump_message_count(chat_id)
        except ContextOverflow as e:
            await self._streamer.finalize(state, aborted=True)
            await self._storage.clear_session(chat_id)
            await reply_to.answer(e.user_message)
        except ClaudeError as e:
            await self._streamer.finalize(state, aborted=True)
            await reply_to.answer(e.user_message)
        except asyncio.CancelledError:
            await self._streamer.finalize(state, aborted=True)
            raise
        except Exception as e:
            logger.exception("unexpected error running claude")
            await self._streamer.finalize(state, aborted=True)
            await reply_to.answer(f"❌ Неожиданная ошибка: {e}")
        finally:
            chat.active_bridge = None
            chat.active_streaming = None
