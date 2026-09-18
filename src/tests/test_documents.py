import os
import tempfile
import pytest
from src.db.connection import get_db_connection, immediate_transaction
from src.db.init_db import init_db
from src.services.stock_service import add_product_service
from src.services.billing_service import start_bill_service, add_item_to_bill_service, finalize_bill_service, get_bill_details_service
from src.documents.pdf_invoice import generate_pdf_invoice_file
from src.documents.pptx_deck import generate_pptx_analysis_deck_file

@pytest.fixture
def test_db():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_docs.db")
        init_db(db_path)
        yield db_path

def test_pdf_invoice_generation(test_db):
    from src.documents.pdf_invoice import get_invoice_font_names
    norm_font, bold_font = get_invoice_font_names()
    assert norm_font != "Helvetica", "A Unicode TrueType font must be registered for PDF currency rendering"

    with get_db_connection(test_db) as conn:
        with immediate_transaction(conn):
            add_product_service(conn, {
                "name": "Tea 250g", "brand": "BrandT", "unit": "packet", "is_loose": False,
                "hsn_code": "0902", "gst_slab": 5, "cost_price": 80, "sell_price": 100,
                "mrp": 110, "quantity": 50, "reorder_level": 5
            })

        with immediate_transaction(conn):
            bill = start_bill_service(conn, "Anil Kumar", payment_mode="upi")
            add_item_to_bill_service(conn, bill["bill"]["id"], "Tea 250g", quantity=2)
            fin_bill = finalize_bill_service(conn, bill["bill"]["id"], payment_reference="UPI998877")

        bill_details = get_bill_details_service(conn, fin_bill["bill"]["id"])
        prefs = {"shop_name": "Testing Kirana", "shop_gstin": "33AAAAA1111B1Z2"}

        pdf_path = generate_pdf_invoice_file(bill_details, prefs)
        assert os.path.exists(pdf_path)
        assert os.path.getsize(pdf_path) > 1000

def test_pptx_deck_generation_with_data_and_empty_range(test_db):
    from pptx import Presentation
    with get_db_connection(test_db) as conn:
        # 1. Empty Date Range Test
        pptx_empty = generate_pptx_analysis_deck_file(conn, "2020-01-01", "2020-01-02")
        assert os.path.exists(pptx_empty)
        assert os.path.getsize(pptx_empty) > 1000
        prs_empty = Presentation(pptx_empty)
        assert len(prs_empty.slides) == 1

        # 2. Date Range with Data
        with immediate_transaction(conn):
            add_product_service(conn, {
                "name": "Milk 1L", "brand": "BrandM", "unit": "litre", "is_loose": False,
                "hsn_code": "0401", "gst_slab": 0, "cost_price": 45, "sell_price": 54,
                "mrp": 55, "quantity": 100, "reorder_level": 10
            })
            b = start_bill_service(conn, "Sunil")
            add_item_to_bill_service(conn, b["bill"]["id"], "Milk 1L", 3)
            finalize_bill_service(conn, b["bill"]["id"])

        import datetime
        today = str(datetime.date.today())
        pptx_data = generate_pptx_analysis_deck_file(conn, today, today)
        assert os.path.exists(pptx_data)
        assert os.path.getsize(pptx_data) > 1000

        prs_data = Presentation(pptx_data)
        assert len(prs_data.slides) == 5
        slide5_text = prs_data.slides[4].shapes[0].text_frame.text
        assert "GST Breakdown" in slide5_text

