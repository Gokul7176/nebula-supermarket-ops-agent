import os
import logging
import asyncio
from typing import Dict, List, Any
from telegram import Update
from telegram.ext import ContextTypes

from src.bot.idempotency import check_and_start_update, mark_update_succeeded, mark_update_failed
from src.agent.loop import process_user_message_agent

logger = logging.getLogger(__name__)

# In-memory store for Telegram chat LLM conversation context
CONVERSATION_HISTORIES: Dict[str, List[Dict[str, Any]]] = {}

def clear_chat_conversation_history(chat_id: str) -> None:
    """Clears ONLY in-memory LLM conversation context for a chat. Does not touch DB state."""
    CONVERSATION_HISTORIES[chat_id] = []

async def handle_telegram_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles incoming Telegram natural language messages for store operations."""
    if not update.message or not update.message.text:
        return

    update_id = update.update_id
    user_text = update.message.text.strip()
    chat_id = str(update.effective_chat.id) if update.effective_chat else "default"

    # 1. Idempotency Check
    action, cached_result = check_and_start_update(update_id)

    if action == "SKIP_CACHED":
        logger.info(f"Replaying cached response for update_id #{update_id}")
        await update.message.reply_text(cached_result or "Request processed previously.")
        return
    elif action == "SKIP_IN_FLIGHT":
        logger.info(f"Ignoring in-flight duplicate update_id #{update_id}")
        return

    # Handle /new command: Reset LLM conversation history for this chat
    if user_text.lower() == "/new":
        clear_chat_conversation_history(chat_id)
        reply_msg = "Conversation context cleared. Active draft bill and store data remain intact."
        await update.message.reply_text(reply_msg)
        mark_update_succeeded(update_id, reply_msg)
        return

    # 2. Process Message via Pure Agentic Control Loop
    try:
        chat_history = CONVERSATION_HISTORIES.get(chat_id, [])
        reply_text, file_paths = await asyncio.to_thread(
            process_user_message_agent,
            user_text,
            conversation_history=chat_history,
            chat_id=chat_id
        )

        # Update in-memory conversation history
        if chat_id not in CONVERSATION_HISTORIES:
            CONVERSATION_HISTORIES[chat_id] = []
        CONVERSATION_HISTORIES[chat_id].append({"role": "user", "text": user_text})
        CONVERSATION_HISTORIES[chat_id].append({"role": "model", "text": reply_text})

        # Limit window size to 20 messages
        if len(CONVERSATION_HISTORIES[chat_id]) > 20:
            CONVERSATION_HISTORIES[chat_id] = CONVERSATION_HISTORIES[chat_id][-20:]

        # Send Text Response to Telegram
        await update.message.reply_text(reply_text)

        # Send any generated document files (PDF Invoice / PPTX Deck)
        for fpath in file_paths:
            if os.path.exists(fpath):
                try:
                    with open(fpath, "rb") as doc_file:
                        await update.message.reply_document(
                            document=doc_file,
                            filename=os.path.basename(fpath)
                        )
                except Exception as doc_err:
                    err_str = str(doc_err).lower()
                    if "timed out" in err_str or "timeout" in err_str:
                        logger.warning(
                            f"Document delivery confirmation timed out for {fpath}: {doc_err}"
                        )
                    else:
                        raise

        # Mark update succeeded
        mark_update_succeeded(update_id, reply_text)

    except Exception as e:
        logger.error(f"Error handling update_id #{update_id}: {e}", exc_info=True)
        err_response = f"⚠️ Store Agent encountered an error: {str(e)}"
        await update.message.reply_text(err_response)
        mark_update_failed(update_id, str(e))
