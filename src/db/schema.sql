-- SQLite Schema for Kirana Store Ops Agent
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- Products Table
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    brand TEXT NOT NULL,
    unit TEXT NOT NULL CHECK(unit IN ('kg', 'g', 'litre', 'ml', 'packet', 'dozen', 'piece')),
    is_loose BOOLEAN NOT NULL DEFAULT 0,
    hsn_code TEXT NOT NULL,
    gst_slab REAL NOT NULL CHECK(gst_slab IN (0, 5, 12, 18)),
    cost_price REAL NOT NULL CHECK(cost_price >= 0),
    sell_price REAL NOT NULL CHECK(sell_price >= 0),
    mrp REAL NOT NULL CHECK(mrp >= 0),
    quantity REAL NOT NULL DEFAULT 0 CHECK(quantity >= 0),
    reorder_level REAL NOT NULL DEFAULT 5,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Bills Table
CREATE TABLE IF NOT EXISTS bills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft', 'finalized')),
    customer_name TEXT,
    payment_mode TEXT CHECK(payment_mode IN ('cash', 'upi', 'card', 'khata')),
    payment_reference TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    finalized_at TIMESTAMP
);

-- Bill Line Items Table
CREATE TABLE IF NOT EXISTS bill_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bill_id INTEGER NOT NULL REFERENCES bills(id) ON DELETE CASCADE,
    product_id INTEGER NOT NULL REFERENCES products(id),
    quantity REAL NOT NULL CHECK(quantity > 0),
    unit_price_at_sale REAL NOT NULL,
    gst_slab_at_sale REAL NOT NULL,
    cgst_amount REAL NOT NULL,
    sgst_amount REAL NOT NULL,
    line_total REAL NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Khata Balances Table
CREATE TABLE IF NOT EXISTS khata (
    customer_name TEXT PRIMARY KEY,
    balance REAL NOT NULL DEFAULT 0 CHECK(balance >= 0),
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Khata Transactions Ledger
CREATE TABLE IF NOT EXISTS khata_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_name TEXT NOT NULL REFERENCES khata(customer_name),
    amount REAL NOT NULL CHECK(amount > 0),
    type TEXT NOT NULL CHECK(type IN ('charge', 'payment')),
    notes TEXT,
    bill_id INTEGER REFERENCES bills(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Store Preferences Table
CREATE TABLE IF NOT EXISTS preferences (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Telegram Update Idempotency Table
CREATE TABLE IF NOT EXISTS processed_updates (
    telegram_update_id INTEGER PRIMARY KEY,
    status TEXT NOT NULL CHECK(status IN ('processing', 'succeeded', 'failed')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    result_json TEXT,
    error_message TEXT
);

-- Performance Indexes
CREATE INDEX IF NOT EXISTS idx_products_name ON products(name);
CREATE INDEX IF NOT EXISTS idx_bills_status ON bills(status);
CREATE INDEX IF NOT EXISTS idx_bill_items_bill_id ON bill_items(bill_id);
CREATE INDEX IF NOT EXISTS idx_khata_tx_customer ON khata_transactions(customer_name);
