import os
import tempfile
import threading
import pytest
from src.db.connection import get_db_connection, immediate_transaction
from src.db.init_db import init_db
from src.services.stock_service import add_product_service, get_stock_service
from src.services.billing_service import start_bill_service, add_item_to_bill_service, finalize_bill_service
from src.services.khata_service import get_khata_balance_service

def test_concurrent_bill_finalization_stock_lock():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_concurrency.db")
        init_db(db_path)

        # Setup 1 packet in stock
        with get_db_connection(db_path) as conn:
            with immediate_transaction(conn):
                add_product_service(conn, {
                    "name": "Limited Item", "brand": "BrandX", "unit": "packet", "is_loose": False,
                    "hsn_code": "1001", "gst_slab": 5, "cost_price": 50, "sell_price": 70,
                    "mrp": 80, "quantity": 1, "reorder_level": 5
                })

                bill1 = start_bill_service(conn, "Customer 1", payment_mode="khata")
                add_item_to_bill_service(conn, bill1["bill"]["id"], "Limited Item", 1)

                bill2 = start_bill_service(conn, "Customer 2", payment_mode="khata")
                add_item_to_bill_service(conn, bill2["bill"]["id"], "Limited Item", 1)

        b1_id = bill1["bill"]["id"]
        b2_id = bill2["bill"]["id"]

        results = {}

        def finalize_worker(bill_id, worker_key):
            try:
                with get_db_connection(db_path) as conn:
                    with immediate_transaction(conn):
                        res = finalize_bill_service(conn, bill_id, payment_mode="khata")
                        results[worker_key] = {"status": "success", "res": res}
            except Exception as e:
                results[worker_key] = {"status": "error", "error": str(e)}

        t1 = threading.Thread(target=finalize_worker, args=(b1_id, "worker1"))
        t2 = threading.Thread(target=finalize_worker, args=(b2_id, "worker2"))

        t1.start()
        t2.start()

        t1.join()
        t2.join()

        # Check outcomes: exactly 1 success and 1 error
        statuses = [results["worker1"]["status"], results["worker2"]["status"]]
        assert "success" in statuses
        assert "error" in statuses

        # Verify stock quantity is 0 (NOT negative!)
        with get_db_connection(db_path) as conn:
            stock = get_stock_service(conn, "Limited Item")[0]
            assert stock["quantity"] == 0.0

            # Verify khata credit balance is exactly 73.50 (₹70 + 5% GST = ₹73.50) for only 1 customer
            k1 = get_khata_balance_service(conn, "Customer 1")
            k2 = get_khata_balance_service(conn, "Customer 2")
            
            b1_bal = k1[0]["balance"] if k1 else 0.0
            b2_bal = k2[0]["balance"] if k2 else 0.0

            assert (b1_bal == 73.5 and b2_bal == 0.0) or (b1_bal == 0.0 and b2_bal == 73.5)
