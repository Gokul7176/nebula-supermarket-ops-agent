# 🛒 Indian Kirana Store Operations Telegram AI Agent

An end-to-end, pure agentic Telegram AI bot designed for Indian Kirana (grocery) store owners. It manages stock receiving, multi-turn GST billing, customer credit (*khata*), daily close aggregation, and automated PDF tax invoices & PowerPoint analysis decks entirely through plain-English chat.

---

## 🌟 Key Architectural Features

- **Pure Agentic Orchestration**: Zero keyword routers, zero regex intent classifiers, and zero hidden command parsers. Powered by **Google Gemini 2.5 Flash** (`google-genai` SDK) with native typed Pydantic tool registration and multi-tool chaining loops.
- **SQLite WAL Mode & Concurrency**: Enabled `PRAGMA journal_mode=WAL` and `PRAGMA foreign_keys=ON`. All state-changing operations (`finalize_bill`, `receive_stock`, `add_khata_charge`, `record_khata_payment`) use `BEGIN IMMEDIATE` write locks upfront to prevent race conditions or negative inventory.
- **Double-Layered Idempotency**:
  - `processed_updates`: Tracks Telegram `update_id` states (`processing`, `succeeded`, `failed`). Replays cached responses for `succeeded`, rejects concurrent `processing`, and permits retries for `failed`.
  - `bills.status = 'finalized'` + `finalized_at`: Authoritative durable guard for bill finalization. Re-calling `finalize_bill` on an already finalized bill returns the existing result without repeating stock or credit ledger mutations.
- **GST & Business Rule Enforcement**: Exact per-item CGST + SGST splitting (intra-state 50/50) and paisa-level rounding (2 decimal places) enforced strictly inside tool/service code.
- **PDF & PPTX Generation**: `reportlab` renders itemized GST tax invoices, and `python-pptx` + `matplotlib` renders multi-slide store analysis decks with live charts (or "No data for this period" callouts).

---

## 📁 Repository Structure

```
c:\nebula\
├── Procfile                # Railway process start command
├── Dockerfile              # Container definition for Railway deployment
├── requirements.txt        # Python dependencies
├── README.md               # Project setup & architecture documentation
├── .env.example            # Sample environment variables
├── .gitignore
└── src/
    ├── __init__.py
    ├── bot/                # Telegram bot & update idempotency middleware
    │   ├── main.py
    │   ├── handlers.py
    │   └── idempotency.py
    ├── agent/              # Gemini 2.5 Flash agent harness & control loop
    │   ├── loop.py
    │   ├── prompt.py
    │   └── registry.py
    ├── tools/              # 16 First-class model-facing business tools
    │   ├── product_tools.py
    │   ├── bill_tools.py
    │   ├── khata_tools.py
    │   ├── report_tools.py
    │   └── pref_tools.py
    ├── services/           # Core business logic (billing, GST, stock, khata)
    │   ├── billing_service.py
    │   ├── stock_service.py
    │   └── khata_service.py
    ├── db/                 # SQLite DDL schema, WAL connection factory & init
    │   ├── schema.sql
    │   ├── connection.py
    │   └── init_db.py
    ├── documents/          # ReportLab PDF & python-pptx + matplotlib builders
    │   ├── pdf_invoice.py
    │   └── pptx_deck.py
    ├── models/             # Pydantic schema declarations
    │   └── schemas.py
    └── tests/              # Comprehensive Pytest suite
        ├── test_db.py
        ├── test_billing.py
        ├── test_idempotency.py
        ├── test_concurrency.py
        └── test_documents.py
```

---

## 🚀 Local Run Instructions

### 1. Prerequisites
- Python 3.11+
- Virtual environment (`venv`)

### 2. Installation
```bash
git clone https://github.com/<your-username>/kirana-ops-agent.git
cd kirana-ops-agent

python -m venv venv
# On Windows:
venv\Scripts\activate
# On Linux/macOS:
source venv/bin/activate

pip install -r requirements.txt
```

### 3. Environment Setup
Copy `.env.example` to `.env` and fill in your keys:
```env
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_from_botfather
GEMINI_API_KEY=your_google_genai_api_key
DB_PATH=kirana.db
```

### 4. Run Test Suite
```bash
pytest src/tests/ -v
```

### 5. Start Bot
```bash
python -m src.bot.main
```

---

## ☁️ Deployment on Railway

1. Create a new project on [Railway.app](https://railway.app).
2. Connect your GitHub repository.
3. Add a **Persistent Volume** mounted at `/data`.
4. Configure Environment Variables in Railway:
   - `TELEGRAM_BOT_TOKEN`: Telegram bot token.
   - `GEMINI_API_KEY`: Google GenAI API key.
   - `DB_PATH`: `/data/kirana.db`
5. Deploy. Railway will use the `Procfile` / `Dockerfile` to start the long-polling process.

---

## 🛠 Model-Facing Tools Reference (16 Tools)

1. `add_product`: Register a new SKU with prices, HSN, and GST slab.
2. `receive_stock`: Add stock quantity & update prices.
3. `get_stock`: Query stock levels or low-stock alerts.
4. `start_bill`: Start a new multi-turn draft bill.
5. `add_item_to_bill`: Add product line item to draft bill.
6. `remove_item_from_bill`: Remove line item from draft bill.
7. `get_draft_bill`: Inspect draft bill totals & tax breakdown.
8. `finalize_bill`: Finalize bill, re-check stock, calculate GST, decrement inventory, update Khata.
9. `get_khata_balance`: Query customer credit balance & transaction ledger.
10. `add_khata_charge`: Add direct manual credit charge.
11. `record_khata_payment`: Settle customer credit payment.
12. `close_day`: Aggregate daily sales, taxes, payment modes, and top items.
13. `generate_invoice_pdf`: Render GST tax invoice PDF.
14. `generate_analysis_deck`: Render PowerPoint analysis deck with charts.
15. `set_preference`: Store shop preferences in SQLite.
16. `get_preference`: Retrieve stored shop preferences.
