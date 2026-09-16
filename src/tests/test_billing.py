import os
import tempfile
import pytest
from src.db.connection import get_db_connection, immediate_transaction
from src.db.init_db import init_db
from src.services.stock_service import add_product_service, get_stock_service
from src.services.billing_service import (
    start_bill_service, add_item_to_bill_service, finalize_bill_service, calculate_line_item_gst
)
from src.services.khata_service import get_khata_balance_service

@pytest.fixture
def test_db():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_billing.db")
        init_db(db_path)
        yield db_path

def test_gst_line_item_calculation_and_rounding():
    # 5% slab on 3 units @ ₹105.33 = ₹315.99 taxable
    res = calculate_line_item_gst(quantity=3, unit_price=105.33, gst_slab=5)
    assert res["taxable_amount"] == 315.99
    # CGST (2.5%) = 7.89975 -> rounded to 7.90
    assert res["cgst_amount"] == 7.90
    assert res["sgst_amount"] == 7.90
    assert res["total_tax"] == 15.80
    assert res["line_total"] == 331.79

def test_oversell_refusal_and_atomic_rollback(test_db):
    with get_db_connection(test_db) as conn:
        with immediate_transaction(conn):
            p = add_product_service(conn, {
                "name": "Atta 5kg", "brand": "BrandA", "unit": "packet", "is_loose": False,
                "hsn_code": "1101", "gst_slab": 5, "cost_price": 200, "sell_price": 250,
                "mrp": 270, "quantity": 2, "reorder_level": 5
            })

        with immediate_transaction(conn):
            bill = start_bill_service(conn, "Customer A")
            add_item_to_bill_service(conn, bill["bill"]["id"], "Atta 5kg", quantity=5)

        # Finalizing 5 packets when stock is 2 MUST raise ValueError
        with pytest.raises(ValueError) as exc_info:
            with immediate_transaction(conn):
                finalize_bill_service(conn, bill["bill"]["id"])

        assert "Stock insufficient" in str(exc_info.value)

        # Verify stock remains unchanged at 2
        stock = get_stock_service(conn, "Atta 5kg")[0]
        assert stock["quantity"] == 2.0

def test_below_cost_refusal_and_override(test_db):
    with get_db_connection(test_db) as conn:
        with immediate_transaction(conn):
            p = add_product_service(conn, {
                "name": "Rice 10kg", "brand": "BrandB", "unit": "packet", "is_loose": False,
                "hsn_code": "1006", "gst_slab": 5, "cost_price": 400, "sell_price": 350,
                "mrp": 450, "quantity": 10, "reorder_level": 5
            })

        with immediate_transaction(conn):
            bill = start_bill_service(conn, "Customer B")
            add_item_to_bill_service(conn, bill["bill"]["id"], "Rice 10kg", quantity=1)

        # Should fail without override
        with pytest.raises(ValueError) as exc_info:
            with immediate_transaction(conn):
                finalize_bill_service(conn, bill["bill"]["id"], override_below_cost=False)

        assert "priced below cost" in str(exc_info.value)

        # Should succeed with override_below_cost=True
        with immediate_transaction(conn):
            fin = finalize_bill_service(conn, bill["bill"]["id"], override_below_cost=True)

        assert fin["bill"]["status"] == "finalized"

def test_atomic_khata_finalization(test_db):
    with get_db_connection(test_db) as conn:
        with immediate_transaction(conn):
            add_product_service(conn, {
                "name": "Sugar 1kg", "brand": "Loose", "unit": "kg", "is_loose": True,
                "hsn_code": "1701", "gst_slab": 0, "cost_price": 35, "sell_price": 42,
                "mrp": 45, "quantity": 20, "reorder_level": 5
            })

        with immediate_transaction(conn):
            bill = start_bill_service(conn, "Ramesh", payment_mode="khata")
            add_item_to_bill_service(conn, bill["bill"]["id"], "Sugar 1kg", quantity=2)

        with immediate_transaction(conn):
            fin = finalize_bill_service(conn, bill["bill"]["id"], payment_mode="khata")

        assert fin["bill"]["status"] == "finalized"

        # Verify khata balance updated to 84.00
        khata = get_khata_balance_service(conn, "Ramesh")[0]
        assert khata["balance"] == 84.0

def test_bill_finalization_idempotency(test_db):
    with get_db_connection(test_db) as conn:
        with immediate_transaction(conn):
            add_product_service(conn, {
                "name": "Soap 100g", "brand": "BrandC", "unit": "piece", "is_loose": False,
                "hsn_code": "3401", "gst_slab": 18, "cost_price": 20, "sell_price": 30,
                "mrp": 35, "quantity": 10, "reorder_level": 5
            })

        with immediate_transaction(conn):
            bill = start_bill_service(conn, "Suresh", payment_mode="cash")
            add_item_to_bill_service(conn, bill["bill"]["id"], "Soap 100g", quantity=2)

        # First finalization
        with immediate_transaction(conn):
            fin1 = finalize_bill_service(conn, bill["bill"]["id"])

        stock_after_first = get_stock_service(conn, "Soap 100g")[0]["quantity"]
        assert stock_after_first == 8.0

        # Second finalization call (IDEMPOTENT REPLAY)
        with immediate_transaction(conn):
            fin2 = finalize_bill_service(conn, bill["bill"]["id"])

        stock_after_second = get_stock_service(conn, "Soap 100g")[0]["quantity"]
        # Stock must NOT be decremented again!
        assert stock_after_second == 8.0
        assert fin1["grand_total"] == fin2["grand_total"]
