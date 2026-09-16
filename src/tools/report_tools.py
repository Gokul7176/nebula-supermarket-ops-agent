from typing import Dict, Any, Optional
from datetime import date as dt_date
from src.db.connection import get_db_connection
from src.services.billing_service import get_bill_details_service
from src.documents.pdf_invoice import generate_pdf_invoice_file
from src.documents.pptx_deck import generate_pptx_analysis_deck_file

def close_day(date: Optional[str] = None) -> Dict[str, Any]:
    """
    Aggregates finalized bills for a given date (defaults to today):
    Total sales revenue, CGST/SGST tax collected, payment mode split, and top items.
    
    Args:
        date: Date string in YYYY-MM-DD format. Defaults to today's date if omitted.
    """
    target_date = date or str(dt_date.today())

    with get_db_connection() as conn:
        bills = conn.execute(
            """
            SELECT * FROM bills
            WHERE status = 'finalized' AND DATE(finalized_at) = DATE(?)
            """,
            (target_date,)
        ).fetchall()

        if not bills:
            return {
                "status": "success",
                "date": target_date,
                "message": f"No finalized bills found for date {target_date}.",
                "metrics": {
                    "total_sales": 0.0,
                    "total_bills": 0,
                    "total_cgst": 0.0,
                    "total_sgst": 0.0,
                    "total_tax": 0.0,
                    "payment_mode_split": {},
                    "top_items": []
                }
            }

        bill_ids = [b["id"] for b in bills]
        placeholders = ",".join("?" for _ in bill_ids)

        items_rows = conn.execute(
            f"""
            SELECT bi.*, p.name as product_name
            FROM bill_items bi
            JOIN products p ON bi.product_id = p.id
            WHERE bi.bill_id IN ({placeholders})
            """,
            bill_ids
        ).fetchall()

        total_sales = sum(i["line_total"] for i in items_rows)
        total_cgst = sum(i["cgst_amount"] for i in items_rows)
        total_sgst = sum(i["sgst_amount"] for i in items_rows)

        pm_split: Dict[str, float] = {}
        for b in bills:
            pm = b["payment_mode"] or "cash"
            # sum bill total
            b_items = [i for i in items_rows if i["bill_id"] == b["id"]]
            b_tot = sum(i["line_total"] for i in b_items)
            pm_split[pm] = round(pm_split.get(pm, 0.0) + b_tot, 2)

        # Top 5 items
        item_summary: Dict[str, Dict[str, Any]] = {}
        for i in items_rows:
            pname = i["product_name"]
            if pname not in item_summary:
                item_summary[pname] = {"quantity": 0.0, "revenue": 0.0}
            item_summary[pname]["quantity"] += i["quantity"]
            item_summary[pname]["revenue"] += i["line_total"]

        top_items = sorted(
            [{"name": k, "quantity": v["quantity"], "revenue": round(v["revenue"], 2)} for k, v in item_summary.items()],
            key=lambda x: x["revenue"],
            reverse=True
        )[:5]

        return {
            "status": "success",
            "date": target_date,
            "metrics": {
                "total_sales": round(total_sales, 2),
                "total_bills": len(bills),
                "total_cgst": round(total_cgst, 2),
                "total_sgst": round(total_sgst, 2),
                "total_tax": round(total_cgst + total_sgst, 2),
                "payment_mode_split": pm_split,
                "top_items": top_items
            }
        }

def generate_invoice_pdf(bill_id: int) -> Dict[str, Any]:
    """
    Renders a GST tax invoice PDF for a finalized bill using database details.
    Returns the absolute PDF file path.
    
    Args:
        bill_id: Finalized bill ID
    """
    with get_db_connection() as conn:
        bill_details = get_bill_details_service(conn, bill_id)
        pref_rows = conn.execute("SELECT key, value FROM preferences").fetchall()
        prefs = {r["key"]: r["value"] for r in pref_rows}

    if bill_details["bill"]["status"] != "finalized":
        raise ValueError(f"Bill #{bill_id} is in draft status and must be finalized before generating invoice PDF.")

    pdf_path = generate_pdf_invoice_file(bill_details, prefs)
    return {
        "status": "success",
        "bill_id": bill_id,
        "file_path": pdf_path,
        "file_name": f"invoice_bill_{bill_id}.pdf"
    }

def generate_analysis_deck(start_date: str, end_date: str) -> Dict[str, Any]:
    """
    Produces a PowerPoint (.pptx) analysis deck with Matplotlib charts for a date range.
    Queries live database metrics. Displays 'No data for this period' if empty.
    
    Args:
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
    """
    with get_db_connection() as conn:
        pptx_path = generate_pptx_analysis_deck_file(conn, start_date, end_date)

    return {
        "status": "success",
        "start_date": start_date,
        "end_date": end_date,
        "file_path": pptx_path,
        "file_name": f"kirana_analysis_{start_date}_to_{end_date}.pptx"
    }
