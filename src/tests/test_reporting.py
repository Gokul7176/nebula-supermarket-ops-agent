import os
import tempfile
import sqlite3
import pytest
from datetime import date, datetime, timedelta

from src.db.connection import get_db_connection, immediate_transaction
from src.db.init_db import init_db
from src.utils.date_utils import resolve_single_date, resolve_date_range
from src.services.stock_service import add_product_service
from src.services.billing_service import start_bill_service, add_item_to_bill_service, finalize_bill_service
from src.tools.report_tools import close_day, generate_analysis_deck
from src.agent.loop import process_user_message_agent

@pytest.fixture
def test_report_db():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_reporting.db")
        init_db(db_path)
        yield db_path

from dotenv import load_dotenv
load_dotenv()

def seed_test_sales(conn, target_date_str: str):
    add_product_service(conn, {
        "name": "Fortune Rice 5kg", "brand": "Fortune", "unit": "packet", "is_loose": False,
        "hsn_code": "1006", "gst_slab": 5, "cost_price": 300, "sell_price": 380,
        "mrp": 400, "quantity": 100, "reorder_level": 5
    })
    add_product_service(conn, {
        "name": "Amul Butter 100g", "brand": "Amul", "unit": "packet", "is_loose": False,
        "hsn_code": "0405", "gst_slab": 12, "cost_price": 45, "sell_price": 55,
        "mrp": 60, "quantity": 50, "reorder_level": 5
    })

    b = start_bill_service(conn, customer_name="Rohan", chat_id="chat_rep")
    add_item_to_bill_service(conn, bill_id=b["bill"]["id"], product_id_or_name="Fortune Rice 5kg", quantity=2, chat_id="chat_rep")
    add_item_to_bill_service(conn, bill_id=b["bill"]["id"], product_id_or_name="Amul Butter 100g", quantity=3, chat_id="chat_rep")
    
    fin = finalize_bill_service(conn, bill_id=b["bill"]["id"], payment_mode="cash", chat_id="chat_rep")
    b_id = fin["bill"]["id"]

    conn.execute(
        "UPDATE bills SET finalized_at = ? WHERE id = ?",
        (f"{target_date_str} 14:30:00", b_id)
    )

def test_resolve_date_range_today():
    today_str = date.today().strftime("%Y-%m-%d")
    s, e = resolve_date_range("today")
    assert s == today_str
    assert e == today_str

def test_resolve_date_range_this_week():
    ref = date.today()
    monday_str = (ref - timedelta(days=ref.weekday())).strftime("%Y-%m-%d")
    sunday_str = ((ref - timedelta(days=ref.weekday())) + timedelta(days=6)).strftime("%Y-%m-%d")
    
    s, e = resolve_date_range("this week")
    assert s == monday_str
    assert e == sunday_str

def test_resolve_date_range_explicit():
    s, e = resolve_date_range("2026-09-01", "2026-09-15")
    assert s == "2026-09-01"
    assert e == "2026-09-15"

def test_resolve_date_range_empty():
    ref = date.today()
    monday_str = (ref - timedelta(days=ref.weekday())).strftime("%Y-%m-%d")
    sunday_str = ((ref - timedelta(days=ref.weekday())) + timedelta(days=6)).strftime("%Y-%m-%d")

    s, e = resolve_date_range(None, None)
    assert s == monday_str
    assert e == sunday_str

def test_close_day_returns_real_sales_data(test_report_db):
    today_str = date.today().strftime("%Y-%m-%d")
    with get_db_connection(test_report_db) as conn:
        with immediate_transaction(conn):
            seed_test_sales(conn, today_str)

    res = close_day(today_str, db_path=test_report_db)
    assert res["status"] == "success"
    assert res["metrics"]["total_bills"] == 1
    assert res["metrics"]["total_sales"] > 0
    assert len(res["metrics"]["sold_items"]) == 2
    assert "Fortune Rice 5kg" in res["summary"]
    assert "Amul Butter 100g" in res["summary"]

def test_generate_analysis_deck_speed_and_file_creation(test_report_db):
    res = generate_analysis_deck(start_date="this week", db_path=test_report_db)
    assert res["status"] == "success"
    assert os.path.exists(res["file_path"])
    assert os.path.getsize(res["file_path"]) > 1000

def test_show_only_what_i_sold_today_agent_response():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        pytest.skip("GEMINI_API_KEY not set in environment.")

    reply, files = process_user_message_agent("Show only what I sold today.", chat_id="chat_sold_today_test")
    assert reply is not None
    assert len(reply) > 20
    assert reply != "Request processed successfully."

def test_multiple_bills_same_product_aggregation_and_reconciliation(test_report_db):
    today_str = date.today().strftime("%Y-%m-%d")
    with get_db_connection(test_report_db) as conn:
        with immediate_transaction(conn):
            add_product_service(conn, {
                "name": "Maggi 70g", "brand": "Nestle", "unit": "packet", "is_loose": False,
                "hsn_code": "1902", "gst_slab": 12, "cost_price": 10, "sell_price": 14,
                "mrp": 15, "quantity": 100, "reorder_level": 5
            })

            # Bill A: 2 Maggi 70g finalized today
            ba = start_bill_service(conn, customer_name="Customer A", chat_id="chat_agg_a")
            add_item_to_bill_service(conn, bill_id=ba["bill"]["id"], product_id_or_name="Maggi 70g", quantity=2, chat_id="chat_agg_a")
            finalize_bill_service(conn, bill_id=ba["bill"]["id"], payment_mode="cash", chat_id="chat_agg_a")

            # Bill B: 3 Maggi 70g finalized today
            bb = start_bill_service(conn, customer_name="Customer B", chat_id="chat_agg_b")
            add_item_to_bill_service(conn, bill_id=bb["bill"]["id"], product_id_or_name="Maggi 70g", quantity=3, chat_id="chat_agg_b")
            finalize_bill_service(conn, bill_id=bb["bill"]["id"], payment_mode="upi", chat_id="chat_agg_b")

    res = close_day(today_str, db_path=test_report_db)
    assert res["status"] == "success"
    assert res["metrics"]["total_bills"] == 2

    # 1. Expected Maggi 70g total quantity across Bill A + Bill B == 5.0
    maggi_item = next(i for i in res["metrics"]["sold_items"] if i["name"] == "Maggi 70g")
    assert maggi_item["quantity"] == 5.0

    # 2. Reconciliation Assertion: sum(sold_items revenue) == total_sales revenue
    sum_items_revenue = round(sum(i["revenue"] for i in res["metrics"]["sold_items"]), 2)
    assert sum_items_revenue == res["metrics"]["total_sales"]

