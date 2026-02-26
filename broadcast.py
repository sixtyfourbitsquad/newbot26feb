"""
Broadcast engine: queue-based worker pool, semaphore rate limit, retry logic.
Uses copy_message when source message is available; falls back to payload send.
All broadcast logic isolated here; does not block event loop.
"""
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from telegram import Bot
from telegram.error import Forbidden, BadRequest, RetryAfter

import database as db
from config import (
    BROADCAST_BATCH_SIZE,
    BROADCAST_MESSAGES_PER_SECOND,
    ADMIN_GROUP_ID,
)

logger = logging.getLogger(__name__)

# Retry
MAX_RETRY_AFTER_ATTEMPTS = 5


@dataclass
class BroadcastParams:
    """Input for a single broadcast run."""
    bot: Bot
    user_ids: list[int]
    broadcast_id: int
    admin_chat_id: int
    # When set, use copy_message for each user (preferred for media)
    source_chat_id: int | None = None
    source_message_id: int | None = None
    # Fallback when copy_message not used or fails
    payload: dict[str, Any] | None = None


@dataclass
class BroadcastState:
    """Shared state for progress and rate limiting."""
    success: int = 0
    failed: int = 0
    batch_count: int = 0
    last_progress_at: int = 0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


async def _send_via_copy(
    bot: Bot,
    user_id: int,
    source_chat_id: int,
    source_message_id: int,
) -> bool:
    """Send using copy_message. Return True if sent, False if user blocked/invalid."""
    try:
        await bot.copy_message(
            chat_id=user_id,
            from_chat_id=source_chat_id,
            message_id=source_message_id,
        )
        return True
    except RetryAfter:
        raise
    except (Forbidden, BadRequest) as e:
        err = str(e).lower()
        if "blocked" in err or "user is deactivated" in err or "chat not found" in err or "user not found" in err:
            return False
        raise
    except Exception:
        raise


async def _send_via_payload(bot: Bot, user_id: int, payload: dict) -> bool:
    """Send using payload (type + file_id/text). Return True if sent, False if blocked."""
    chat_id = user_id
    try:
        if payload.get("type") == "text":
            await bot.send_message(chat_id=chat_id, text=payload.get("text", ""))
            return True
        cap = payload.get("caption", "") or ""
        if payload.get("type") == "photo":
            await bot.send_photo(chat_id=chat_id, photo=payload["file_id"], caption=cap)
            return True
        if payload.get("type") == "video":
            await bot.send_video(chat_id=chat_id, video=payload["file_id"], caption=cap)
            return True
        if payload.get("type") == "document":
            await bot.send_document(chat_id=chat_id, document=payload["file_id"], caption=cap)
            return True
        if payload.get("type") == "audio":
            await bot.send_audio(chat_id=chat_id, audio=payload["file_id"], caption=cap)
            return True
        if payload.get("type") == "voice":
            await bot.send_voice(chat_id=chat_id, voice=payload["file_id"], caption=cap)
            return True
        if payload.get("type") == "sticker":
            await bot.send_sticker(chat_id=chat_id, sticker=payload["file_id"])
            return True
        if payload.get("type") == "video_note":
            await bot.send_video_note(chat_id=chat_id, video_note=payload["file_id"])
            return True
        await bot.send_message(chat_id=chat_id, text=payload.get("text", ""))
        return True
    except RetryAfter:
        raise
    except (Forbidden, BadRequest) as e:
        err = str(e).lower()
        if "blocked" in err or "user is deactivated" in err or "chat not found" in err or "user not found" in err:
            return False
        raise
    except Exception:
        raise


async def _send_one_with_retry(
    params: BroadcastParams,
    user_id: int,
    state: BroadcastState,
) -> None:
    """
    Send to one user. Use copy_message when possible, else payload.
    Implements retry logic for RetryAfter. Does not raise; single user failure is isolated.
    """
    bot = params.bot
    use_copy = params.source_chat_id is not None and params.source_message_id is not None

    for attempt in range(1, MAX_RETRY_AFTER_ATTEMPTS + 1):
        try:
            if use_copy:
                try:
                    ok = await _send_via_copy(
                        bot, user_id, params.source_chat_id, params.source_message_id
                    )
                except (BadRequest, Forbidden) as copy_err:
                    err = str(copy_err).lower()
                    if "blocked" in err or "user is deactivated" in err or "chat not found" in err or "user not found" in err:
                        await db.set_user_blocked(user_id, blocked=True)
                        async with state.lock:
                            state.failed += 1
                        logger.info("Broadcast copy_message: user %s blocked/invalid", user_id)
                        return
                    if params.payload:
                        logger.debug("Broadcast copy_message failed for user %s, falling back to payload", user_id)
                        ok = await _send_via_payload(bot, user_id, params.payload)
                    else:
                        async with state.lock:
                            state.failed += 1
                        logger.warning("Broadcast copy_message failed for user %s, no payload fallback", user_id)
                        return
            elif params.payload:
                ok = await _send_via_payload(bot, user_id, params.payload)
            else:
                logger.warning("Broadcast send skipped for user %s: no source and no payload", user_id)
                async with state.lock:
                    state.failed += 1
                return

            if ok:
                async with state.lock:
                    state.success += 1
                logger.debug("Broadcast sent to user %s", user_id)
            else:
                await db.set_user_blocked(user_id, blocked=True)
                async with state.lock:
                    state.failed += 1
                logger.info("Broadcast: user %s blocked or invalid, marked blocked", user_id)
            return

        except RetryAfter as e:
            logger.warning(
                "Broadcast RetryAfter for user %s (attempt %s/%s), sleeping %s s",
                user_id, attempt, MAX_RETRY_AFTER_ATTEMPTS, e.retry_after,
            )
            await asyncio.sleep(e.retry_after)
            continue

        except (Forbidden, BadRequest) as e:
            err = str(e).lower()
            if "blocked" in err or "user is deactivated" in err or "chat not found" in err or "user not found" in err:
                await db.set_user_blocked(user_id, blocked=True)
                async with state.lock:
                    state.failed += 1
                logger.info("Broadcast: user %s blocked/invalid, marked blocked", user_id)
            else:
                async with state.lock:
                    state.failed += 1
                logger.exception("Broadcast send failed for user %s: %s", user_id, e)
            return

        except Exception as e:
            async with state.lock:
                state.failed += 1
            logger.exception("Broadcast send failed for user %s (non-fatal): %s", user_id, e)
            return

    async with state.lock:
        state.failed += 1
    logger.warning("Broadcast: user %s failed after %s RetryAfter attempts", user_id, MAX_RETRY_AFTER_ATTEMPTS)


async def _worker(
    params: BroadcastParams,
    queue: asyncio.Queue[int | None],
    semaphore: asyncio.Semaphore,
    state: BroadcastState,
    progress_interval: int,
    total: int,
) -> None:
    """Single worker: get user_id from queue, rate-limited send (semaphore), never crash on single failure."""
    while True:
        user_id = await queue.get()
        try:
            if user_id is None:
                queue.task_done()
                return
            async with semaphore:
                await _send_one_with_retry(params, user_id, state)
                async with state.lock:
                    state.batch_count += 1
                    n = state.batch_count
                if n % BROADCAST_MESSAGES_PER_SECOND == 0:
                    await asyncio.sleep(1.0)
        except Exception as e:
            logger.exception("Broadcast worker non-fatal error: %s", e)
        finally:
            queue.task_done()


async def _progress_sender(
    bot: Bot,
    admin_chat_id: int,
    state: BroadcastState,
    total: int,
    progress_interval: int,
    stop_event: asyncio.Event,
) -> None:
    """Periodically send progress to admin group; does not block broadcast workers."""
    while not stop_event.is_set():
        await asyncio.sleep(2.0)
        if stop_event.is_set():
            return
        async with state.lock:
            current = state.success + state.failed
            if current - state.last_progress_at >= progress_interval or current >= total:
                state.last_progress_at = current
                try:
                    await bot.send_message(
                        admin_chat_id,
                        f"📢 Broadcast progress: {current}/{total} (✓ {state.success} ✗ {state.failed})",
                    )
                    logger.info("Broadcast progress sent to admin: %s/%s", current, total)
                except Exception as e:
                    logger.warning("Could not send broadcast progress: %s", e)


def run_broadcast(
    bot: Bot,
    user_ids: list[int],
    payload: dict[str, Any],
    broadcast_id: int,
    admin_chat_id: int,
    *,
    source_chat_id: int | None = None,
    source_message_id: int | None = None,
) -> None:
    """
    Start broadcast as a background task (non-blocking).
    Uses queue-based worker pool and asyncio.Semaphore for rate limit.
    Prefer copy_message when source_chat_id and source_message_id are provided.
    """
    total = len(user_ids)
    if total == 0:
        logger.warning("Broadcast started with 0 users")
        return

    params = BroadcastParams(
        bot=bot,
        user_ids=user_ids,
        broadcast_id=broadcast_id,
        admin_chat_id=admin_chat_id,
        source_chat_id=source_chat_id,
        source_message_id=source_message_id,
        payload=payload,  # used when no source, or as fallback when copy_message fails
    )

    state = BroadcastState()
    progress_interval = 100
    semaphore = asyncio.Semaphore(BROADCAST_BATCH_SIZE)
    queue: asyncio.Queue[int | None] = asyncio.Queue()

    logger.info(
        "Broadcast started: id=%s total=%s use_copy=%s",
        broadcast_id, total,
        source_chat_id is not None and source_message_id is not None,
    )

    async def _run() -> None:
        stop_progress = asyncio.Event()
        for uid in user_ids:
            await queue.put(uid)
        for _ in range(min(BROADCAST_BATCH_SIZE, total)):
            await queue.put(None)

        workers = [
            asyncio.create_task(
                _worker(params, queue, semaphore, state, progress_interval, total)
            )
            for _ in range(min(BROADCAST_BATCH_SIZE, total))
        ]
        progress_task = asyncio.create_task(
            _progress_sender(bot, admin_chat_id, state, total, progress_interval, stop_progress)
        )

        await queue.join()
        stop_progress.set()
        await asyncio.gather(*workers)
        progress_task.cancel()
        try:
            await progress_task
        except asyncio.CancelledError:
            pass

        logger.info(
            "Broadcast completing: id=%s success=%s failed=%s, updating DB",
            broadcast_id, state.success, state.failed,
        )
        await db.update_broadcast(
            broadcast_id,
            success=state.success,
            failed=state.failed,
            status="completed",
        )
        logger.info(
            "Broadcast completed: id=%s success=%s failed=%s",
            broadcast_id, state.success, state.failed,
        )
        try:
            await bot.send_message(
                admin_chat_id,
                f"📢 Broadcast finished.\nTotal: {total}\nSuccess: {state.success}\nFailed: {state.failed}",
            )
        except Exception as e:
            logger.warning("Could not send broadcast completion message: %s", e)

    asyncio.create_task(_run())
