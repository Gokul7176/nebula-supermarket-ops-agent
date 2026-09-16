import os
import sqlite3
from contextlib import contextmanager
from typing import Generator

DEFAULT_DB_PATH = "kirana.db"

def get_db_path() -> str:
    """Returns the database file path from environment or default."""
    return os.getenv("DB_PATH", DEFAULT_DB_PATH)

def get_raw_connection(db_path: str = None) -> sqlite3.Connection:
    """Creates a sqlite3 Connection with WAL mode and foreign keys enabled."""
    path = db_path or get_db_path()
    # Ensure directory exists if path includes directories (e.g. /data/kirana.db)
    dirname = os.path.dirname(path)
    if dirname:
        os.makedirs(dirname, exist_ok=True)

    conn = sqlite3.connect(path, timeout=10.0, isolation_level=None)  # autocommit mode for explicit transactions
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    return conn

@contextmanager
def get_db_connection(db_path: str = None) -> Generator[sqlite3.Connection, None, None]:
    """Context manager for acquiring a database connection."""
    conn = get_raw_connection(db_path)
    try:
        yield conn
    finally:
        conn.close()

@contextmanager
def immediate_transaction(conn: sqlite3.Connection) -> Generator[sqlite3.Connection, None, None]:
    """
    Context manager for acquiring an upfront write lock via BEGIN IMMEDIATE.
    Guarantees check-then-write atomicity inside SQLite WAL mode.
    """
    conn.execute("BEGIN IMMEDIATE;")
    try:
        yield conn
        conn.execute("COMMIT;")
    except Exception:
        conn.execute("ROLLBACK;")
        raise
