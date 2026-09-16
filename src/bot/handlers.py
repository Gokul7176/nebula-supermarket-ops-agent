import os
import logging
from telegram import Update
from telegram.ext import ContextTypes

from src.bot.idempotency import check_and_start_update, mark_update_succeeded, mark_update_failed
from src.agent.loop import process_user_message_agent

logger = logging.getLogger(__name__)

async def handle_telegram_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles incoming Telegram natural language messages for store operations."""
    if not update.message or not update.message.text:
        return

    update_id = update.update_id
    user_text = update.message.text.strip()

    # 1. Idempotency Check
    action, cached_result = check_and_start_update(update_id)

    if action == "SKIP_CACHED":
        logger.info(f"Replaying cached response for update_id #{update_id}")
        await update.message.reply_text(cached_result or "Request processed previously.")
        return
    elif action == "SKIP_IN_FLIGHT":
        logger.info(f"Ignoring in-flight duplicate update_id #{update_id}")
        return

    # 2. Process Message via Pure Agentic Control Loop
    try:
        reply_text, file_paths = process_user_message_agent(user_text)

        # Send Text Response to Telegram
        await update.message.reply_text(reply_text)

        # Send any generated document files (PDF Invoice / PPTX Deck)
        for fpath in file_paths:
            if os.path.exists(fpath):
                with open(fpath, "rb") as doc_file:
                    await update.message.reply_document(document=doc_file, filename=os.path.basename(fpath))

        # Mark update succeeded
        mark_update_succeeded(update_id, reply_text)

    except Exception as e:
        logger.error(f"Error handling update_id #{update_id}: {e}", exc_info=True)
        err_response = f"⚠️ Store Agent encountered an error: {str(e)}"
        await update.message.reply_text(err_response)
        mark_update_failed(update_id, str(e))
