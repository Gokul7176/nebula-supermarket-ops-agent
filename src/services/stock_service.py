import sqlite3
from typing import Dict, Any, List, Optional
from src.db.connection import get_db_connection, immediate_transaction

def add_product_service(conn: sqlite3.Connection, data: Dict[str, Any]) -> Dict[str, Any]:
    """Adds a new product SKU to the database inside a write transaction."""
    sql = """
    INSERT INTO products (name, brand, unit, is_loose, hsn_code, gst_slab, cost_price, sell_price, mrp, quantity, reorder_level)
    VALUES (:name, :brand, :unit, :is_loose, :hsn_code, :gst_slab, :cost_price, :sell_price, :mrp, :quantity, :reorder_level)
    """
    try:
        cursor = conn.execute(sql, data)
        product_id = cursor.lastrowid
        row = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
        return dict(row)
    except sqlite3.IntegrityError as e:
        if "UNIQUE constraint failed: products.name" in str(e):
            raise ValueError(f"Product with name '{data['name']}' already exists.")
        raise e

def receive_stock_service(conn: sqlite3.Connection, product_id_or_name: str, quantity: float,
                          cost_price: Optional[float] = None, mrp: Optional[float] = None,
                          sell_price: Optional[float] = None) -> Dict[str, Any]:
    """
    Increments product stock and optionally updates prices.
    Preserves existing prices if optional values are omitted/None.
    """
    # Find product by ID or Name
    product = None
    if str(product_id_or_name).isdigit():
        product = conn.execute("SELECT * FROM products WHERE id = ?", (int(product_id_or_name),)).fetchone()
    if not product:
        product = conn.execute("SELECT * FROM products WHERE name = ? COLLATE NOCASE", (str(product_id_or_name).strip(),)).fetchone()
    if not product:
        # Try partial match
        product = conn.execute("SELECT * FROM products WHERE name LIKE ? COLLATE NOCASE", (f"%{product_id_or_name}%",)).fetchone()
    
    if not product:
        raise ValueError(f"Product '{product_id_or_name}' not found.")

    p_id = product["id"]

    sql = """
    UPDATE products
    SET quantity = quantity + :qty,
        cost_price = COALESCE(:cost_price, cost_price),
        mrp = COALESCE(:mrp, mrp),
        sell_price = COALESCE(:sell_price, sell_price),
        updated_at = CURRENT_TIMESTAMP
    WHERE id = :id
    """
    conn.execute(sql, {
        "qty": quantity,
        "cost_price": cost_price,
        "mrp": mrp,
        "sell_price": sell_price,
        "id": p_id
    })

    updated_product = conn.execute("SELECT * FROM products WHERE id = ?", (p_id,)).fetchone()
    return dict(updated_product)

def get_stock_service(conn: sqlite3.Connection, query: Optional[str] = None, low_stock_only: bool = False) -> List[Dict[str, Any]]:
    """Queries product stock from database."""
    sql = "SELECT * FROM products WHERE 1=1"
    params = []

    if query:
        sql += " AND (name LIKE ? OR brand LIKE ? OR hsn_code LIKE ?)"
        q = f"%{query.strip()}%"
        params.extend([q, q, q])

    if low_stock_only:
        sql += " AND quantity <= reorder_level"

    sql += " ORDER BY name ASC"
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]
