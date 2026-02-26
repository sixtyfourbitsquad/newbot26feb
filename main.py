"""Production-ready Telegram support + broadcast bot (bot_1)."""
import logging
import sys

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

import database as db
from config import BOT_TOKEN, ADMIN_GROUP_ID
from handlers.start import send_welcome
from handlers.private_messages import handle_private_message
from handlers.admin_group import handle_admin_group_reply
from handlers.admin_panel import (
    cmd_panel,
    callback_broadcast,
    callback_stats,
    callback_set_welcome,
    callback_cleanup,
    handle_admin_message,
)

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
    stream=sys.stdout,
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log and suppress errors so the bot keeps running."""
    logger.exception(
        "Update %s caused error: %s",
        update,
        context.error,
        exc_info=context.error,
    )
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "An error occurred. Please try again later."
            )
        except Exception:
            pass


def main() -> None:
    application = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )

    application.add_handler(CommandHandler("start", send_welcome))
    application.add_handler(
        MessageHandler(
            filters.Chat(ADMIN_GROUP_ID) & filters.REPLY,
            handle_admin_group_reply,
        )
    )
    application.add_handler(
        MessageHandler(filters.Chat(ADMIN_GROUP_ID), handle_admin_message)
    )
    application.add_handler(
        CommandHandler("panel", cmd_panel, filters=filters.Chat(ADMIN_GROUP_ID))
    )
    application.add_handler(CallbackQueryHandler(callback_broadcast, pattern="^panel:broadcast$"))
    application.add_handler(CallbackQueryHandler(callback_stats, pattern="^panel:stats$"))
    application.add_handler(CallbackQueryHandler(callback_set_welcome, pattern="^panel:set_welcome$"))
    application.add_handler(CallbackQueryHandler(callback_cleanup, pattern="^panel:cleanup$"))
    application.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE & ~filters.COMMAND,
            handle_private_message,
        )
    )

    application.add_error_handler(global_error_handler)

    application.run_polling(allowed_updates=Update.ALL_TYPES)


async def _post_init(application) -> None:
    await db.init_db()


async def _post_shutdown(application) -> None:
    await db.close_pool()


if __name__ == "__main__":
    main()
