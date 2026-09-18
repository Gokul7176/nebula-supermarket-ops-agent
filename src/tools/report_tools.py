from typing import Dict, Any, Optional
from datetime import date as dt_date
from src.db.connection import get_db_connection
from src.services.billing_service import get_bill_details_service
from src.documents.pdf_invoice import generate_pdf_invoice_file
from src.documents.pptx_deck import generate_pptx_analysis_deck_file
from src.utils.date_utils import resolve_single_date, resolve_date_range

def close_day(date: Optional[str] = None, db_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Aggregates finalized bills for a given date (defaults to today's date):
    Total sales revenue, CGST/SGST tax collected, payment mode split, and detailed list of all sold items with quantities.
    
    Args:
        date: Optional date string in YYYY-MM-DD format or relative term ('today', 'yesterday'). Defaults to today's date if omitted.
        db_path: Optional database file path for testing override
    """
    target_date = resolve_single_date(date)

    with get_db_connection(db_path) as conn:
        bills = conn.execute(
            """
            SELECT * FROM bills
            WHERE status = 'finalized'
              AND (
                DATE(finalized_at, 'localtime') = DATE(?)
                OR DATE(finalized_at) = DATE(?)
              )
            ORDER BY id ASC
            """,
            (target_date, target_date)
        ).fetchall()

        if not bills:
            summary_text = f"Sales Report for {target_date}:\n• Total Sales: ₹0.00\n• Finalized Bills: 0\n• No items were sold on {target_date}."
            return {
                "status": "success",
                "date": target_date,
                "summary": summary_text,
                "metrics": {
                    "total_sales": 0.0,
                    "total_bills": 0,
                    "total_cgst": 0.0,
                    "total_sgst": 0.0,
                    "total_tax": 0.0,
                    "payment_mode_split": {},
                    "sold_items": [],
                    "top_items": []
                }
            }

        bill_ids = [b["id"] for b in bills]
        placeholders = ",".join("?" for _ in bill_ids)

        items_rows = conn.execute(
            f"""
            SELECT bi.*, p.id as p_id, p.name as product_name
            FROM bill_items bi
            JOIN products p ON bi.product_id = p.id
            WHERE bi.bill_id IN ({placeholders})
            ORDER BY bi.bill_id ASC, bi.id ASC
            """,
            bill_ids
        ).fetchall()

        total_sales = round(sum(i["line_total"] for i in items_rows), 2)
        total_cgst = round(sum(i["cgst_amount"] for i in items_rows), 2)
        total_sgst = round(sum(i["sgst_amount"] for i in items_rows), 2)

        pm_split: Dict[str, float] = {}
        for b in bills:
            pm = b["payment_mode"] or "cash"
            b_items = [i for i in items_rows if i["bill_id"] == b["id"]]
            b_tot = sum(i["line_total"] for i in b_items)
            pm_split[pm] = round(pm_split.get(pm, 0.0) + b_tot, 2)

        # Group by product_id to ensure exact mapping and aggregation across all bills
        product_summary: Dict[int, Dict[str, Any]] = {}
        for i in items_rows:
            p_id = i["p_id"]
            pname = i["product_name"]
            qty = float(i["quantity"])
            ltot = float(i["line_total"])

            if p_id not in product_summary:
                product_summary[p_id] = {
                    "product_id": p_id,
                    "name": pname,
                    "quantity": 0.0,
                    "revenue": 0.0
                }
            product_summary[p_id]["quantity"] += qty
            product_summary[p_id]["revenue"] += ltot

        sold_items_list = []
        for p_id, item in product_summary.items():
            sold_items_list.append({
                "product_id": p_id,
                "name": item["name"],
                "quantity": round(item["quantity"], 4),
                "revenue": round(item["revenue"], 2)
            })

        sold_items_list.sort(key=lambda x: x["revenue"], reverse=True)

        lines = [
            f"Sales Report for {target_date}:",
            f"• Total Sales: ₹{total_sales:,.2f}",
            f"• Finalized Bills: {len(bills)}",
            f"• Total Tax Collected: ₹{round(total_cgst + total_sgst, 2):,.2f}",
            "• Items Sold:"
        ]
        for item in sold_items_list:
            qty_str = f"{int(item['quantity'])}" if item['quantity'].is_integer() else f"{item['quantity']}"
            lines.append(f"  - {item['name']}: {qty_str} sold (Total: ₹{item['revenue']:,.2f})")

        summary_text = "\n".join(lines)

        return {
            "status": "success",
            "date": target_date,
            "summary": summary_text,
            "metrics": {
                "total_sales": total_sales,
                "total_bills": len(bills),
                "total_cgst": total_cgst,
                "total_sgst": total_sgst,
                "total_tax": round(total_cgst + total_sgst, 2),
                "payment_mode_split": pm_split,
                "sold_items": sold_items_list,
                "top_items": sold_items_list[:5]
            }
        }

def generate_invoice_pdf(bill_id: int, db_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Renders a GST tax invoice PDF for a finalized bill using database details.
    Returns the absolute PDF file path.
    
    Args:
        bill_id: Finalized bill ID
        db_path: Optional database file path for testing override
    """
    with get_db_connection(db_path) as conn:
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

def generate_analysis_deck(start_date: Optional[str] = None, end_date: Optional[str] = None, db_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Produces a PowerPoint (.pptx) analysis deck with Matplotlib charts for a date range.
    Queries live database metrics. Displays 'No data for this period' if empty.
    
    Args:
        start_date: Optional start date in YYYY-MM-DD format or relative term ('today', 'this week', 'this month', 'yesterday'). Defaults to 'this week' (Monday of current week) if omitted.
        end_date: Optional end date in YYYY-MM-DD format. Defaults to today or end of period if omitted.
        db_path: Optional database file path for testing override
    """
    res_start_date, res_end_date = resolve_date_range(start_date, end_date)

    with get_db_connection(db_path) as conn:
        pptx_path = generate_pptx_analysis_deck_file(conn, res_start_date, res_end_date)

    return {
        "status": "success",
        "start_date": res_start_date,
        "end_date": res_end_date,
        "file_path": pptx_path,
        "file_name": f"kirana_analysis_{res_start_date}_to_{res_end_date}.pptx"
    }
