import sqlite3
from typing import Dict, Any, List, Optional

def get_khata_balance_service(conn: sqlite3.Connection, customer_name: Optional[str] = None) -> List[Dict[str, Any]]:
    """Fetches customer khata balances and transaction history."""
    if customer_name and customer_name.strip():
        name = customer_name.strip()
        row = conn.execute("SELECT * FROM khata WHERE customer_name = ? COLLATE NOCASE", (name,)).fetchone()
        if not row:
            return []
        
        txs = conn.execute(
            "SELECT * FROM khata_transactions WHERE customer_name = ? ORDER BY id DESC LIMIT 10", (row["customer_name"],)
        ).fetchall()

        return [{
            "customer_name": row["customer_name"],
            "balance": row["balance"],
            "updated_at": row["updated_at"],
            "recent_transactions": [dict(t) for t in txs]
        }]
    else:
        rows = conn.execute("SELECT * FROM khata ORDER BY balance DESC").fetchall()
        return [dict(r) for r in rows]

def add_khata_charge_service(conn: sqlite3.Connection, customer_name: str, amount: float, notes: Optional[str] = None) -> Dict[str, Any]:
    """Adds a manual charge to customer khata balance inside write transaction."""
    name = customer_name.strip()
    if not name:
        raise ValueError("Customer name cannot be empty.")
    if amount <= 0:
        raise ValueError("Charge amount must be greater than zero.")

    # Upsert customer khata entry
    conn.execute(
        """
        INSERT INTO khata (customer_name, balance) VALUES (?, ?)
        ON CONFLICT(customer_name) DO UPDATE SET updated_at = CURRENT_TIMESTAMP
        """,
        (name, 0.0)
    )

    # Insert transaction
    conn.execute(
        "INSERT INTO khata_transactions (customer_name, amount, type, notes) VALUES (?, ?, 'charge', ?)",
        (name, amount, notes)
    )

    # Update balance
    conn.execute(
        "UPDATE khata SET balance = balance + ?, updated_at = CURRENT_TIMESTAMP WHERE customer_name = ?",
        (amount, name)
    )

    res = get_khata_balance_service(conn, name)
    return res[0]

def record_khata_payment_service(conn: sqlite3.Connection, customer_name: str, amount: float,
                                 payment_mode: str = 'cash', reference: Optional[str] = None) -> Dict[str, Any]:
    """
    Records a credit payment settlement against customer khata balance inside write transaction.
    REFUSES payment if customer does not exist or payment exceeds owed balance.
    """
    name = customer_name.strip()
    if not name:
        raise ValueError("Customer name cannot be empty.")
    if amount <= 0:
        raise ValueError("Payment amount must be greater than zero.")

    row = conn.execute("SELECT * FROM khata WHERE customer_name = ? COLLATE NOCASE", (name,)).fetchone()
    if not row:
        raise ValueError(f"Customer '{name}' has no active khata credit record.")

    current_balance = row["balance"]
    exact_name = row["customer_name"]

    if amount > current_balance:
        raise ValueError(
            f"Cannot process payment of ₹{amount:.2f} for '{exact_name}'. "
            f"Owed balance is only ₹{current_balance:.2f}."
        )

    notes_str = f"Settlement via {payment_mode.upper()}"
    if reference:
        notes_str += f" (Ref: {reference})"

    # Insert transaction
    conn.execute(
        "INSERT INTO khata_transactions (customer_name, amount, type, notes) VALUES (?, ?, 'payment', ?)",
        (exact_name, amount, notes_str)
    )

    # Update balance
    conn.execute(
        "UPDATE khata SET balance = balance - ?, updated_at = CURRENT_TIMESTAMP WHERE customer_name = ?",
        (amount, exact_name)
    )

    res = get_khata_balance_service(conn, exact_name)
    return res[0]
