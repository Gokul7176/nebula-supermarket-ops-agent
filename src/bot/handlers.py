import re
import os
import html
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

def format_telegram_html(text: str) -> str:
    """
    Formats AI text output into clean, elegant Telegram HTML:
    - Normalizes backslash-escaped Markdown tokens (\\**, \\---, \\#, \\_) while preserving file paths.
    - Normalizes legacy HTML tags (<b>, <strong>, &lt;b&gt;) to avoid double-escaping.
    - Removes horizontal rule separators (---, ────).
    - Converts Markdown headings (# Heading, ## Heading) -> <b>[Emoji] Heading</b>
    - Converts standalone section headers (Items Sold, Payment Breakdown, Bill #5 — Madhavan) -> <b>[Emoji] Header</b>
    - Formats key labels (Label: value) -> <b>Label:</b> value
    - Converts bullet list items (* or -) -> • 
    - Removes raw Markdown markers (##, **, __, `)
    """
    if not text:
        return ""

    # 1. Normalize escaped HTML entities like &lt;b&gt; or &lt;strong&gt; first if present
    text = re.sub(r'&lt;b&gt;(.*?)&lt;/b&gt;', r'**\1**', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'&lt;strong&gt;(.*?)&lt;/strong&gt;', r'**\1**', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'&lt;code&gt;(.*?)&lt;/code&gt;', r'`\1`', text, flags=re.IGNORECASE | re.DOTALL)

    # Normalize existing raw supported HTML tags like <b>, <strong>, or <code>
    text = re.sub(r'<(b|strong)>(.*?)</\1>', r'**\2**', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'<code>(.*?)</code>', r'`\1`', text, flags=re.IGNORECASE | re.DOTALL)

    # 2. Normalize backslash-escaped Markdown characters without touching Windows file paths
    text = re.sub(r'\\(\*\*|---|#|_|`|\*)', r'\1', text)

    # 3. Remove code fence markers (e.g. ```markdown\n...``` -> ...)
    cleaned = re.sub(r'```[a-zA-Z]*\n?', '', text)
    cleaned = cleaned.replace('```', '')

    lines = cleaned.splitlines()
    formatted_lines = []

    HEADER_KEYWORDS = [
        'daily sales summary', 'sales summary', 'sales overview', 'overview',
        'items sold', 'sold items', 'products sold', 'payment breakdown',
        'payment mode breakdown', 'payment mode split', 'inventory',
        'stock health', 'stock warning', 'stock check', 'khata', 'khata balance',
        'store operations analysis', 'executive summary'
    ]

    has_sales_header = False
    for line in lines:
        l_str = line.strip()
        l_clean = re.sub(r'^[^\w#]+', '', l_str).lower().rstrip(':').strip()
        if l_str.startswith('#') and any(k in l_str.lower() for k in ['sales overview', 'sales summary', 'daily sales summary', 'sales report']):
            has_sales_header = True
            break
        if l_clean in ['sales overview', 'sales summary', 'daily sales summary', 'sales report', 'executive summary']:
            has_sales_header = True
            break

    for line in lines:
        line_str = line.strip()
        if not line_str:
            formatted_lines.append("")
            continue

        # Skip horizontal rule separator lines (e.g. ---, \---, ────)
        if re.match(r'^[ \t]*[-─—]+[ \t]*$', line_str):
            continue

        # Auto-insert <b>📊 Sales Overview</b> before first sales totals line if no sales header exists
        if not has_sales_header:
            if re.search(r'\b(total sales revenue|total revenue|finalized bills|total finalized bills|total tax collected)\b', line_str, re.IGNORECASE):
                formatted_lines.append("<b>📊 Sales Overview</b>")
                has_sales_header = True

        # Check if line is a header (# Heading, ## Heading, ### Heading)
        header_match = re.match(r'^#+[ \t]*(.*)', line_str)
        if header_match:
            header_text = header_match.group(1).strip()
            header_text = re.sub(r'\*\*(.*?)\*\*', r'\1', header_text)
            escaped_header = html.escape(header_text)

            emoji = ""
            h_lower = header_text.lower()
            if not any(c in header_text for c in ['📊', '🧾', '📦', '💳', '💰', '⚠️', '✅']):
                if any(k in h_lower for k in ['warning', 'error', 'refusal', 'caution', 'below cost', 'oversell']):
                    emoji = "⚠️ "
                elif any(k in h_lower for k in ['payment']):
                    emoji = "💳 "
                elif any(k in h_lower for k in ['sales', 'summary', 'overview', 'report', 'close', 'daily', 'deck', 'analysis']):
                    emoji = "📊 "
                elif any(k in h_lower for k in ['bill', 'invoice', 'draft']):
                    emoji = "🧾 "
                elif any(k in h_lower for k in ['stock', 'inventory', 'product', 'item']):
                    emoji = "📦 "
                elif any(k in h_lower for k in ['khata', 'balance', 'credit', 'ledger']):
                    emoji = "💰 "
                elif any(k in h_lower for k in ['success', 'created', 'finalized', 'added']):
                    emoji = "✅ "

            formatted_lines.append(f"<b>{emoji}{escaped_header}</b>")
            continue

        # Check if line is a standalone section header (e.g. Items Sold, Payment Breakdown, Bill #5 — Madhavan)
        clean_line_text = re.sub(r'\*\*(.*?)\*\*', r'\1', line_str).strip()
        clean_lower = clean_line_text.lower()
        # Normalize for keyword matching by stripping leading emojis/symbols and trailing colons
        clean_lower_normalized = re.sub(r'^[^\w#]+', '', clean_lower).rstrip(':').strip()

        is_standalone_header = False
        if clean_lower in HEADER_KEYWORDS or clean_lower.rstrip(':') in HEADER_KEYWORDS or clean_lower_normalized in HEADER_KEYWORDS:
            is_standalone_header = True
        elif re.match(r'^(?:[^\w#]+\s*)?bill\s*#?\d+', clean_lower):
            is_standalone_header = True

        if is_standalone_header and not clean_line_text.startswith("• "):
            escaped_title = html.escape(clean_line_text)
            emoji = ""
            if not any(c in clean_line_text for c in ['📊', '🧾', '📦', '💳', '💰', '⚠️', '✅']):
                if any(k in clean_lower for k in ['warning', 'error', 'refusal', 'caution', 'below cost', 'oversell']):
                    emoji = "⚠️ "
                elif any(k in clean_lower for k in ['payment']):
                    emoji = "💳 "
                elif any(k in clean_lower for k in ['sales', 'summary', 'overview', 'report', 'close', 'daily']):
                    emoji = "📊 "
                elif any(k in clean_lower for k in ['bill', 'invoice', 'draft']):
                    emoji = "🧾 "
                elif any(k in clean_lower for k in ['stock', 'inventory', 'product', 'item']):
                    emoji = "📦 "
                elif any(k in clean_lower for k in ['khata', 'balance', 'credit', 'ledger']):
                    emoji = "💰 "
                elif any(k in clean_lower for k in ['success', 'created', 'finalized', 'added']):
                    emoji = "✅ "

            formatted_lines.append(f"<b>{emoji}{escaped_title}</b>")
            continue

        # Check if line is a bullet item (* item or - item or • item)
        bullet_prefix = ""
        if re.match(r'^[*-][ \t]+', line_str):
            bullet_prefix = "• "
            line_content = re.sub(r'^[*-][ \t]+', '', line_str)
        elif line_str.startswith("• "):
            bullet_prefix = "• "
            line_content = line_str[2:]
        else:
            line_content = line_str

        # Parse inline markdown elements: **bold**, __italic__, _italic_, `code`
        parts = re.split(r'(\*\*.*?\*\*|__.*?__|(?<![a-zA-Z0-9])_.*?_(?![a-zA-Z0-9])|`.*?`)', line_content)
        line_out = []
        for part in parts:
            if part.startswith("**") and part.endswith("**") and len(part) >= 4:
                inner = part[2:-2]
                line_out.append(f"<b>{html.escape(inner)}</b>")
            elif part.startswith("__") and part.endswith("__") and len(part) >= 4:
                inner = part[2:-2]
                line_out.append(f"<b>{html.escape(inner)}</b>")
            elif part.startswith("_") and part.endswith("_") and len(part) >= 2:
                inner = part[1:-1]
                line_out.append(f"<b>{html.escape(inner)}</b>")
            elif part.startswith("`") and part.endswith("`") and len(part) >= 2:
                inner = part[1:-1]
                line_out.append(f"<code>{html.escape(inner)}</code>")
            else:
                line_out.append(html.escape(part))

        processed_str = "".join(line_out)

        # General Label Detection: Bold any line (or bullet content) that starts with "Label:"
        if not processed_str.startswith("<b>"):
            label_match = re.match(r'^([A-Za-z0-9\s/#—()_-]+:)(.*)', processed_str)
            if label_match:
                lbl = label_match.group(1)
                rest = label_match.group(2)
                processed_str = f"<b>{lbl}</b>{rest}"

        formatted_lines.append(f"{bullet_prefix}{processed_str}")

    return "\n".join(formatted_lines).strip()

def clean_markdown(text: str) -> str:
    """
    Cleans raw Markdown formatting syntax from AI responses for plain text presentation:
    - Normalizes backslash-escaped Markdown tokens (\\**, \\---, \\#, \\_) while preserving file paths.
    - Removes horizontal rule separators (---, ────).
    - Strips legacy HTML tags (<b>, <strong>, <code>, &lt;b&gt;).
    - Headings (# Heading, ## Heading, etc.) -> Heading
    - Bold markers (**text**) -> text
    - Underscore emphasis (__text__ / _text_) -> text
    - Inline code (`text`) -> text
    - Code fences (```text ... ```) -> inner content
    - Preserves clean line breaks and list structures.
    """
    if not text:
        return ""

    # Normalize escaped HTML entities & raw tags
    text = re.sub(r'&lt;/?(b|strong|code)&gt;', '', text, flags=re.IGNORECASE)
    text = re.sub(r'</?(b|strong|code)>', '', text, flags=re.IGNORECASE)

    # Normalize backslash-escaped Markdown characters without touching file paths
    text = re.sub(r'\\(\*\*|---|#|_|`|\*)', r'\1', text)

    cleaned = re.sub(r'```[a-zA-Z]*\n?', '', text)
    cleaned = cleaned.replace('```', '')

    lines = cleaned.splitlines()
    processed_lines = []
    for line in lines:
        line_str = line.rstrip()
        if re.match(r'^[ \t]*[-─—]+[ \t]*$', line_str):
            continue
        line_str = re.sub(r'^[ \t]*#+[ \t]*', '', line_str)
        processed_lines.append(line_str)

    cleaned = "\n".join(processed_lines)
    cleaned = re.sub(r'\*\*(.*?)\*\*', r'\1', cleaned)
    cleaned = re.sub(r'__(.*?)__', r'\1', cleaned)
    cleaned = re.sub(r'(?<![a-zA-Z0-9])_(.*?)_(?![a-zA-Z0-9])', r'\1', cleaned)
    cleaned = re.sub(r'`([^`\n]+)`', r'\1', cleaned)

    return cleaned.strip()

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
        try:
            await update.message.reply_text(cached_result or "Request processed previously.", parse_mode="HTML")
        except Exception:
            await update.message.reply_text(clean_markdown(cached_result or "Request processed previously."))
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

        formatted_reply = format_telegram_html(reply_text)

        # Update in-memory conversation history - STORE RAW reply_text NOT formatted_reply
        if chat_id not in CONVERSATION_HISTORIES:
            CONVERSATION_HISTORIES[chat_id] = []
        CONVERSATION_HISTORIES[chat_id].append({"role": "user", "text": user_text})
        CONVERSATION_HISTORIES[chat_id].append({"role": "model", "text": reply_text})

        # Limit window size to 20 messages
        if len(CONVERSATION_HISTORIES[chat_id]) > 20:
            CONVERSATION_HISTORIES[chat_id] = CONVERSATION_HISTORIES[chat_id][-20:]

        # Send Text Response to Telegram with HTML parse_mode (with fallback to plain text if malformed)
        try:
            await update.message.reply_text(formatted_reply, parse_mode="HTML")
        except Exception as html_err:
            logger.warning(f"Failed to send HTML response ({html_err}), falling back to plain text")
            await update.message.reply_text(clean_markdown(reply_text))

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
        mark_update_succeeded(update_id, formatted_reply)

    except Exception as e:
        logger.error(f"Error handling update_id #{update_id}: {e}", exc_info=True)
        err_response = f"⚠️ Store Agent encountered an error: {str(e)}"
        await update.message.reply_text(err_response)
        mark_update_failed(update_id, str(e))
