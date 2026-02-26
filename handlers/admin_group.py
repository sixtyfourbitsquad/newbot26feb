"""Handle admin group: reply to forwarded message -> send back to user."""
import logging
from telegram import Update
from telegram.constants import ChatType
from telegram.error import BadRequest, Forbidden
from telegram.ext import ContextTypes

import database as db
from config import ADMIN_GROUP_ID

logger = logging.getLogger(__name__)


async def _send_to_user(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    update: Update,
) -> bool:
    """Send the admin's reply (text or media) to the user. Return True if sent."""
    message = update.message
    if not message:
        return False

    try:
        if message.text:
            await context.bot.send_message(chat_id=user_id, text=message.text)
            return True
        if message.caption is not None and (message.photo or message.video or message.document or message.audio or message.voice):
            # Media with optional caption
            if message.photo:
                await context.bot.send_photo(user_id, photo=message.photo[-1].file_id, caption=message.caption)
            elif message.video:
                await context.bot.send_video(user_id, video=message.video.file_id, caption=message.caption)
            elif message.document:
                await context.bot.send_document(user_id, document=message.document.file_id, caption=message.caption)
            elif message.audio:
                await context.bot.send_audio(user_id, audio=message.audio.file_id, caption=message.caption)
            elif message.voice:
                await context.bot.send_voice(user_id, voice=message.voice.file_id, caption=message.caption)
            else:
                await context.bot.send_message(user_id, text=message.caption)
            return True
        if message.photo:
            await context.bot.send_photo(user_id, photo=message.photo[-1].file_id)
            return True
        if message.video:
            await context.bot.send_video(user_id, video=message.video.file_id)
            return True
        if message.document:
            await context.bot.send_document(user_id, document=message.document.file_id)
            return True
        if message.audio:
            await context.bot.send_audio(user_id, audio=message.audio.file_id)
            return True
        if message.voice:
            await context.bot.send_voice(user_id, voice=message.voice.file_id)
            return True
        if message.sticker:
            await context.bot.send_sticker(user_id, sticker=message.sticker.file_id)
            return True
        if message.video_note:
            await context.bot.send_video_note(user_id, video_note=message.video_note.file_id)
            return True
    except Forbidden as e:
        if "blocked" in str(e).lower() or "user is deactivated" in str(e).lower():
            await db.set_user_blocked(user_id, blocked=True)
            logger.info("Marked user %s as blocked", user_id)
        raise
    except BadRequest as e:
        if "chat not found" in str(e).lower() or "user not found" in str(e).lower():
            await db.set_user_blocked(user_id, blocked=True)
            logger.info("Marked user %s as blocked (chat not found)", user_id)
        raise
    return False


async def handle_admin_group_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """If in admin group and replying to a forwarded message, send reply to that user."""
    if not update.message or not update.message.reply_to_message:
        return
    if update.effective_chat.id != ADMIN_GROUP_ID:
        return
    if update.effective_chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return

    # Need to get target user id; get_user_from_reply is async
    user_id = await db.get_user_from_reply(ADMIN_GROUP_ID, update.message.reply_to_message.message_id)
    if not user_id:
        try:
            if update.message.reply_to_message.forward_origin:
                origin = update.message.reply_to_message.forward_origin
                if type(origin).__name__ == "MessageOriginUser" and getattr(origin, "sender_user", None):
                    user_id = origin.sender_user.id
        except Exception:
            pass
    if not user_id:
        await update.message.reply_text("Could not determine which user to reply to.")
        return

    try:
        sent = await _send_to_user(context, user_id, update)
        if sent:
            await update.message.reply_text("✅ Sent to user.")
    except Forbidden as e:
        await update.message.reply_text("❌ User has blocked the bot or deactivated.")
    except BadRequest as e:
        await update.message.reply_text(f"❌ Could not deliver: {e.message}")
    except Exception as e:
        logger.exception("Error sending reply to user: %s", e)
        await update.message.reply_text("❌ Failed to send.")
