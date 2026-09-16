import sqlite3
from typing import Dict, Any, List, Optional

def calculate_line_item_gst(quantity: float, unit_price: float, gst_slab: float) -> Dict[str, float]:
    """
    Computes per-line-item tax.
    Intra-state split: CGST = slab/2, SGST = slab/2.
    Rounds tax to 2 decimal places (nearest paisa) per line item.
    """
    taxable_amount = quantity * unit_price
    half_slab = (gst_slab / 2.0) / 100.0
    
    cgst_raw = taxable_amount * half_slab
    sgst_raw = taxable_amount * half_slab
    
    cgst_amount = round(cgst_raw, 2)
    sgst_amount = round(sgst_raw, 2)
    line_total = round(taxable_amount + cgst_amount + sgst_amount, 2)
    
    return {
        "taxable_amount": round(taxable_amount, 2),
        "cgst_amount": cgst_amount,
        "sgst_amount": sgst_amount,
        "total_tax": round(cgst_amount + sgst_amount, 2),
        "line_total": line_total
    }

def start_bill_service(conn: sqlite3.Connection, customer_name: Optional[str] = None, payment_mode: str = 'cash') -> Dict[str, Any]:
    """Creates a new draft bill."""
    cursor = conn.execute(
        "INSERT INTO bills (customer_name, payment_mode, status) VALUES (?, ?, 'draft')",
        (customer_name, payment_mode)
    )
    bill_id = cursor.lastrowid
    return get_bill_details_service(conn, bill_id)

def find_product_helper(conn: sqlite3.Connection, product_id_or_name: str) -> Dict[str, Any]:
    """Helper to locate a product by ID or Name."""
    product = None
    if str(product_id_or_name).isdigit():
        product = conn.execute("SELECT * FROM products WHERE id = ?", (int(product_id_or_name),)).fetchone()
    if not product:
        product = conn.execute("SELECT * FROM products WHERE name = ? COLLATE NOCASE", (str(product_id_or_name).strip(),)).fetchone()
    if not product:
        product = conn.execute("SELECT * FROM products WHERE name LIKE ? COLLATE NOCASE", (f"%{product_id_or_name}%",)).fetchone()
    
    if not product:
        raise ValueError(f"Product '{product_id_or_name}' not found.")
    return dict(product)

def add_item_to_bill_service(conn: sqlite3.Connection, bill_id: int, product_id_or_name: str, quantity: float) -> Dict[str, Any]:
    """Adds or updates an item in a draft bill."""
    bill = conn.execute("SELECT * FROM bills WHERE id = ?", (bill_id,)).fetchone()
    if not bill:
        raise ValueError(f"Bill #{bill_id} not found.")
    if bill["status"] == "finalized":
        raise ValueError(f"Cannot edit Bill #{bill_id} because it is already finalized.")

    product = find_product_helper(conn, product_id_or_name)
    p_id = product["id"]

    # Calculate tax for provisional totals
    tax_info = calculate_line_item_gst(quantity, product["sell_price"], product["gst_slab"])

    # Check if product is already in bill_items
    existing_item = conn.execute(
        "SELECT * FROM bill_items WHERE bill_id = ? AND product_id = ?", (bill_id, p_id)
    ).fetchone()

    if existing_item:
        new_qty = existing_item["quantity"] + quantity
        new_tax_info = calculate_line_item_gst(new_qty, product["sell_price"], product["gst_slab"])
        conn.execute(
            """
            UPDATE bill_items
            SET quantity = ?, unit_price_at_sale = ?, gst_slab_at_sale = ?,
                cgst_amount = ?, sgst_amount = ?, line_total = ?
            WHERE id = ?
            """,
            (new_qty, product["sell_price"], product["gst_slab"],
             new_tax_info["cgst_amount"], new_tax_info["sgst_amount"], new_tax_info["line_total"], existing_item["id"])
        )
    else:
        conn.execute(
            """
            INSERT INTO bill_items (bill_id, product_id, quantity, unit_price_at_sale, gst_slab_at_sale, cgst_amount, sgst_amount, line_total)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (bill_id, p_id, quantity, product["sell_price"], product["gst_slab"],
             tax_info["cgst_amount"], tax_info["sgst_amount"], tax_info["line_total"])
        )

    return get_bill_details_service(conn, bill_id)

def remove_item_from_bill_service(conn: sqlite3.Connection, bill_id: int, item_id_or_product_name: str) -> Dict[str, Any]:
    """Removes a line item from a draft bill."""
    bill = conn.execute("SELECT * FROM bills WHERE id = ?", (bill_id,)).fetchone()
    if not bill:
        raise ValueError(f"Bill #{bill_id} not found.")
    if bill["status"] == "finalized":
        raise ValueError(f"Cannot edit Bill #{bill_id} because it is already finalized.")

    if str(item_id_or_product_name).isdigit():
        conn.execute("DELETE FROM bill_items WHERE bill_id = ? AND id = ?", (bill_id, int(item_id_or_product_name)))
    else:
        product = find_product_helper(conn, item_id_or_product_name)
        conn.execute("DELETE FROM bill_items WHERE bill_id = ? AND product_id = ?", (bill_id, product["id"]))

    return get_bill_details_service(conn, bill_id)

def get_bill_details_service(conn: sqlite3.Connection, bill_id: int) -> Dict[str, Any]:
    """Fetches complete bill structure with computed totals."""
    bill = conn.execute("SELECT * FROM bills WHERE id = ?", (bill_id,)).fetchone()
    if not bill:
        raise ValueError(f"Bill #{bill_id} not found.")

    items_rows = conn.execute(
        """
        SELECT bi.*, p.name as product_name, p.brand, p.unit, p.hsn_code, p.cost_price, p.mrp
        FROM bill_items bi
        JOIN products p ON bi.product_id = p.id
        WHERE bi.bill_id = ?
        ORDER BY bi.id ASC
        """,
        (bill_id,)
    ).fetchall()

    items = [dict(r) for r in items_rows]

    subtotal = sum(i["quantity"] * i["unit_price_at_sale"] for i in items)
    total_cgst = sum(i["cgst_amount"] for i in items)
    total_sgst = sum(i["sgst_amount"] for i in items)
    total_tax = total_cgst + total_sgst
    grand_total = sum(i["line_total"] for i in items)

    return {
        "bill": dict(bill),
        "items": items,
        "subtotal": round(subtotal, 2),
        "total_cgst": round(total_cgst, 2),
        "total_sgst": round(total_sgst, 2),
        "total_tax": round(total_tax, 2),
        "grand_total": round(grand_total, 2)
    }

def finalize_bill_service(conn: sqlite3.Connection, bill_id: int, payment_mode: Optional[str] = None,
                          payment_reference: Optional[str] = None, override_below_cost: bool = False) -> Dict[str, Any]:
    """
    Finalizes a bill inside the caller's BEGIN IMMEDIATE transaction.
    AUTHORITATIVE GUARD: If bills.status == 'finalized', returns existing result immediately!
    """
    bill = conn.execute("SELECT * FROM bills WHERE id = ?", (bill_id,)).fetchone()
    if not bill:
        raise ValueError(f"Bill #{bill_id} not found.")

    # 1. Authoritative Durable Idempotency Check
    if bill["status"] == "finalized":
        # Return existing finalized bill details without mutating stock or khata
        return get_bill_details_service(conn, bill_id)

    # Fetch line items
    items_rows = conn.execute(
        """
        SELECT bi.*, p.name as product_name, p.quantity as current_stock, p.cost_price, p.sell_price, p.gst_slab
        FROM bill_items bi
        JOIN products p ON bi.product_id = p.id
        WHERE bi.bill_id = ?
        """,
        (bill_id,)
    ).fetchall()

    if not items_rows:
        raise ValueError(f"Bill #{bill_id} has no line items and cannot be finalized.")

    # Determine final payment mode
    final_pm = payment_mode or bill["payment_mode"] or "cash"

    # 2. Stock Availability & Below-Cost Refusal Checks
    for item in items_rows:
        p_name = item["product_name"]
        req_qty = item["quantity"]
        curr_stock = item["current_stock"]
        unit_price = item["unit_price_at_sale"]
        cost_price = item["cost_price"]

        if req_qty > curr_stock:
            raise ValueError(
                f"Cannot finalize Bill #{bill_id}: Stock insufficient for '{p_name}'. "
                f"Requested: {req_qty}, Available: {curr_stock}."
            )

        if unit_price < cost_price and not override_below_cost:
            raise ValueError(
                f"Cannot finalize Bill #{bill_id}: Item '{p_name}' is priced below cost "
                f"(Selling: ₹{unit_price}, Cost: ₹{cost_price}). "
                f"Owner override required."
            )

    # 3. Recalculate per-line GST & update stock quantities
    grand_total = 0.0
    for item in items_rows:
        req_qty = item["quantity"]
        p_id = item["product_id"]
        unit_price = item["unit_price_at_sale"]
        gst_slab = item["gst_slab_at_sale"]

        tax_info = calculate_line_item_gst(req_qty, unit_price, gst_slab)
        grand_total += tax_info["line_total"]

        # Update line item tax breakdown
        conn.execute(
            """
            UPDATE bill_items
            SET cgst_amount = ?, sgst_amount = ?, line_total = ?
            WHERE id = ?
            """,
            (tax_info["cgst_amount"], tax_info["sgst_amount"], tax_info["line_total"], item["id"])
        )

        # Decrement product stock atomically
        conn.execute(
            "UPDATE products SET quantity = quantity - ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (req_qty, p_id)
        )

    grand_total = round(grand_total, 2)
    cust_name = bill["customer_name"]

    # 4. Handle Khata credit if payment_mode == 'khata'
    if final_pm == "khata":
        if not cust_name or not cust_name.strip():
            raise ValueError(f"Khata payment mode requires a valid customer name on Bill #{bill_id}.")
        
        cust_name = cust_name.strip()
        
        # Ensure khata customer entry exists
        conn.execute(
            """
            INSERT INTO khata (customer_name, balance) VALUES (?, ?)
            ON CONFLICT(customer_name) DO UPDATE SET updated_at = CURRENT_TIMESTAMP
            """,
            (cust_name, 0.0)
        )

        # Record charge in khata_transactions
        conn.execute(
            """
            INSERT INTO khata_transactions (customer_name, amount, type, notes, bill_id)
            VALUES (?, ?, 'charge', ?, ?)
            """,
            (cust_name, grand_total, f"Bill #{bill_id} purchase", bill_id)
        )

        # Update running balance
        conn.execute(
            "UPDATE khata SET balance = balance + ?, updated_at = CURRENT_TIMESTAMP WHERE customer_name = ?",
            (grand_total, cust_name)
        )

    # 5. Mark bill finalized
    conn.execute(
        """
        UPDATE bills
        SET status = 'finalized', payment_mode = ?, payment_reference = ?, finalized_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (final_pm, payment_reference, bill_id)
    )

    return get_bill_details_service(conn, bill_id)
