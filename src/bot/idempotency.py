import json
import sqlite3
from typing import Optional, Tuple
from src.db.connection import get_db_connection, immediate_transaction

def check_and_start_update(update_id: int) -> Tuple[str, Optional[str]]:
    """
    Checks and registers a Telegram update_id in processed_updates table inside write lock.
    
    Returns:
        (action, cached_result_json)
        action is one of:
        - 'SKIP_CACHED': update_id status is 'succeeded'. Return cached_result_json.
        - 'SKIP_IN_FLIGHT': update_id status is 'processing'. Reject concurrent execution.
        - 'PROCEED': update_id is new or previously 'failed'. Proceed with processing.
    """
    with get_db_connection() as conn:
        with immediate_transaction(conn):
            row = conn.execute("SELECT * FROM processed_updates WHERE telegram_update_id = ?", (update_id,)).fetchone()
            
            if row:
                status = row["status"]
                if status == "succeeded":
                    return "SKIP_CACHED", row["result_json"]
                elif status == "processing":
                    return "SKIP_IN_FLIGHT", None
                elif status == "failed":
                    # Allow retry on failed update
                    conn.execute(
                        "UPDATE processed_updates SET status = 'processing', error_message = NULL, created_at = CURRENT_TIMESTAMP WHERE telegram_update_id = ?",
                        (update_id,)
                    )
                    return "PROCEED", None
            else:
                conn.execute(
                    "INSERT INTO processed_updates (telegram_update_id, status) VALUES (?, 'processing')",
                    (update_id,)
                )
                return "PROCEED", None

def mark_update_succeeded(update_id: int, result_text: str) -> None:
    """Marks telegram update_id as succeeded with cached result string."""
    with get_db_connection() as conn:
        with immediate_transaction(conn):
            conn.execute(
                """
                UPDATE processed_updates
                SET status = 'succeeded', result_json = ?, completed_at = CURRENT_TIMESTAMP
                WHERE telegram_update_id = ?
                """,
                (result_text, update_id)
            )

def mark_update_failed(update_id: int, error_msg: str) -> None:
    """Marks telegram update_id as failed with error details to allow future retries."""
    with get_db_connection() as conn:
        with immediate_transaction(conn):
            conn.execute(
                """
                UPDATE processed_updates
                SET status = 'failed', error_message = ?, completed_at = CURRENT_TIMESTAMP
                WHERE telegram_update_id = ?
                """,
                (error_msg, update_id)
            )
