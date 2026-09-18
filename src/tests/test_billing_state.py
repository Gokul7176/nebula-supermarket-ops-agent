import os
import tempfile
import sqlite3
import pytest
from src.db.connection import get_db_connection, immediate_transaction
from src.db.init_db import init_db
from src.services.stock_service import add_product_service, get_stock_service
from src.services.billing_service import (
    start_bill_service, add_item_to_bill_service, remove_item_from_bill_service,
    get_bill_details_service, finalize_bill_service, resolve_bill_id,
    get_active_draft_id_service, list_draft_bills_service, set_active_draft_service
)
from src.bot.handlers import clear_chat_conversation_history, CONVERSATION_HISTORIES

@pytest.fixture
def test_db():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_billing_state.db")
        init_db(db_path)
        yield db_path

def seed_sample_products(conn):
    add_product_service(conn, {
        "name": "Aashirvaad Atta", "brand": "ITC", "unit": "packet", "is_loose": False,
        "hsn_code": "1101", "gst_slab": 5, "cost_price": 200, "sell_price": 250,
        "mrp": 270, "quantity": 50, "reorder_level": 5
    })
    add_product_service(conn, {
        "name": "Tata Salt", "brand": "Tata", "unit": "packet", "is_loose": False,
        "hsn_code": "2501", "gst_slab": 0, "cost_price": 20, "sell_price": 28,
        "mrp": 30, "quantity": 100, "reorder_level": 10
    })

def test_start_bill_add_item_get_draft(test_db):
    with get_db_connection(test_db) as conn:
        with immediate_transaction(conn):
            seed_sample_products(conn)
            b1 = start_bill_service(conn, customer_name="Ramesh", chat_id="chat_100")
            b_id = b1["bill"]["id"]

        with immediate_transaction(conn):
            b2 = add_item_to_bill_service(conn, bill_id=None, product_id_or_name="Aashirvaad Atta", quantity=2, chat_id="chat_100")
            assert b2["bill"]["id"] == b_id
            assert len(b2["items"]) == 1
            assert b2["items"][0]["product_name"] == "Aashirvaad Atta"

        b_det = get_bill_details_service(conn, bill_id=None, chat_id="chat_100")
        assert b_det["bill"]["id"] == b_id
        assert b_det["grand_total"] == 525.0  # 2 * 250 + 5% GST = 525.0

def test_multi_turn_add_and_remove(test_db):
    with get_db_connection(test_db) as conn:
        with immediate_transaction(conn):
            seed_sample_products(conn)
            b = start_bill_service(conn, customer_name="Suresh", chat_id="chat_101")
            add_item_to_bill_service(conn, bill_id=None, product_id_or_name="Aashirvaad Atta", quantity=1, chat_id="chat_101")
            add_item_to_bill_service(conn, bill_id=None, product_id_or_name="Tata Salt", quantity=3, chat_id="chat_101")

        b_det = get_bill_details_service(conn, bill_id=None, chat_id="chat_101")
        assert len(b_det["items"]) == 2

        with immediate_transaction(conn):
            b_rem = remove_item_from_bill_service(conn, bill_id=None, item_id_or_product_name="Aashirvaad Atta", chat_id="chat_101")
            assert len(b_rem["items"]) == 1
            assert b_rem["items"][0]["product_name"] == "Tata Salt"

def test_restart_process_continues_draft(test_db):
    # Step 1: Create active draft in Connection 1
    conn1 = sqlite3.connect(test_db)
    conn1.row_factory = sqlite3.Row
    init_db(test_db)
    seed_sample_products(conn1)
    
    b_orig = start_bill_service(conn1, customer_name="Mahesh", chat_id="chat_restart")
    orig_id = b_orig["bill"]["id"]
    add_item_to_bill_service(conn1, bill_id=None, product_id_or_name="Aashirvaad Atta", quantity=2, chat_id="chat_restart")
    conn1.commit()
    
    # Step 2: EXPLICITLY CLOSE Connection 1 to simulate bot/process restart
    conn1.close()

    # Step 3: Open fresh Connection 2 and verify chat_restart resolves same active draft
    conn2 = sqlite3.connect(test_db)
    conn2.row_factory = sqlite3.Row
    
    resolved_id = resolve_bill_id(conn2, bill_id=None, chat_id="chat_restart")
    assert resolved_id == orig_id
    
    details = get_bill_details_service(conn2, bill_id=None, chat_id="chat_restart")
    assert details["bill"]["id"] == orig_id
    assert len(details["items"]) == 1
    assert details["items"][0]["product_name"] == "Aashirvaad Atta"
    conn2.close()

def test_new_command_preserves_active_draft_and_store_data(test_db):
    with get_db_connection(test_db) as conn:
        with immediate_transaction(conn):
            seed_sample_products(conn)
            b = start_bill_service(conn, customer_name="Kiran", chat_id="chat_new_cmd")
            add_item_to_bill_service(conn, bill_id=None, product_id_or_name="Tata Salt", quantity=5, chat_id="chat_new_cmd")

    # Simulate in-memory conversation history prior to /new
    CONVERSATION_HISTORIES["chat_new_cmd"] = [
        {"role": "user", "text": "Start a bill for Kiran"},
        {"role": "model", "text": "Started draft bill #1 for Kiran"}
    ]
    assert len(CONVERSATION_HISTORIES["chat_new_cmd"]) == 2

    # Execute /new command handler function
    clear_chat_conversation_history("chat_new_cmd")

    # 1. In-memory conversation context is cleared
    assert len(CONVERSATION_HISTORIES["chat_new_cmd"]) == 0

    # 2. SQLite active draft row, draft bill, items, and stock remain 100% intact
    with get_db_connection(test_db) as conn:
        active_id = get_active_draft_id_service(conn, "chat_new_cmd")
        assert active_id == b["bill"]["id"]
        
        b_det = get_bill_details_service(conn, bill_id=None, chat_id="chat_new_cmd")
        assert b_det["bill"]["customer_name"] == "Kiran"
        assert len(b_det["items"]) == 1

def test_start_bill_switches_active_draft(test_db):
    with get_db_connection(test_db) as conn:
        with immediate_transaction(conn):
            seed_sample_products(conn)
            b1 = start_bill_service(conn, customer_name="Draft 1", chat_id="chat_switch")
            b1_id = b1["bill"]["id"]

        with immediate_transaction(conn):
            b2 = start_bill_service(conn, customer_name="Draft 2", chat_id="chat_switch")
            b2_id = b2["bill"]["id"]

        assert b1_id != b2_id
        # Active draft for chat_switch is now Bill 2
        active_id = get_active_draft_id_service(conn, "chat_switch")
        assert active_id == b2_id

        # Previous Draft 1 remains intact in bills table
        drafts = list_draft_bills_service(conn, chat_id="chat_switch")
        assert len(drafts) == 2
        d_ids = [d["bill"]["id"] for d in drafts]
        assert b1_id in d_ids
        assert b2_id in d_ids

def test_ambiguity_and_no_global_guessing(test_db):
    with get_db_connection(test_db) as conn:
        with immediate_transaction(conn):
            seed_sample_products(conn)
            # Create 2 drafts for chat_A
            b1 = start_bill_service(conn, customer_name="Customer 1", chat_id="chat_A")
            b2 = start_bill_service(conn, customer_name="Customer 2", chat_id="chat_A")
            
            # Create 1 draft for chat_B
            b3 = start_bill_service(conn, customer_name="Customer 3", chat_id="chat_B")

        # Manually clear active draft mapping for chat_A to simulate un-bound active draft state with multiple drafts
        set_active_draft_service(conn, "chat_A", None)

        # Resolving bill for chat_A when active draft is None and 2 open drafts exist -> raises ambiguity error
        with pytest.raises(ValueError) as exc_info:
            resolve_bill_id(conn, bill_id=None, chat_id="chat_A")
        assert "Multiple open draft bills exist for this conversation" in str(exc_info.value)

        # Resolving bill for chat_C (which has 0 drafts) -> raises clear "No active draft" error
        with pytest.raises(ValueError) as exc_info_c:
            resolve_bill_id(conn, bill_id=None, chat_id="chat_C")
        assert "No active draft bill found for chat session 'chat_C'" in str(exc_info_c.value)

        # Verify chat_C NEVER globally guesses or borrows draft b3 from chat_B
        drafts_c = list_draft_bills_service(conn, chat_id="chat_C")
        assert len(drafts_c) == 0

def test_finalize_bill_clears_active_draft(test_db):
    with get_db_connection(test_db) as conn:
        with immediate_transaction(conn):
            seed_sample_products(conn)
            b = start_bill_service(conn, customer_name="Finalize Test", chat_id="chat_fin")
            add_item_to_bill_service(conn, bill_id=None, product_id_or_name="Tata Salt", quantity=2, chat_id="chat_fin")

        with immediate_transaction(conn):
            fin = finalize_bill_service(conn, bill_id=None, chat_id="chat_fin")
            assert fin["bill"]["status"] == "finalized"

        # After finalization, active draft mapping for chat_fin must be cleared
        active_id = get_active_draft_id_service(conn, "chat_fin")
        assert active_id is None

        with pytest.raises(ValueError) as exc_info:
            resolve_bill_id(conn, bill_id=None, chat_id="chat_fin")
        assert "No active draft bill found for chat session 'chat_fin'" in str(exc_info.value)

def test_active_draft_bill_unique_constraint(test_db):
    with get_db_connection(test_db) as conn:
        with immediate_transaction(conn):
            seed_sample_products(conn)
            b = start_bill_service(conn, customer_name="Unique Test", chat_id="chat_u1")
            b_id = b["bill"]["id"]

        # Bind b_id to chat_u2
        with immediate_transaction(conn):
            set_active_draft_service(conn, "chat_u2", b_id)

        # Verify bill is active for chat_u2 and NO LONGER active for chat_u1
        assert get_active_draft_id_service(conn, "chat_u2") == b_id
        assert get_active_draft_id_service(conn, "chat_u1") is None

def test_product_custom_reorder_level_and_low_stock(test_db):
    with get_db_connection(test_db) as conn:
        with immediate_transaction(conn):
            # 1. Create product with explicit reorder_level=3
            p = add_product_service(conn, {
                "name": "Custom Atta", "brand": "BrandX", "unit": "packet", "is_loose": False,
                "hsn_code": "1101", "gst_slab": 5, "cost_price": 200, "sell_price": 250,
                "mrp": 270, "quantity": 4, "reorder_level": 3
            })

        # 2. Retrieve product and verify reorder_level=3 stored in SQLite
        retrieved = get_stock_service(conn, query="Custom Atta")[0]
        assert retrieved["reorder_level"] == 3.0

        # 3. Verify low-stock status uses stored reorder_level=3:
        # Since quantity (4) > reorder_level (3), product MUST NOT appear in low-stock list
        low_stock_1 = get_stock_service(conn, low_stock_only=True)
        assert not any(item["name"] == "Custom Atta" for item in low_stock_1)

        # 4. Now reduce stock quantity to 2 (quantity <= 3)
        with immediate_transaction(conn):
            conn.execute("UPDATE products SET quantity = 2 WHERE name = 'Custom Atta'")

        # Verify low-stock status triggers when quantity (2) <= stored reorder_level (3)
        low_stock_2 = get_stock_service(conn, low_stock_only=True)
        matched = [item for item in low_stock_2 if item["name"] == "Custom Atta"]
        assert len(matched) == 1
        assert matched[0]["reorder_level"] == 3.0

def test_below_cost_no_override_fails(test_db):
    with get_db_connection(test_db) as conn:
        with immediate_transaction(conn):
            add_product_service(conn, {
                "name": "Test Biscuit", "brand": "BrandX", "unit": "packet", "is_loose": False,
                "hsn_code": "1905", "gst_slab": 5, "cost_price": 100, "sell_price": 80,
                "mrp": 110, "quantity": 10, "reorder_level": 3
            })
            b = start_bill_service(conn, customer_name="Arun", chat_id="chat_bc1")
            add_item_to_bill_service(conn, bill_id=None, product_id_or_name="Test Biscuit", quantity=1, chat_id="chat_bc1")

    # Call finalize_bill without explicit override in user message
    with get_db_connection(test_db) as conn:
        with pytest.raises(ValueError) as exc_info:
            with immediate_transaction(conn):
                finalize_bill_service(conn, bill_id=b["bill"]["id"], override_below_cost=False, chat_id="chat_bc1")

    assert "priced below cost" in str(exc_info.value)

    # Verify bill remains draft and stock unchanged
    with get_db_connection(test_db) as conn:
        det = get_bill_details_service(conn, bill_id=b["bill"]["id"])
        assert det["bill"]["status"] == "draft"
        stock = get_stock_service(conn, query="Test Biscuit")[0]
        assert stock["quantity"] == 10.0

def test_below_cost_explicit_same_message_override_succeeds(test_db):
    with get_db_connection(test_db) as conn:
        with immediate_transaction(conn):
            add_product_service(conn, {
                "name": "Test Biscuit", "brand": "BrandX", "unit": "packet", "is_loose": False,
                "hsn_code": "1905", "gst_slab": 5, "cost_price": 100, "sell_price": 80,
                "mrp": 110, "quantity": 10, "reorder_level": 3
            })
            b = start_bill_service(conn, customer_name="Arun", chat_id="chat_bc2")
            add_item_to_bill_service(conn, bill_id=None, product_id_or_name="Test Biscuit", quantity=1, chat_id="chat_bc2")

    from src.agent.context import current_user_message_var, current_chat_id_var
    token_msg = current_user_message_var.set("Finalize the bill and allow below cost sale")
    token_chat = current_chat_id_var.set("chat_bc2")
    try:
        with get_db_connection(test_db) as conn:
            with immediate_transaction(conn):
                fin = finalize_bill_service(conn, bill_id=b["bill"]["id"], override_below_cost=True, chat_id="chat_bc2")
        assert fin["bill"]["status"] == "finalized"
    finally:
        current_user_message_var.reset(token_msg)
        current_chat_id_var.reset(token_chat)

    # Verify stock decremented
    with get_db_connection(test_db) as conn:
        stock = get_stock_service(conn, query="Test Biscuit")[0]
        assert stock["quantity"] == 9.0

def test_below_cost_earlier_message_override_fails(test_db):
    with get_db_connection(test_db) as conn:
        with immediate_transaction(conn):
            add_product_service(conn, {
                "name": "Test Biscuit", "brand": "BrandX", "unit": "packet", "is_loose": False,
                "hsn_code": "1905", "gst_slab": 5, "cost_price": 100, "sell_price": 80,
                "mrp": 110, "quantity": 10, "reorder_level": 3
            })
            b = start_bill_service(conn, customer_name="Arun", chat_id="chat_bc3")
            add_item_to_bill_service(conn, bill_id=None, product_id_or_name="Test Biscuit", quantity=1, chat_id="chat_bc3")

    from src.agent.context import current_user_message_var, current_chat_id_var
    # Earlier message had authorization, but CURRENT message is just "Finalize the bill for Arun"
    token_msg = current_user_message_var.set("Finalize the bill for Arun")
    token_chat = current_chat_id_var.set("chat_bc3")
    try:
        with get_db_connection(test_db) as conn:
            with pytest.raises(ValueError) as exc_info:
                with immediate_transaction(conn):
                    finalize_bill_service(conn, bill_id=b["bill"]["id"], override_below_cost=True, chat_id="chat_bc3")
            assert "priced below cost" in str(exc_info.value)
    finally:
        current_user_message_var.reset(token_msg)
        current_chat_id_var.reset(token_chat)

    # Verify bill remains draft and stock unchanged at 10
    with get_db_connection(test_db) as conn:
        det = get_bill_details_service(conn, bill_id=b["bill"]["id"])
        assert det["bill"]["status"] == "draft"
        stock = get_stock_service(conn, query="Test Biscuit")[0]
        assert stock["quantity"] == 10.0

def test_duplicate_finalization_of_overridden_bill_no_duplicate_mutation(test_db):
    with get_db_connection(test_db) as conn:
        with immediate_transaction(conn):
            add_product_service(conn, {
                "name": "Test Biscuit", "brand": "BrandX", "unit": "packet", "is_loose": False,
                "hsn_code": "1905", "gst_slab": 5, "cost_price": 100, "sell_price": 80,
                "mrp": 110, "quantity": 10, "reorder_level": 3
            })
            b = start_bill_service(conn, customer_name="Arun", chat_id="chat_bc4")
            add_item_to_bill_service(conn, bill_id=None, product_id_or_name="Test Biscuit", quantity=1, chat_id="chat_bc4")

    from src.agent.context import current_user_message_var, current_chat_id_var
    token_msg = current_user_message_var.set("Finalize bill and override below cost")
    token_chat = current_chat_id_var.set("chat_bc4")
    try:
        # First finalization with same-message override
        with get_db_connection(test_db) as conn:
            with immediate_transaction(conn):
                fin1 = finalize_bill_service(conn, bill_id=b["bill"]["id"], override_below_cost=True, chat_id="chat_bc4")
        assert fin1["bill"]["status"] == "finalized"
        
        # Second finalization call (duplicate finalization)
        with get_db_connection(test_db) as conn:
            with immediate_transaction(conn):
                fin2 = finalize_bill_service(conn, bill_id=b["bill"]["id"], override_below_cost=True, chat_id="chat_bc4")
        assert fin2["bill"]["status"] == "finalized"
    finally:
        current_user_message_var.reset(token_msg)
        current_chat_id_var.reset(token_chat)

    # Verify stock was decremented ONCE (10 -> 9), NOT twice to 8
    with get_db_connection(test_db) as conn:
        stock = get_stock_service(conn, query="Test Biscuit")[0]
        assert stock["quantity"] == 9.0

def test_below_cost_tool_structured_refusal_and_no_stock_or_khata_change(test_db):
    from src.services.billing_service import BelowCostOverrideRequiredError
    from src.services.khata_service import get_khata_balance_service
    from src.agent.context import current_user_message_var, current_chat_id_var

    with get_db_connection(test_db) as conn:
        with immediate_transaction(conn):
            add_product_service(conn, {
                "name": "Test Biscuit", "brand": "BrandX", "unit": "packet", "is_loose": False,
                "hsn_code": "1905", "gst_slab": 5, "cost_price": 100, "sell_price": 80,
                "mrp": 110, "quantity": 10, "reorder_level": 3
            })
            b = start_bill_service(conn, customer_name="Arun", payment_mode="khata", chat_id="chat_bc5")
            add_item_to_bill_service(conn, bill_id=None, product_id_or_name="Test Biscuit", quantity=1, chat_id="chat_bc5")

    # Set user message without explicit below-cost override phrase
    token_msg = current_user_message_var.set("Finalize the bill for Arun")
    token_chat = current_chat_id_var.set("chat_bc5")
    try:
        with get_db_connection(test_db) as conn:
            with pytest.raises(BelowCostOverrideRequiredError) as exc_info:
                with immediate_transaction(conn):
                    finalize_bill_service(conn, bill_id=b["bill"]["id"], payment_mode="khata", override_below_cost=True, chat_id="chat_bc5")
            ex = exc_info.value
            assert ex.product_name == "Test Biscuit"
            assert ex.sell_price == 80.0
            assert ex.cost_price == 100.0
            assert "priced below cost" in ex.message
    finally:
        current_user_message_var.reset(token_msg)
        current_chat_id_var.reset(token_chat)

    # 2. Stock MUST remain unchanged at 10.0
    with get_db_connection(test_db) as conn:
        stock = get_stock_service(conn, query="Test Biscuit")[0]
        assert stock["quantity"] == 10.0

        # 3. Khata balance MUST remain 0.0 (NO khata charges created)
        khata_list = get_khata_balance_service(conn, customer_name="Arun")
        if khata_list:
            assert khata_list[0]["balance"] == 0.0

        # 4. Bill status MUST remain draft
        det = get_bill_details_service(conn, bill_id=b["bill"]["id"])
        assert det["bill"]["status"] == "draft"

def test_active_draft_priority_over_hallucinated_bill_id(test_db):
    from src.agent.context import current_user_message_var
    with get_db_connection(test_db) as conn:
        with immediate_transaction(conn):
            seed_sample_products(conn)
            # Create old drafts #17 and #18
            b17 = start_bill_service(conn, customer_name="Arun", chat_id="chat_res1")
            b18 = start_bill_service(conn, customer_name="Arun", chat_id="chat_res1")
            # Create active draft #19
            b19 = start_bill_service(conn, customer_name="Arun", chat_id="chat_res1")

    # Set user message without numeric bill ID ("finalize the bill")
    token_msg = current_user_message_var.set("Finalize the bill for Arun")
    try:
        with get_db_connection(test_db) as conn:
            # Even if tool call receives hallucinated bill_id=17, resolve_bill_id MUST target active draft #19
            res_id = resolve_bill_id(conn, bill_id=b17["bill"]["id"], chat_id="chat_res1")
            assert res_id == b19["bill"]["id"]
    finally:
        current_user_message_var.reset(token_msg)

def test_explicit_user_text_bill_id_overrides_active_draft(test_db):
    from src.agent.context import current_user_message_var
    with get_db_connection(test_db) as conn:
        with immediate_transaction(conn):
            seed_sample_products(conn)
            b17 = start_bill_service(conn, customer_name="Arun", chat_id="chat_res2")
            b19 = start_bill_service(conn, customer_name="Arun", chat_id="chat_res2")

    b17_id = b17["bill"]["id"]
    # User message explicitly mentions bill ID number (e.g. "finalize bill 1")
    token_msg = current_user_message_var.set(f"Finalize bill {b17_id}")
    try:
        with get_db_connection(test_db) as conn:
            res_id = resolve_bill_id(conn, bill_id=b17_id, chat_id="chat_res2")
            assert res_id == b17_id
    finally:
        current_user_message_var.reset(token_msg)

def test_sqlite_active_mapping_exists_immediately_after_start_bill(test_db):
    with get_db_connection(test_db) as conn:
        with immediate_transaction(conn):
            seed_sample_products(conn)
            b = start_bill_service(conn, customer_name="Test Mapping", chat_id="chat_mapped_1")
            b_id = b["bill"]["id"]

            # Query active_draft_bills directly from SQLite table
            row = conn.execute("SELECT bill_id FROM active_draft_bills WHERE chat_id = 'chat_mapped_1'").fetchone()
            assert row is not None
            assert row["bill_id"] == b_id

def test_tools_read_active_mapping_from_sqlite_using_chat_id(test_db):
    with get_db_connection(test_db) as conn:
        with immediate_transaction(conn):
            seed_sample_products(conn)
            b = start_bill_service(conn, customer_name="Read Test", chat_id="chat_read_1")
            b_id = b["bill"]["id"]

        with immediate_transaction(conn):
            # add_item_to_bill_service called with bill_id=None reads active_draft_bills table for chat_read_1
            b_added = add_item_to_bill_service(conn, bill_id=None, product_id_or_name="Tata Salt", quantity=2, chat_id="chat_read_1")
            assert b_added["bill"]["id"] == b_id

        with immediate_transaction(conn):
            # finalize_bill_service called with bill_id=None reads active_draft_bills table for chat_read_1
            b_fin = finalize_bill_service(conn, bill_id=None, chat_id="chat_read_1")
            assert b_fin["bill"]["id"] == b_id
            assert b_fin["bill"]["status"] == "finalized"

def test_below_cost_refused_even_if_tool_arg_true_without_user_text_override(test_db):
    with get_db_connection(test_db) as conn:
        with immediate_transaction(conn):
            add_product_service(conn, {
                "name": "Test Biscuit", "brand": "BrandX", "unit": "packet", "is_loose": False,
                "hsn_code": "1905", "gst_slab": 5, "cost_price": 100, "sell_price": 80,
                "mrp": 110, "quantity": 10, "reorder_level": 3
            })
            b = start_bill_service(conn, customer_name="Arun", chat_id="chat_no_txt_override")
            add_item_to_bill_service(conn, bill_id=None, product_id_or_name="Test Biscuit", quantity=1, chat_id="chat_no_txt_override")

    from src.agent.context import current_user_message_var, current_chat_id_var
    # User message DOES NOT contain any override language
    token_msg = current_user_message_var.set("Finalize the bill.")
    token_chat = current_chat_id_var.set("chat_no_txt_override")
    try:
        with get_db_connection(test_db) as conn:
            # Even though tool argument override_below_cost=True is passed, it MUST BE REFUSED because user text lacks explicit override
            with pytest.raises(ValueError) as exc_info:
                with immediate_transaction(conn):
                    finalize_bill_service(conn, bill_id=b["bill"]["id"], override_below_cost=True, chat_id="chat_no_txt_override")
            assert "priced below cost" in str(exc_info.value)
    finally:
        current_user_message_var.reset(token_msg)
        current_chat_id_var.reset(token_chat)

