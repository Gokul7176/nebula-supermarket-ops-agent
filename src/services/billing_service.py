import sqlite3
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

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

def set_active_draft_service(conn: sqlite3.Connection, chat_id: str, bill_id: Optional[int]) -> None:
    """Binds or unbinds an active draft bill for a chat_id."""
    if not chat_id:
        return
    if bill_id is not None:
        # Enforce that a bill cannot be active for multiple chats simultaneously
        conn.execute("DELETE FROM active_draft_bills WHERE bill_id = ?", (int(bill_id),))
        conn.execute(
            """
            INSERT INTO active_draft_bills (chat_id, bill_id, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(chat_id) DO UPDATE SET bill_id = EXCLUDED.bill_id, updated_at = CURRENT_TIMESTAMP
            """,
            (str(chat_id), int(bill_id))
        )
        logger.info(f"[ACTIVE_DRAFT] Bound chat_id='{chat_id}' -> active bill_id #{bill_id}")
    else:
        conn.execute("DELETE FROM active_draft_bills WHERE chat_id = ?", (str(chat_id),))
        logger.info(f"[ACTIVE_DRAFT] Cleared active draft mapping for chat_id='{chat_id}'")

def get_active_draft_id_service(conn: sqlite3.Connection, chat_id: str) -> Optional[int]:
    """Retrieves current valid active draft bill_id for a chat_id."""
    if not chat_id:
        return None
    row = conn.execute("SELECT bill_id FROM active_draft_bills WHERE chat_id = ?", (str(chat_id),)).fetchone()
    if not row:
        return None
    b_id = row["bill_id"]
    # Validate that bill exists and status == 'draft'
    bill = conn.execute("SELECT status FROM bills WHERE id = ?", (b_id,)).fetchone()
    if bill and bill["status"] == "draft":
        return b_id
    else:
        # Clean up invalid/finalized active draft association
        conn.execute("DELETE FROM active_draft_bills WHERE chat_id = ?", (str(chat_id),))
        logger.info(f"[ACTIVE_DRAFT] Bill #{b_id} for chat_id='{chat_id}' is no longer draft; removed mapping.")
        return None

def list_draft_bills_service(conn: sqlite3.Connection, chat_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Lists draft bills, chat-scoped to current chat_id."""
    if not chat_id:
        from src.agent.context import current_chat_id_var
        chat_id = current_chat_id_var.get()

    if chat_id:
        rows = conn.execute(
            "SELECT * FROM bills WHERE status = 'draft' AND chat_id = ? ORDER BY id ASC",
            (str(chat_id),)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM bills WHERE status = 'draft' AND (chat_id IS NULL OR chat_id = 'default') ORDER BY id ASC").fetchall()
    
    result = []
    for r in rows:
        result.append(get_bill_details_service(conn, r["id"]))
    return result

def resolve_bill_id(conn: sqlite3.Connection, bill_id: Optional[int] = None, chat_id: Optional[str] = None) -> int:
    """
    Strict resolution order per spec:
    1. Active draft for current chat_id (from active_draft_bills table).
       If an explicit bill_id is supplied in tool args, it is ONLY used if:
       - The current user request message text explicitly mentions that bill ID (e.g., "bill 17", "17").
    2. Otherwise, check open drafts for current chat_id ONLY:
       - If exactly 1 draft exists -> sets active draft and returns it.
       - If multiple drafts exist -> raises ambiguity error asking clarification.
       - If no draft exists -> raises "No active draft bill found" error.
    """
    from src.agent.context import current_user_message_var, current_chat_id_var
    resolved_chat_id = chat_id or current_chat_id_var.get()
    user_msg = (current_user_message_var.get() or "").lower()

    # Check if chat_id has an active draft mapping in active_draft_bills
    active_id = get_active_draft_id_service(conn, resolved_chat_id) if resolved_chat_id else None
    logger.info(
        f"[DEBUG RESOLVE_BILL_ID] resolved_chat_id='{resolved_chat_id}', "
        f"tool_arg_bill_id={bill_id}, active_draft_lookup_result={active_id}, "
        f"user_msg='{user_msg}'"
    )

    # Determine if numeric bill_id was explicitly mentioned in current user request text
    explicitly_mentioned_in_text = False
    if bill_id is not None and str(bill_id).isdigit():
        str_b_id = str(bill_id)
        if str_b_id in user_msg:
            explicitly_mentioned_in_text = True

    # 1. If active draft exists for this chat, MUST target active draft UNLESS user explicitly specified a different bill ID in text
    if active_id is not None:
        if bill_id is not None and explicitly_mentioned_in_text:
            b_id = int(bill_id)
            bill = conn.execute("SELECT id FROM bills WHERE id = ?", (b_id,)).fetchone()
            if not bill:
                raise ValueError(f"Bill #{b_id} not found.")
            logger.info(f"[DEBUG RESOLVE_BILL_ID] Explicit bill_id #{b_id} in text overriding active draft #{active_id}")
            return b_id
        logger.info(f"[DEBUG RESOLVE_BILL_ID] Resolved to active_draft #{active_id}")
        return active_id

    # 2. If no active draft mapping exists for this chat, use explicit bill_id parameter if valid
    if bill_id is not None and str(bill_id).isdigit():
        b_id = int(bill_id)
        bill = conn.execute("SELECT id FROM bills WHERE id = ?", (b_id,)).fetchone()
        if not bill:
            raise ValueError(f"Bill #{b_id} not found.")
        logger.info(f"[DEBUG RESOLVE_BILL_ID] No active draft; resolved to explicit parameter bill_id #{b_id}")
        return b_id

    # 3. Otherwise, check open drafts for current chat_id ONLY
    if resolved_chat_id:
        drafts = list_draft_bills_service(conn, resolved_chat_id)
        if len(drafts) == 1:
            d_id = drafts[0]["bill"]["id"]
            set_active_draft_service(conn, resolved_chat_id, d_id)
            logger.info(f"[DEBUG RESOLVE_BILL_ID] Single draft found for chat '{resolved_chat_id}'; setting active_id #{d_id}")
            return d_id
        elif len(drafts) > 1:
            d_ids = [d["bill"]["id"] for d in drafts]
            logger.warning(f"[DEBUG RESOLVE_BILL_ID] Ambiguity: multiple open drafts {d_ids} for chat '{resolved_chat_id}'")
            raise ValueError(f"Multiple open draft bills exist for this conversation ({d_ids}). Please specify which bill to target or ask the owner for clarification.")
        else:
            logger.warning(f"[DEBUG RESOLVE_BILL_ID] No active draft bill found for chat '{resolved_chat_id}'")
            raise ValueError(f"No active draft bill found for chat session '{resolved_chat_id}'. Please start a new bill first.")

    raise ValueError("No bill ID or active chat session provided to target a draft bill.")

def resolve_finalized_bill_id(conn: sqlite3.Connection, bill_id: Optional[int] = None, chat_id: Optional[str] = None) -> int:
    """
    Resolves a finalized bill_id for PDF invoice generation:
    - If bill_id is supplied, verifies whether the user explicitly referenced that bill number in their request message.
    - If Gemini supplied a bill_id that the user did not explicitly mention, ignores that value and treats bill_id as None.
    - For explicit bill_id: verifies existence, status='finalized', and chat ownership.
    - For omitted/non-explicit bill_id: selects the newest finalized bill belonging to current chat_id ONLY.
    - If no finalized bill is found, raises ValueError.
    """
    from src.agent.context import current_chat_id_var, current_user_message_var
    resolved_chat_id = chat_id or current_chat_id_var.get() or "default"
    user_msg = (current_user_message_var.get() or "").lower()

    is_explicit = False
    if bill_id is not None:
        try:
            b_id = int(bill_id)
            if str(b_id) in user_msg:
                is_explicit = True
        except (ValueError, TypeError):
            raise ValueError(f"Invalid bill ID: {bill_id}")

    if bill_id is not None and is_explicit:
        b_id = int(bill_id)
        bill = conn.execute("SELECT * FROM bills WHERE id = ?", (b_id,)).fetchone()
        if not bill:
            raise ValueError(f"Bill #{b_id} not found.")
        if bill["status"] != "finalized":
            raise ValueError(f"Bill #{b_id} is in draft status and must be finalized before generating invoice PDF.")
        if resolved_chat_id:
            b_chat = bill["chat_id"]
            if b_chat and str(b_chat) != str(resolved_chat_id):
                raise ValueError(f"Bill #{b_id} does not belong to the current chat session.")
        return b_id

    target_chat = str(resolved_chat_id)
    row = conn.execute(
        """
        SELECT id
        FROM bills
        WHERE status = 'finalized'
          AND chat_id = ?
        ORDER BY finalized_at DESC, id DESC
        LIMIT 1
        """,
        (target_chat,)
    ).fetchone()

    if row:
        return row["id"]

    raise ValueError(
        "No finalized bill found for this chat session to generate invoice PDF."
    )

def start_bill_service(conn: sqlite3.Connection, customer_name: Optional[str] = None, payment_mode: str = 'cash', chat_id: Optional[str] = None) -> Dict[str, Any]:
    """Creates a new draft bill and sets active draft for chat_id."""
    cursor = conn.execute(
        "INSERT INTO bills (chat_id, customer_name, payment_mode, status) VALUES (?, ?, ?, 'draft')",
        (str(chat_id) if chat_id else None, customer_name, payment_mode)
    )
    bill_id = cursor.lastrowid
    if chat_id:
        set_active_draft_service(conn, chat_id, bill_id)
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

def add_item_to_bill_service(conn: sqlite3.Connection, bill_id: Optional[int], product_id_or_name: str, quantity: float, chat_id: Optional[str] = None) -> Dict[str, Any]:
    """Adds or updates an item in a draft bill."""
    resolved_bill_id = resolve_bill_id(conn, bill_id, chat_id)
    if chat_id:
        set_active_draft_service(conn, chat_id, resolved_bill_id)

    bill = conn.execute("SELECT * FROM bills WHERE id = ?", (resolved_bill_id,)).fetchone()
    if not bill:
        raise ValueError(f"Bill #{resolved_bill_id} not found.")
    if bill["status"] == "finalized":
        raise ValueError(f"Cannot edit Bill #{resolved_bill_id} because it is already finalized.")

    product = find_product_helper(conn, product_id_or_name)
    p_id = product["id"]

    # Calculate tax for provisional totals
    tax_info = calculate_line_item_gst(quantity, product["sell_price"], product["gst_slab"])

    # Check if product is already in bill_items
    existing_item = conn.execute(
        "SELECT * FROM bill_items WHERE bill_id = ? AND product_id = ?", (resolved_bill_id, p_id)
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
            (resolved_bill_id, p_id, quantity, product["sell_price"], product["gst_slab"],
             tax_info["cgst_amount"], tax_info["sgst_amount"], tax_info["line_total"])
        )

    return get_bill_details_service(conn, resolved_bill_id)

def remove_item_from_bill_service(conn: sqlite3.Connection, bill_id: Optional[int], item_id_or_product_name: str, chat_id: Optional[str] = None) -> Dict[str, Any]:
    """Removes a line item from a draft bill."""
    resolved_bill_id = resolve_bill_id(conn, bill_id, chat_id)
    bill = conn.execute("SELECT * FROM bills WHERE id = ?", (resolved_bill_id,)).fetchone()
    if not bill:
        raise ValueError(f"Bill #{resolved_bill_id} not found.")
    if bill["status"] == "finalized":
        raise ValueError(f"Cannot edit Bill #{resolved_bill_id} because it is already finalized.")

    if str(item_id_or_product_name).isdigit():
        conn.execute("DELETE FROM bill_items WHERE bill_id = ? AND id = ?", (resolved_bill_id, int(item_id_or_product_name)))
    else:
        product = find_product_helper(conn, item_id_or_product_name)
        conn.execute("DELETE FROM bill_items WHERE bill_id = ? AND product_id = ?", (resolved_bill_id, product["id"]))

    return get_bill_details_service(conn, resolved_bill_id)

def get_bill_details_service(conn: sqlite3.Connection, bill_id: Optional[int] = None, chat_id: Optional[str] = None) -> Dict[str, Any]:
    """Fetches complete bill structure with computed totals."""
    if bill_id is None and chat_id:
        resolved_bill_id = resolve_bill_id(conn, bill_id, chat_id)
    elif bill_id is not None:
        resolved_bill_id = int(bill_id)
    else:
        raise ValueError("Bill ID or chat ID required to get bill details.")

    bill = conn.execute("SELECT * FROM bills WHERE id = ?", (resolved_bill_id,)).fetchone()
    if not bill:
        raise ValueError(f"Bill #{resolved_bill_id} not found.")

    items_rows = conn.execute(
        """
        SELECT bi.*, p.name as product_name, p.brand, p.unit, p.hsn_code, p.cost_price, p.mrp
        FROM bill_items bi
        JOIN products p ON bi.product_id = p.id
        WHERE bi.bill_id = ?
        ORDER BY bi.id ASC
        """,
        (resolved_bill_id,)
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

class BelowCostOverrideRequiredError(ValueError):
    """Raised when a bill contains line items priced below cost without explicit same-message authorization."""
    def __init__(self, message: str, bill_id: int, product_name: str, sell_price: float, cost_price: float):
        super().__init__(message)
        self.message = message
        self.bill_id = bill_id
        self.product_name = product_name
        self.sell_price = sell_price
        self.cost_price = cost_price

def finalize_bill_service(conn: sqlite3.Connection, bill_id: Optional[int] = None, payment_mode: Optional[str] = None,
                          payment_reference: Optional[str] = None, override_below_cost: bool = False, chat_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Finalizes a bill inside the caller's BEGIN IMMEDIATE transaction.
    AUTHORITATIVE GUARD: If bills.status == 'finalized', returns existing result immediately!
    """
    resolved_bill_id = resolve_bill_id(conn, bill_id, chat_id)

    bill = conn.execute("SELECT * FROM bills WHERE id = ?", (resolved_bill_id,)).fetchone()
    if not bill:
        raise ValueError(f"Bill #{resolved_bill_id} not found.")

    # 1. Authoritative Durable Idempotency Check
    if bill["status"] == "finalized":
        return get_bill_details_service(conn, resolved_bill_id)

    # Fetch line items
    items_rows = conn.execute(
        """
        SELECT bi.*, p.name as product_name, p.quantity as current_stock, p.cost_price, p.sell_price, p.gst_slab
        FROM bill_items bi
        JOIN products p ON bi.product_id = p.id
        WHERE bi.bill_id = ?
        """,
        (resolved_bill_id,)
    ).fetchall()

    if not items_rows:
        raise ValueError(f"Bill #{resolved_bill_id} has no line items and cannot be finalized.")

    # Determine final payment mode
    final_pm = payment_mode or bill["payment_mode"] or "cash"

    # 2. Stock Availability & Below-Cost Refusal Checks
    from src.agent.context import current_user_message_var
    user_msg = (current_user_message_var.get() or "").strip()
    user_msg_lower = user_msg.lower()

    # Explicit authorization keywords/phrases in the CURRENT user message
    # Must be unambiguous override intent specifically for below-cost/loss sales
    explicit_override_phrases = [
        "override",
        "below cost",
        "below-cost",
        "loss",
        "allow loss",
        "sell at loss",
        "sell below cost",
        "allow below cost",
        "allow the below-cost",
        "explicitly allow"
    ]
    is_same_msg_authorized = any(phrase in user_msg_lower for phrase in explicit_override_phrases)

    logger.info(
        f"[DEBUG FINALIZE_SERVICE] resolved_bill_id={resolved_bill_id}, "
        f"tool_arg_override_below_cost={override_below_cost}, "
        f"is_same_msg_authorized={is_same_msg_authorized}, user_msg='{user_msg}'"
    )

    for item in items_rows:
        p_name = item["product_name"]
        req_qty = item["quantity"]
        curr_stock = item["current_stock"]
        unit_price = item["unit_price_at_sale"]
        cost_price = item["cost_price"]

        if req_qty > curr_stock:
            raise ValueError(
                f"Cannot finalize Bill #{resolved_bill_id}: Stock insufficient for '{p_name}'. "
                f"Requested: {req_qty}, Available: {curr_stock}."
            )

        if unit_price < cost_price:
            logger.info(
                f"[DEBUG BELOW_COST_ITEM] Item '{p_name}' priced below cost! "
                f"sell_price={unit_price}, cost_price={cost_price}. "
                f"override_below_cost={override_below_cost}, is_same_msg_authorized={is_same_msg_authorized}"
            )
            # Below-cost sale requires BOTH:
            # 1. override_below_cost=True passed by LLM tool call
            # 2. Explicit authorization present in the current user request message
            if not override_below_cost or not is_same_msg_authorized:
                logger.warning(
                    f"[BELOW_COST_REFUSED] Bill #{resolved_bill_id} item '{p_name}' sell_price={unit_price} < cost_price={cost_price}. "
                    f"override_below_cost={override_below_cost}, is_same_msg_authorized={is_same_msg_authorized}. "
                    f"Refusing finalization."
                )
                raise BelowCostOverrideRequiredError(
                    message=f"Cannot finalize Bill #{resolved_bill_id}: Item '{p_name}' is priced below cost (Selling: ₹{unit_price}, Cost: ₹{cost_price}). Explicit owner authorization in the current request message is required.",
                    bill_id=resolved_bill_id,
                    product_name=p_name,
                    sell_price=unit_price,
                    cost_price=cost_price
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
            raise ValueError(f"Khata payment mode requires a valid customer name on Bill #{resolved_bill_id}.")
        
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
            (cust_name, grand_total, f"Bill #{resolved_bill_id} purchase", resolved_bill_id)
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
        (final_pm, payment_reference, resolved_bill_id)
    )

    # Clear active draft association for this bill upon successful finalization
    conn.execute("DELETE FROM active_draft_bills WHERE bill_id = ?", (resolved_bill_id,))

    return get_bill_details_service(conn, resolved_bill_id)
