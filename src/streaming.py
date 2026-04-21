"""Telegram streaming: sendMessageDraft loop + elapsed-time indicator.

- `start()` sends the timer message and spawns two background tasks:
  1. Draft loop — pushes the text buffer to Telegram every 30ms via `sendMessageDraft`.
  2. Timer loop — edits the timer message every 2s with elapsed seconds.
- `append(text)` appends to the buffer (the draft loop picks it up).
- `finalize()` stops the loops, sends the final formatted message, deletes the timer.
- On `sendMessageDraft` failure the draft loop transparently falls back to
  ``send_message`` + ``edit_message_text``.

During streaming we push **HTML-escaped plain text**, not markdown→HTML output.
Re-formatting on every tick would reshape the text whenever a markdown pair
closes (e.g. ``**word**`` → ``<b>word</b>``), turning what should be a pure
append into a mid-string rewrite. The draft animation renders such rewrites
as delete-and-retype, which looks like the message is flickering. Full
markdown formatting is applied only in ``finalize()`` for the final message.
"""
from __future__ import annotations

import asyncio
import html
import logging
import random
import re
import time
from dataclasses import dataclass, field

from aiogram import Bot
from aiogram.types import BufferedInputFile, Message

from src.formatter import format_for_telegram, strip_html_tags

logger = logging.getLogger(__name__)


DRAFT_INTERVAL = 0.03  # 30ms — draft API has no rate limit
TIMER_INTERVAL = 2.0   # 2s — edit_message_text has a 1/sec limit, 2s is safe


def _format_elapsed(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)}с"
    m, s = divmod(int(seconds), 60)
    return f"{m}м {s}с"


@dataclass
class StreamingState:
    chat_id: int
    max_length: int = 4096

    timer_message: Message | None = None
    final_message: Message | None = None
    buffer: str = ""
    _draft_id: int = field(default_factory=lambda: random.randint(1, 2**31 - 1))
    _receiving: bool = True
    _start_time: float = field(default_factory=time.time)
    _draft_task: asyncio.Task | None = None
    _timer_task: asyncio.Task | None = None
    _done: asyncio.Event = field(default_factory=asyncio.Event)
    _fallback_mode: bool = False


class Streamer:
    def __init__(
        self,
        bot: Bot,
        *,
        max_length: int = 4096,
        code_threshold: int = 500,
    ) -> None:
        self._bot = bot
        self._max_length = max_length
        self._code_threshold = code_threshold

    async def start(self, chat_id: int) -> StreamingState:
        timer = await self._bot.send_message(chat_id, "⏳ 0с")
        state = StreamingState(
            chat_id=chat_id,
            max_length=self._max_length,
            timer_message=timer,
        )
        # sendMessageDraft works only in private chats (positive chat_id).
        # In groups/channels go straight to fallback — no point spamming the
        # draft endpoint with requests that will always fail.
        if chat_id < 0:
            state._fallback_mode = True
            logger.info(
                "draft streaming disabled: chat_id=%s is not a private chat",
                chat_id,
            )
        state._draft_task = asyncio.create_task(self._draft_loop(state))
        state._timer_task = asyncio.create_task(self._timer_loop(state))
        return state

    def append(self, state: StreamingState, chunk: str) -> None:
        state.buffer += chunk

    async def finalize(self, state: StreamingState, *, aborted: bool = False) -> Message | None:
        """Stop loops, send final HTML message, delete timer. Returns final message."""
        state._receiving = False
        try:
            await asyncio.wait_for(state._done.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            pass
        for task in (state._draft_task, state._timer_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # Delete timer message
        if state.timer_message:
            try:
                await state.timer_message.delete()
            except Exception:
                logger.debug("timer message already deleted or unavailable")

        # Nothing to send?
        if not state.buffer.strip():
            notice = "🛑 Остановлено (без текста)" if aborted else "✅ Готово (без текста)"
            try:
                return await self._bot.send_message(state.chat_id, notice)
            except Exception as e:
                logger.warning("send empty-result notice failed: %s", e)
                return None

        return await self._send_final(state, aborted=aborted)

    # --- loops ------------------------------------------------------------

    async def _draft_loop(self, state: StreamingState) -> None:
        last_len = 0
        try:
            while True:
                buf_len = len(state.buffer)
                if buf_len > last_len:
                    display = state.buffer
                    if len(display) > state.max_length - 50:
                        display = display[-(state.max_length - 50):]
                    # HTML-escaped plain text only — markdown rendering happens
                    # in finalize(). See module docstring.
                    draft_text = html.escape(display)
                    if not state._fallback_mode:
                        try:
                            await self._bot.send_message_draft(
                                chat_id=state.chat_id,
                                draft_id=state._draft_id,
                                text=draft_text,
                                parse_mode="HTML",
                            )
                        except Exception as e:
                            logger.warning(
                                "sendMessageDraft failed, falling back to "
                                "send_message+edit_text: %s: %s (text_len=%d, "
                                "draft_id=%s, chat_id=%s)",
                                type(e).__name__,
                                e,
                                len(draft_text),
                                state._draft_id,
                                state.chat_id,
                            )
                            state._fallback_mode = True
                    if state._fallback_mode:
                        try:
                            if state.final_message is None:
                                state.final_message = await self._bot.send_message(
                                    state.chat_id, draft_text, parse_mode="HTML"
                                )
                            else:
                                await state.final_message.edit_text(
                                    draft_text, parse_mode="HTML"
                                )
                        except Exception as e:
                            if "message is not modified" not in str(e):
                                logger.debug("fallback edit error: %s", e)
                    last_len = buf_len
                elif not state._receiving:
                    state._done.set()
                    return
                await asyncio.sleep(DRAFT_INTERVAL)
        except asyncio.CancelledError:
            pass
        finally:
            state._done.set()

    async def _timer_loop(self, state: StreamingState) -> None:
        try:
            while state._receiving:
                await asyncio.sleep(TIMER_INTERVAL)
                elapsed = time.time() - state._start_time
                text = f"⏳ {_format_elapsed(elapsed)}"
                if state.timer_message:
                    try:
                        await state.timer_message.edit_text(text)
                    except Exception as e:
                        if "message is not modified" not in str(e):
                            logger.debug("timer edit error: %s", e)
        except asyncio.CancelledError:
            pass

    # --- final send -------------------------------------------------------

    async def _send_final(self, state: StreamingState, *, aborted: bool) -> Message | None:
        text = state.buffer
        text, code_files = self._extract_code_blocks(text)
        try:
            html_text = format_for_telegram(text) or text
        except Exception as e:
            logger.warning("format_for_telegram failed in finalize: %s", e)
            html_text = text
        prefix = "🛑 <i>Остановлено</i>\n\n" if aborted else ""
        full = prefix + html_text

        # If fallback mode: edit the already-created message
        if state.final_message is not None:
            try:
                await state.final_message.edit_text(full, parse_mode="HTML")
                last_msg = state.final_message
            except Exception as e:
                logger.warning("final edit failed, sending new message: %s", e)
                last_msg = await self._send_possibly_split(state, full)
        else:
            last_msg = await self._send_possibly_split(state, full)

        for filename, code in code_files:
            try:
                await self._bot.send_document(
                    state.chat_id,
                    BufferedInputFile(code.encode("utf-8"), filename=filename),
                )
            except Exception as e:
                logger.warning("code file send failed: %s", e)
        return last_msg

    async def _send_possibly_split(self, state: StreamingState, html_text: str) -> Message | None:
        if len(html_text) <= state.max_length - 50:
            try:
                return await self._bot.send_message(
                    state.chat_id, html_text, parse_mode="HTML"
                )
            except Exception as e:
                logger.warning("html send failed, trying plain: %s", e)
                plain = strip_html_tags(html_text)
                return await self._bot.send_message(state.chat_id, plain[: state.max_length])

        last: Message | None = None
        for chunk in self._split(html_text, state.max_length - 100):
            try:
                last = await self._bot.send_message(state.chat_id, chunk, parse_mode="HTML")
            except Exception as e:
                logger.warning("split chunk html send failed, trying plain: %s", e)
                last = await self._bot.send_message(state.chat_id, strip_html_tags(chunk))
        return last

    def _split(self, text: str, max_len: int) -> list[str]:
        chunks: list[str] = []
        current = ""
        for para in text.split("\n\n"):
            if len(current) + len(para) + 2 > max_len:
                if current:
                    chunks.append(current.strip())
                current = para
                while len(current) > max_len:
                    chunks.append(current[:max_len])
                    current = current[max_len:]
            else:
                current = f"{current}\n\n{para}" if current else para
        if current:
            chunks.append(current.strip())
        return chunks or [""]

    def _extract_code_blocks(self, text: str) -> tuple[str, list[tuple[str, str]]]:
        files: list[tuple[str, str]] = []
        pattern = re.compile(r"```(\w+)?\n(.*?)```", re.DOTALL)

        def replace(m: re.Match) -> str:
            lang = (m.group(1) or "txt").lower()
            code = m.group(2)
            if len(code) > self._code_threshold:
                ext = self._ext(lang)
                filename = f"code_{len(files) + 1}.{ext}"
                files.append((filename, code))
                return f"[код отправлен файлом: {filename}]"
            return m.group(0)

        return pattern.sub(replace, text), files

    @staticmethod
    def _ext(lang: str) -> str:
        return {
            "python": "py",
            "javascript": "js",
            "typescript": "ts",
            "bash": "sh",
            "shell": "sh",
            "json": "json",
            "yaml": "yaml",
            "html": "html",
            "css": "css",
            "sql": "sql",
            "go": "go",
            "rust": "rs",
            "java": "java",
            "cpp": "cpp",
            "c": "c",
        }.get(lang, "txt")
