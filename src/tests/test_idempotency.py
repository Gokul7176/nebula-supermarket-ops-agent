import os
import tempfile
import pytest
from src.db.connection import get_db_connection
from src.db.init_db import init_db
from src.bot.idempotency import check_and_start_update, mark_update_succeeded, mark_update_failed

@pytest.fixture
def test_db(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_idempotency.db")
        init_db(db_path)
        monkeypatch.setenv("DB_PATH", db_path)
        yield db_path

def test_telegram_update_idempotency_flow(test_db):
    update_id = 998877

    # 1. First arrival -> PROCEED
    action1, _ = check_and_start_update(update_id)
    assert action1 == "PROCEED"

    # 2. In-flight duplicate arrival -> SKIP_IN_FLIGHT
    action2, _ = check_and_start_update(update_id)
    assert action2 == "SKIP_IN_FLIGHT"

    # 3. Mark succeeded
    mark_update_succeeded(update_id, "Result Text Output")

    # 4. Subsequent duplicate arrival -> SKIP_CACHED with cached result
    action3, cached_res = check_and_start_update(update_id)
    assert action3 == "SKIP_CACHED"
    assert cached_res == "Result Text Output"

def test_failed_update_allows_retry(test_db):
    update_id = 112233

    # First arrival -> PROCEED
    action1, _ = check_and_start_update(update_id)
    assert action1 == "PROCEED"

    # Exception occurs -> mark failed
    mark_update_failed(update_id, "Database timeout error")

    # Retry arrival -> PROCEED (retry allowed)
    action2, _ = check_and_start_update(update_id)
    assert action2 == "PROCEED"

@pytest.mark.asyncio
async def test_document_timeout_suppression_in_handler(test_db, monkeypatch):
    from unittest.mock import AsyncMock, MagicMock
    from src.bot.handlers import handle_telegram_message

    tmp_file = os.path.join(os.path.dirname(test_db), "test_deck.pptx")
    with open(tmp_file, "w") as f:
        f.write("dummy pptx content")

    monkeypatch.setattr(
        "src.bot.handlers.process_user_message_agent",
        lambda user_text, conversation_history=None, chat_id="default": (
            "Here is your sales analysis deck.",
            [tmp_file]
        )
    )

    update = MagicMock()
    update.update_id = 777888
    update.message.text = "Generate today's sales analysis deck"
    update.effective_chat.id = 12345
    update.message.reply_text = AsyncMock()

    import telegram.error
    update.message.reply_document = AsyncMock(side_effect=telegram.error.TimedOut("Timed out"))

    await handle_telegram_message(update, None)

    update.message.reply_text.assert_called_with("Here is your sales analysis deck.", parse_mode="HTML")

    for call in update.message.reply_text.call_args_list:
        assert "Store Agent encountered an error" not in str(call)

    with get_db_connection(test_db) as conn:
        row = conn.execute("SELECT status FROM processed_updates WHERE telegram_update_id = 777888").fetchone()
        assert row["status"] == "succeeded"

def test_clean_markdown_formatting():
    from src.bot.handlers import clean_markdown

    raw_input = (
        "## Daily Sales Summary\n"
        "**Products Sold:**\n"
        "1. **Aashirvaad Atta 5kg:** 1 unit sold\n\n"
        "__Note__: Payment via `UPI`\n"
        "```text\n"
        "Bill #1 finalized\n"
        "```"
    )

    expected_output = (
        "Daily Sales Summary\n"
        "Products Sold:\n"
        "1. Aashirvaad Atta 5kg: 1 unit sold\n\n"
        "Note: Payment via UPI\n"
        "Bill #1 finalized"
    )

    cleaned = clean_markdown(raw_input)
    assert cleaned == expected_output
    assert "##" not in cleaned
    assert "**" not in cleaned
    assert "__" not in cleaned
    assert "`" not in cleaned

def test_format_telegram_html():
    from src.bot.handlers import format_telegram_html

    raw_input = (
        "## Daily Sales Summary\n"
        "Total Sales Revenue: ₹414.26\n"
        "Total Finalized Bills: 7\n"
        "Total Tax Collected: ₹26.26\n\n"
        "## Products Sold\n"
        "* Aashirvaad Atta 5kg <v1> & Brand — 1 unit\n"
        "* Maggi 70g — 7 units\n\n"
        "## Payment Mode\n"
        "- Cash — ₹351.54\n"
        "- UPI — ₹62.72\n\n"
        "Report path: C:\\nebula\\output\\invoice_bill_1.pdf"
    )

    formatted = format_telegram_html(raw_input)

    # 1. Headings become bold HTML headings with contextual emojis
    assert "<b>📊 Daily Sales Summary</b>" in formatted
    assert "<b>📦 Products Sold</b>" in formatted
    # 2. Labels/Totals bolded
    assert "<b>Total Sales Revenue:</b> ₹414.26" in formatted
    # 3. Raw ## and ** removed
    assert "##" not in formatted
    assert "**" not in formatted
    # 4. ₹ unchanged
    assert "₹414.26" in formatted
    assert "₹351.54" in formatted
    # 5. Bullets converted to •
    assert "• Aashirvaad Atta 5kg &lt;v1&gt; &amp; Brand — 1 unit" in formatted
    assert "• Maggi 70g — 7 units" in formatted
    # 6. <, >, & safely escaped
    assert "&lt;v1&gt; &amp; Brand" in formatted
    assert "<v1>" not in formatted
    # 7. Filenames and paths intact
    assert "C:\\nebula\\output\\invoice_bill_1.pdf" in formatted
