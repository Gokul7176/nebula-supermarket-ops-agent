import os
import tempfile
import pytest
from src.db.connection import get_db_connection, immediate_transaction
from src.db.init_db import init_db

def test_database_wal_and_foreign_keys():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_wal.db")
        init_db(db_path)

        with get_db_connection(db_path) as conn:
            wal_mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
            fk_mode = conn.execute("PRAGMA foreign_keys;").fetchone()[0]

            assert wal_mode.lower() == "wal"
            assert fk_mode == 1

def test_database_persistence():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_persist.db")
        init_db(db_path)

        with get_db_connection(db_path) as conn:
            with immediate_transaction(conn):
                conn.execute("INSERT INTO preferences (key, value) VALUES ('test_key', 'test_val')")

        # Re-open connection
        with get_db_connection(db_path) as conn:
            row = conn.execute("SELECT value FROM preferences WHERE key = 'test_key'").fetchone()
            assert row is not None
            assert row["value"] == "test_val"
