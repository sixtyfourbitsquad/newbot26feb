"""Start command and welcome message."""
import logging

from telegram import Update
from telegram.ext import ContextTypes

import database as db
from config import DEFAULT_WELCOME_TEXT

logger = logging.getLogger(__name__)


async def send_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send welcome message from DB or default placeholder."""
    user = update.effective_user
    if not user:
        return

    await db.upsert_user(
        telegram_id=user.id,
        username=user.username,
        first_name=user.first_name,
    )

    payload = await db.get_setting("welcome_message")
    if payload and isinstance(payload, dict):
        msg_type = payload.get("type", "text")
        try:
            if msg_type == "text":
                text = payload.get("text") or DEFAULT_WELCOME_TEXT
                await update.message.reply_text(text)
            elif msg_type == "photo":
                await context.bot.send_photo(
                    chat_id=update.effective_chat.id,
                    photo=payload["file_id"],
                    caption=payload.get("caption", ""),
                )
            elif msg_type == "video":
                await context.bot.send_video(
                    chat_id=update.effective_chat.id,
                    video=payload["file_id"],
                    caption=payload.get("caption", ""),
                )
            elif msg_type == "document":
                await context.bot.send_document(
                    chat_id=update.effective_chat.id,
                    document=payload["file_id"],
                    caption=payload.get("caption", ""),
                )
            elif msg_type == "audio":
                await context.bot.send_audio(
                    chat_id=update.effective_chat.id,
                    audio=payload["file_id"],
                    caption=payload.get("caption", ""),
                )
            else:
                await update.message.reply_text(DEFAULT_WELCOME_TEXT)
        except Exception as e:
            logger.exception("Failed to send stored welcome: %s", e)
            await update.message.reply_text(DEFAULT_WELCOME_TEXT)
    else:
        await update.message.reply_text(DEFAULT_WELCOME_TEXT)
