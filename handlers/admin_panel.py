"""Admin panel: /panel with inline keyboard and callback handlers. Admin-only access control."""
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler, MessageHandler, filters

import database as db
from config import ADMIN_GROUP_ID, ADMIN_USER_IDS
from broadcast import run_broadcast

logger = logging.getLogger(__name__)


def _is_admin(user_id: int | None) -> bool:
    """Allow panel/broadcast only for ADMIN_USER_IDS. If ADMIN_USER_IDS is empty, allow any user in admin group."""
    if user_id is None:
        return False
    if not ADMIN_USER_IDS:
        return True
    return user_id in ADMIN_USER_IDS


CALLBACK_BROADCAST = "panel:broadcast"
CALLBACK_STATS = "panel:stats"
CALLBACK_SET_WELCOME = "panel:set_welcome"
CALLBACK_CLEANUP = "panel:cleanup"


def _admin_group_filter():
    return filters.Chat(ADMIN_GROUP_ID)


def _panel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Broadcast", callback_data=CALLBACK_BROADCAST)],
        [InlineKeyboardButton("📊 Stats", callback_data=CALLBACK_STATS)],
        [InlineKeyboardButton("📝 Set Welcome", callback_data=CALLBACK_SET_WELCOME)],
        [InlineKeyboardButton("🧹 Cleanup", callback_data=CALLBACK_CLEANUP)],
    ])


async def cmd_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show admin panel only in admin group; admin-only if ADMIN_USER_IDS is set.
    Works in GROUP and SUPERGROUP. Supports /panel and /panel@bot_username.
    """
    effective_chat_id = update.effective_chat.id if update.effective_chat else None
    effective_user_id = update.effective_user.id if update.effective_user else None
    logger.info(
        "[PANEL] cmd_panel triggered: effective_chat.id=%s effective_user.id=%s",
        effective_chat_id,
        effective_user_id,
    )

    if update.effective_chat and update.effective_chat.id != ADMIN_GROUP_ID:
        return
    if not _is_admin(effective_user_id):
        if ADMIN_USER_IDS:
            logger.warning(
                "[PANEL] User not authorized: user_id=%s not in ADMIN_USER_IDS (ADMIN_USER_IDS is set)",
                effective_user_id,
            )
        await update.message.reply_text("Access denied. Admin only.")
        return
    await update.message.reply_text(
        "Admin Panel",
        reply_markup=_panel_keyboard(),
    )


async def callback_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ask admin to send the broadcast message. Admin-only."""
    if update.effective_chat and update.effective_chat.id != ADMIN_GROUP_ID:
        return
    if not _is_admin(update.effective_user.id if update.effective_user else None):
        await update.callback_query.answer("Access denied. Admin only.", show_alert=True)
        if ADMIN_USER_IDS:
            logger.warning(
                "[PANEL] Broadcast callback: user_id=%s not in ADMIN_USER_IDS",
                update.effective_user.id if update.effective_user else None,
            )
        return
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        "📢 Send the message you want to broadcast (text or any media). "
        "It will be sent to all non-blocked users."
    )
    context.user_data["awaiting_broadcast"] = True


async def callback_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show total, active 7d, blocked counts. Admin-only."""
    if not _is_admin(update.effective_user.id if update.effective_user else None):
        await update.callback_query.answer("Access denied. Admin only.", show_alert=True)
        if ADMIN_USER_IDS:
            logger.warning(
                "[PANEL] Stats callback: user_id=%s not in ADMIN_USER_IDS",
                update.effective_user.id if update.effective_user else None,
            )
        return
    await update.callback_query.answer()
    stats = await db.get_stats()
    text = (
        f"📊 Stats\n"
        f"Total users: {stats['total']}\n"
        f"Active (7 days): {stats['active_7d']}\n"
        f"Blocked: {stats['blocked']}"
    )
    await update.callback_query.edit_message_text(text, reply_markup=_panel_keyboard())


async def callback_set_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ask admin to send new welcome message. Admin-only."""
    if not _is_admin(update.effective_user.id if update.effective_user else None):
        await update.callback_query.answer("Access denied. Admin only.", show_alert=True)
        if ADMIN_USER_IDS:
            logger.warning(
                "[PANEL] Set Welcome callback: user_id=%s not in ADMIN_USER_IDS",
                update.effective_user.id if update.effective_user else None,
            )
        return
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        "📝 Send the new welcome message (text or one media: photo, video, document, audio)."
    )
    context.user_data["awaiting_welcome"] = True


async def callback_cleanup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Delete all blocked users from DB. Admin-only."""
    if not _is_admin(update.effective_user.id if update.effective_user else None):
        await update.callback_query.answer("Access denied. Admin only.", show_alert=True)
        if ADMIN_USER_IDS:
            logger.warning(
                "[PANEL] Cleanup callback: user_id=%s not in ADMIN_USER_IDS",
                update.effective_user.id if update.effective_user else None,
            )
        return
    await update.callback_query.answer()
    deleted = await db.cleanup_blocked_users()
    await update.callback_query.edit_message_text(
        f"🧹 Cleanup done. Removed {deleted} blocked user(s).",
        reply_markup=_panel_keyboard(),
    )


async def handle_admin_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle message in admin group: either broadcast content or welcome content. Admin-only for these actions.
    Temporary: log every incoming group message here to confirm bot receives updates.
    """
    if not update.message or not update.effective_chat:
        return
    if update.effective_chat.id != ADMIN_GROUP_ID:
        return

    # Temporary: log every incoming group message to confirm bot receives updates
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id if update.effective_user else None
    msg_id = update.message.message_id
    text = (update.message.text or update.message.caption or "(no text)")[:80]
    chat_type = getattr(update.effective_chat, "type", None)
    logger.info(
        "[GROUP_MSG] chat_id=%s chat_type=%s user_id=%s message_id=%s text=%s",
        chat_id, chat_type, user_id, msg_id, repr(text),
    )

    if context.user_data.get("awaiting_broadcast"):
        if not _is_admin(update.effective_user.id if update.effective_user else None):
            context.user_data["awaiting_broadcast"] = False
            if ADMIN_USER_IDS:
                logger.warning(
                    "[PANEL] Broadcast message rejected: user_id=%s not in ADMIN_USER_IDS",
                    update.effective_user.id if update.effective_user else None,
                )
            await update.message.reply_text("Access denied. Admin only.")
            return
        context.user_data["awaiting_broadcast"] = False
        await _start_broadcast(update, context)
        return

    if context.user_data.get("awaiting_welcome"):
        if not _is_admin(update.effective_user.id if update.effective_user else None):
            context.user_data["awaiting_welcome"] = False
            if ADMIN_USER_IDS:
                logger.warning(
                    "[PANEL] Welcome message rejected: user_id=%s not in ADMIN_USER_IDS",
                    update.effective_user.id if update.effective_user else None,
                )
            await update.message.reply_text("Access denied. Admin only.")
            return
        context.user_data["awaiting_welcome"] = False
        await _store_welcome(update, context)
        return


async def _store_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Store welcome message payload in settings."""
    msg = update.message
    payload = None
    if msg.text:
        payload = {"type": "text", "text": msg.text}
    elif msg.photo:
        payload = {"type": "photo", "file_id": msg.photo[-1].file_id, "caption": msg.caption or ""}
    elif msg.video:
        payload = {"type": "video", "file_id": msg.video.file_id, "caption": msg.caption or ""}
    elif msg.document:
        payload = {"type": "document", "file_id": msg.document.file_id, "caption": msg.caption or ""}
    elif msg.audio:
        payload = {"type": "audio", "file_id": msg.audio.file_id, "caption": msg.caption or ""}
    elif msg.voice:
        payload = {"type": "voice", "file_id": msg.voice.file_id, "caption": msg.caption or ""}
    if payload:
        await db.set_setting("welcome_message", payload)
        await msg.reply_text("✅ Welcome message updated.", reply_markup=_panel_keyboard())
    else:
        await msg.reply_text("Unsupported message type. Send text or one media (photo/video/document/audio/voice).", reply_markup=_panel_keyboard())


async def _start_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Store broadcast message and run broadcast in background; progress to admin group."""
    msg = update.message
    admin_chat_id = ADMIN_GROUP_ID

    # Build payload for sending (same as welcome: text or one media)
    payload = _message_to_payload(msg)
    if not payload:
        await msg.reply_text("Unsupported message type for broadcast. Use text or one media.")
        return

    user_ids = await db.get_all_active_user_ids()
    total = len(user_ids)
    if total == 0:
        await msg.reply_text("No users to broadcast to.")
        return

    broadcast_id = await db.create_broadcast(total)
    await msg.reply_text(f"📢 Broadcasting to {total} users…")

    # run_broadcast starts its own background task and uses copy_message when source is provided
    run_broadcast(
        context.bot,
        user_ids,
        payload,
        broadcast_id,
        admin_chat_id,
        source_chat_id=msg.chat_id,
        source_message_id=msg.message_id,
    )


def _message_to_payload(msg) -> dict | None:
    """Convert message to broadcast payload (type, file_id, text, caption)."""
    if msg.text:
        return {"type": "text", "text": msg.text}
    if msg.caption is not None:
        cap = msg.caption
    else:
        cap = ""
    if msg.photo:
        return {"type": "photo", "file_id": msg.photo[-1].file_id, "caption": cap}
    if msg.video:
        return {"type": "video", "file_id": msg.video.file_id, "caption": cap}
    if msg.document:
        return {"type": "document", "file_id": msg.document.file_id, "caption": cap}
    if msg.audio:
        return {"type": "audio", "file_id": msg.audio.file_id, "caption": cap}
    if msg.voice:
        return {"type": "voice", "file_id": msg.voice.file_id, "caption": cap}
    if msg.sticker:
        return {"type": "sticker", "file_id": msg.sticker.file_id, "caption": cap}
    if msg.video_note:
        return {"type": "video_note", "file_id": msg.video_note.file_id, "caption": cap}
    return None
