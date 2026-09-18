import os
from src.db.connection import get_db_connection, get_db_path

def init_db(db_path: str = None) -> None:
    """Initializes the database schema if tables do not exist."""
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    with open(schema_path, "r", encoding="utf-8") as f:
        schema_sql = f.read()

    with get_db_connection(db_path) as conn:
        conn.executescript(schema_sql)
        # Ensure chat_id column exists on bills table for pre-existing databases
        cursor = conn.execute("PRAGMA table_info(bills)")
        columns = [row["name"] for row in cursor.fetchall()]
        if "chat_id" not in columns:
            conn.execute("ALTER TABLE bills ADD COLUMN chat_id TEXT")

if __name__ == "__main__":
    path = get_db_path()
    print(f"Initializing database at: {path}")
    init_db(path)
    print("Database initialization complete.")
