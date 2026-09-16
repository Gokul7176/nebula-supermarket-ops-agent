from typing import Dict, Any, Optional
from src.db.connection import get_db_connection, immediate_transaction

def set_preference(key: str, value: str) -> Dict[str, Any]:
    """
    Persists a store preference key-value pair in SQLite (e.g. shop_name, shop_gstin, default_payment_mode).
    
    Args:
        key: Preference key string
        value: Preference value string
    """
    k = key.strip().lower()
    v = value.strip()
    with get_db_connection() as conn:
        with immediate_transaction(conn):
            conn.execute(
                """
                INSERT INTO preferences (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = CURRENT_TIMESTAMP
                """,
                (k, v, v)
            )
    return {"status": "success", "key": k, "value": v}

def get_preference(key: Optional[str] = None) -> Dict[str, Any]:
    """
    Retrieves store preference(s) from SQLite.
    
    Args:
        key: Optional preference key. Omit to fetch all stored preferences.
    """
    with get_db_connection() as conn:
        if key:
            k = key.strip().lower()
            row = conn.execute("SELECT * FROM preferences WHERE key = ?", (k,)).fetchone()
            if not row:
                return {"status": "success", "key": k, "value": None}
            return {"status": "success", "key": k, "value": row["value"]}
        else:
            rows = conn.execute("SELECT * FROM preferences").fetchall()
            prefs = {r["key"]: r["value"] for r in rows}
            return {"status": "success", "preferences": prefs}
