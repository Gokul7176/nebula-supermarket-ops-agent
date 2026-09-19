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

def test_escaped_markdown_normalization():
    from src.bot.handlers import format_telegram_html, clean_markdown

    live_regression_input = (
        "\\# Daily Sales Summary\n"
        "• \\**Total Sales Revenue:\\** ₹492.66\n"
        "• \\**Finalized Bills:\\** 8\n"
        "• \\**Total Tax Collected:\\** ₹34.66\n\n"
        "\\---\n\n"
        "\\**📦 Items Sold:\\**\n"
        "• \\**Aashirvaad Atta 5kg:\\** 1 sold — ₹304.50\n"
        "• \\**Maggi 70g:\\** 12 sold — ₹188.16\n\n"
        "\\**Payment Breakdown:\\**\n"
        "• \\**Cash:\\** ₹429.94\n"
        "• \\**UPI:\\** ₹62.72\n"
        "Path: C:\\Users\\Test\\file.pdf"
    )

    formatted = format_telegram_html(live_regression_input)

    # A. Escaped bold becomes <b>
    assert "<b>Total Sales Revenue:</b> ₹492.66" in formatted
    # B. Escaped heading becomes bold HTML heading with emoji
    assert "<b>📊 Daily Sales Summary</b>" in formatted
    # C. Escaped horizontal rule is removed
    assert "---" not in formatted
    # E. Legitimate backslashes in Windows file paths are preserved
    assert "C:\\Users\\Test\\file.pdf" in formatted
    # F. Telegram HTML output contains no malformed \<b>, \</b>, \**, \---
    assert "\\<b>" not in formatted
    assert "\\</b>" not in formatted
    assert "\\**" not in formatted
    assert "\\---" not in formatted

    # Test clean_markdown fallback path
    cleaned = clean_markdown(live_regression_input)
    assert "\\**" not in cleaned
    assert "\\---" not in cleaned
    assert "Total Sales Revenue:" in cleaned
    assert "C:\\Users\\Test\\file.pdf" in cleaned

@pytest.mark.asyncio
async def test_conversation_history_stores_raw_reply_text(test_db, monkeypatch):
    from unittest.mock import AsyncMock, MagicMock
    from src.bot.handlers import handle_telegram_message, CONVERSATION_HISTORIES

    raw_agent_reply = "Here is your summary:\n## Daily Sales Summary\n**Total:** ₹100"

    monkeypatch.setattr(
        "src.bot.handlers.process_user_message_agent",
        lambda user_text, conversation_history=None, chat_id="default": (
            raw_agent_reply,
            []
        )
    )

    update = MagicMock()
    update.update_id = 889900
    update.message.text = "Show sales"
    update.effective_chat.id = 998877
    update.message.reply_text = AsyncMock()

    await handle_telegram_message(update, None)

    # Verify that stored conversation history contains raw_agent_reply, NOT formatted HTML
    history = CONVERSATION_HISTORIES.get("998877", [])
    assert len(history) >= 2
    model_msg = [m for m in history if m["role"] == "model"][-1]
    assert model_msg["text"] == raw_agent_reply
    assert "<b>" not in model_msg["text"]

def test_comprehensive_telegram_html_formatting_cases():
    from src.bot.handlers import format_telegram_html

    # 1. General labels bolding
    out1 = format_telegram_html("Finalized Bills: 8")
    assert "<b>Finalized Bills:</b> 8" in out1

    # 2. Bullet labels bolding
    out2 = format_telegram_html("• Cash: ₹351.54")
    assert "• <b>Cash:</b> ₹351.54" in out2

    # 3. Standalone section titles (with and without emoji prefixes)
    out3 = format_telegram_html("📊 Sales Overview\n📦 Items Sold\nPayment Breakdown\nBill #5 — Madhavan\nInventory\nStock Warning")
    assert "<b>📊 Sales Overview</b>" in out3
    assert "<b>📦 Items Sold</b>" in out3
    assert "<b>💳 Payment Breakdown</b>" in out3
    assert "<b>🧾 Bill #5 — Madhavan</b>" in out3
    assert "<b>📦 Inventory</b>" in out3
    assert "<b>⚠️ Stock Warning</b>" in out3

    # 4. Parenthesized labels
    out_paren = format_telegram_html("• Khata (Credit): ₹0.00\nItem (Custom): 5")
    assert "• <b>Khata (Credit):</b> ₹0.00" in out_paren
    assert "<b>Item (Custom):</b> 5" in out_paren

    # 5. Legacy HTML & Escaped HTML
    out4 = format_telegram_html("<b>Total:</b> ₹100\n&lt;b&gt;Customer:&lt;/b&gt; Ramesh")
    assert "<b>Total:</b> ₹100" in out4
    assert "<b>Customer:</b> Ramesh" in out4
    assert "&lt;b&gt;" not in out4
    assert "\\<b>" not in out4

    # 6. Separator removal
    out5 = format_telegram_html("Line 1\n---\n\\---\n────\nLine 2")
    assert "---" not in out5
    assert "────" not in out5
    assert "Line 1\nLine 2" in out5

    # 7. HTML Safety: Only <b>, <strong>, <code> recognized; arbitrary tags escaped
    out6 = format_telegram_html("<b>Total:</b> <div>test</div> & <script>alert('xss')</script>")
    assert "<b>Total:</b>" in out6
    assert "&lt;div&gt;test&lt;/div&gt;" in out6
    assert "&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;" in out6 or "&lt;script&gt;alert('xss')&lt;/script&gt;" in out6
    assert "<div>" not in out6
    assert "<script>" not in out6

def test_auto_inserted_sales_overview_header():
    from src.bot.handlers import format_telegram_html

    raw_summary_without_header = (
        "Here is your sales summary for today:\n"
        "• Total Sales Revenue: ₹492.66\n"
        "• Total Finalized Bills: 8\n"
        "• Total Tax Collected: ₹34.66\n\n"
        "Items Sold\n"
        "• Aashirvaad Atta 5kg: 1 unit — ₹304.50"
    )

    formatted = format_telegram_html(raw_summary_without_header)

    # Must contain exactly one <b>📊 Sales Overview</b>
    assert formatted.count("<b>📊 Sales Overview</b>") == 1
    assert "<b>Total Sales Revenue:</b> ₹492.66" in formatted
    assert "<b>Total Finalized Bills:</b> 8" in formatted
    assert "<b>Total Tax Collected:</b> ₹34.66" in formatted

    # When header is already provided by LLM, no duplicate header is added
    raw_summary_with_header = (
        "📊 Sales Overview\n"
        "• Total Sales Revenue: ₹492.66\n"
        "• Total Finalized Bills: 8"
    )
    formatted2 = format_telegram_html(raw_summary_with_header)
    assert formatted2.count("<b>📊 Sales Overview</b>") == 1

def test_sold_products_section_header():
    from src.bot.handlers import format_telegram_html

    raw_input = "Sold Products:\n• Aashirvaad Atta 5kg: 1 unit — ₹304.50"
    formatted = format_telegram_html(raw_input)
    assert "<b>📦 Sold Products</b>" in formatted

    raw_input_with_emoji = "📦 Sold Products:\n• Maggi 70g: 12 units"
    formatted_with_emoji = format_telegram_html(raw_input_with_emoji)
    assert "<b>📦 Sold Products</b>" in formatted_with_emoji
    assert "📦 📦" not in formatted_with_emoji


