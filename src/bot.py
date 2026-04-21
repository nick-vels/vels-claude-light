"""Telegram bot — aiogram Dispatcher, auth, handlers, per-chat FIFO queue."""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aiogram import BaseMiddleware, Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllChatAdministrators,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    Message,
    TelegramObject,
)

from src.bridge import (
    ClaudeBridge,
    ClaudeError,
    ContextOverflow,
    EventType,
    resolve_claude_binary,
)
from src.storage import Storage
from src.streaming import Streamer
from src.uploads import save_to_uploads

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
        # Clear command overrides on narrower scopes. Telegram resolves the
        # client's command menu from the most specific matching scope, so a
        # forgotten BotFather entry under e.g. "all private chats" would mask
        # the default scope set below.
        for scope in (
            BotCommandScopeAllPrivateChats(),
            BotCommandScopeAllGroupChats(),
            BotCommandScopeAllChatAdministrators(),
        ):
            try:
                await self._bot.delete_my_commands(scope=scope)
            except Exception as e:
                logger.debug("delete_my_commands(%s) failed: %s", type(scope).__name__, e)
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
        self._dp.message.register(self._cmd_new, Command("new", "clear"))
        self._dp.message.register(self._cmd_compact, Command("compact"))
        self._dp.message.register(self._cmd_stop, Command("stop"))
        self._dp.message.register(self._cmd_status, Command("status"))
        # Media before text — order matters, aiogram picks the first match.
        self._dp.message.register(self._on_photo, F.photo)
        self._dp.message.register(self._on_document, F.document)
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
        await self._dispatch_prompt(msg, msg.text)

    async def _on_photo(self, msg: Message) -> None:
        """Save Telegram photo to working_dir and feed its path into Claude."""
        if not msg.photo:
            return
        # Largest rendition last; file_id is stable.
        photo = msg.photo[-1]
        try:
            path = await save_to_uploads(
                self._bot,
                file_id=photo.file_id,
                file_name=f"photo_{photo.file_unique_id}.jpg",
                working_dir=self._cfg.working_dir,
            )
        except Exception as e:
            logger.warning("photo download failed: %s", e)
            await msg.answer(f"❌ Не удалось скачать изображение: {e}")
            return
        await self._dispatch_prompt(msg, self._build_upload_prompt(path, msg.caption))

    async def _on_document(self, msg: Message) -> None:
        """Save any document attachment and feed its path into Claude."""
        if not msg.document:
            return
        doc = msg.document
        try:
            path = await save_to_uploads(
                self._bot,
                file_id=doc.file_id,
                file_name=doc.file_name or f"file_{doc.file_unique_id}",
                working_dir=self._cfg.working_dir,
            )
        except Exception as e:
            logger.warning("document download failed: %s", e)
            await msg.answer(f"❌ Не удалось скачать файл: {e}")
            return
        await self._dispatch_prompt(msg, self._build_upload_prompt(path, msg.caption))

    # --- helpers ----------------------------------------------------------

    async def _dispatch_prompt(self, msg: Message, prompt: str) -> None:
        """Run prompt immediately or enqueue behind an active task."""
        chat = self._chats[msg.chat.id]
        if chat.active_task is None or chat.active_task.done():
            chat.active_task = asyncio.create_task(
                self._run_one(msg.chat.id, prompt, msg)
            )
            return
        chat.queue.append((prompt, msg))
        await msg.answer(f"⏳ В очереди ({len(chat.queue)} впереди)")

    def _build_upload_prompt(self, path: Path, caption: str | None) -> str:
        """Prompt that references the uploaded file's path relative to cwd."""
        try:
            rel = path.relative_to(Path(self._cfg.working_dir))
        except ValueError:
            rel = path
        header = f"Пользователь прикрепил файл: {rel}"
        caption = (caption or "").strip()
        if caption:
            return f"{header}\n\n{caption}"
        return f"{header}\n\nПрочитай его (инструмент Read поддерживает изображения, PDF, текст) и ответь пользователю."

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

        got_text = False
        try:
            async for event in bridge.run(prompt=prompt, session_id=session_id):
                if event.type == EventType.INIT:
                    sid = (event.metadata or {}).get("session_id")
                    if sid:
                        await self._storage.set_session(chat_id, sid)
                elif event.type == EventType.TEXT:
                    got_text = True
                    self._streamer.append(state, event.text)
                elif event.type == EventType.RESULT:
                    meta = event.metadata or {}
                    sid = meta.get("session_id")
                    if sid:
                        await self._storage.set_session(chat_id, sid)
                    # Some prompts (e.g. `/compact`) return only a terminal
                    # `result` without streaming text_delta chunks. Fold the
                    # result text in so the user sees *something*.
                    if not got_text and event.text:
                        self._streamer.append(state, event.text)
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

    async def _cmd_new(self, msg: Message) -> None:
        chat = self._chats[msg.chat.id]
        # 1. Cancel active generation if any
        if chat.active_task and not chat.active_task.done():
            chat.active_task.cancel()
            try:
                await chat.active_task
            except (asyncio.CancelledError, Exception):
                pass
        if chat.active_bridge:
            chat.active_bridge.kill()
        # 2. Clear queue
        chat.queue.clear()
        # 3. Wipe session
        await self._storage.clear_session(msg.chat.id)
        await msg.answer("✅ Новая сессия. Контекст сброшен.")

    async def _cmd_compact(self, msg: Message) -> None:
        chat = self._chats[msg.chat.id]
        if chat.active_task and not chat.active_task.done():
            await msg.answer("⏳ Подождите, Claude ещё отвечает.")
            return
        # Treat /compact as normal prompt — the Claude CLI handles the built-in command itself
        chat.active_task = asyncio.create_task(self._run_one(msg.chat.id, "/compact", msg))

    async def _cmd_stop(self, msg: Message) -> None:
        chat = self._chats[msg.chat.id]
        if chat.active_task is None or chat.active_task.done():
            await msg.answer("Нечего останавливать.")
            return
        if chat.active_bridge:
            chat.active_bridge.kill()
        chat.active_task.cancel()
        try:
            await chat.active_task
        except (asyncio.CancelledError, Exception):
            pass
        # Drop queued messages too — /stop is decisive
        chat.queue.clear()
        await msg.answer("🛑 Остановлено.")

    async def _cmd_status(self, msg: Message) -> None:
        session = await self._storage.get_session(msg.chat.id)
        if not session:
            await msg.answer("Нет активной сессии. Напишите что-нибудь, чтобы начать.")
            return
        sid = session.get("session_id", "")
        tail = sid[-8:] if sid else "(нет)"
        count = session.get("message_count", 0)
        last = session.get("last_activity", "—")
        await msg.answer(
            f"📊 <b>Сессия</b>\n"
            f"ID: <code>…{tail}</code>\n"
            f"Сообщений: {count}\n"
            f"Последняя активность: <code>{last}</code>\n"
            f"Рабочая директория: <code>{self._cfg.working_dir}</code>",
        )
