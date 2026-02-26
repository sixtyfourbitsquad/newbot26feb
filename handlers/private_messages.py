"""Handle all private messages: forward to admin group without captions."""
import logging

from telegram import Update
from telegram.ext import ContextTypes

import database as db
from config import ADMIN_GROUP_ID

logger = logging.getLogger(__name__)


async def handle_private_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Forward private message to admin group and store mapping."""
    if not update.message or not update.effective_user:
        return

    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    message_id = update.message.message_id

    await db.update_last_active(user_id)

    try:
        forwarded = await context.bot.forward_message(
            chat_id=ADMIN_GROUP_ID,
            from_chat_id=chat_id,
            message_id=message_id,
        )
        if forwarded and forwarded.message_id:
            await db.save_forward_mapping(
                admin_chat_id=ADMIN_GROUP_ID,
                admin_message_id=forwarded.message_id,
                user_telegram_id=user_id,
            )
    except Exception as e:
        logger.exception("Failed to forward private message to admin group: %s", e)
