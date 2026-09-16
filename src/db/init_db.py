import os
from src.db.connection import get_db_connection, get_db_path

def init_db(db_path: str = None) -> None:
    """Initializes the database schema if tables do not exist."""
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    with open(schema_path, "r", encoding="utf-8") as f:
        schema_sql = f.read()

    with get_db_connection(db_path) as conn:
        conn.executescript(schema_sql)

if __name__ == "__main__":
    path = get_db_path()
    print(f"Initializing database at: {path}")
    init_db(path)
    print("Database initialization complete.")
