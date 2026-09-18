import os
import tempfile
import sqlite3
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
matplotlib.rcParams['font.sans-serif'] = ['DejaVu Sans', 'Arial', 'Helvetica']
matplotlib.rcParams['font.family'] = 'sans-serif'
import matplotlib.pyplot as plt

# Pre-warm matplotlib rendering pipeline on module import to eliminate font-cache indexing delay
try:
    _fig, _ax = plt.subplots(figsize=(1, 1), dpi=50)
    _ax.text(0.5, 0.5, "warmup")
    _fig.savefig(os.path.devnull, format='png')
    plt.close(_fig)
except Exception:
    pass

from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN

def generate_pptx_analysis_deck_file(conn: sqlite3.Connection, start_date: str, end_date: str) -> str:
    """
    Generates a PowerPoint (.pptx) analysis deck with Matplotlib charts for a date range.
    Queries database directly. Displays 'No data for this period' if date range is empty.
    """
    temp_dir = tempfile.gettempdir()
    file_path = os.path.join(temp_dir, f"kirana_analysis_{start_date}_to_{end_date}.pptx")

    prs = Presentation()
    prs.slide_width = Inches(10)
    prs.slide_height = Inches(5.625) # 16:9 widescreen

    blank_layout = prs.slide_layouts[6] # Blank slide layout

    # Helper colors
    NAVY = RGBColor(26, 54, 93)
    GRAY = RGBColor(74, 85, 104)
    WHITE = RGBColor(255, 255, 255)

    def add_title(slide, text: str):
        txBox = slide.shapes.add_textbox(Inches(0.6), Inches(0.4), Inches(8.8), Inches(0.8))
        tf = txBox.text_frame
        p = tf.paragraphs[0]
        p.text = text
        p.font.bold = True
        p.font.size = Pt(24)
        p.font.color.rgb = NAVY
        p.alignment = PP_ALIGN.LEFT

    # Fetch Sales Data for Date Range
    bills_query = """
    SELECT id, status, customer_name, payment_mode, finalized_at
    FROM bills
    WHERE status = 'finalized'
      AND (
        (DATE(finalized_at, 'localtime') >= DATE(?) AND DATE(finalized_at, 'localtime') <= DATE(?))
        OR (DATE(finalized_at) >= DATE(?) AND DATE(finalized_at) <= DATE(?))
      )
    """
    finalized_bills = conn.execute(bills_query, (start_date, end_date, start_date, end_date)).fetchall()

    bill_ids = [b["id"] for b in finalized_bills]

    # Slide 1: Title & Executive Summary
    slide1 = prs.slides.add_slide(blank_layout)
    add_title(slide1, f"Store Operations Analysis ({start_date} to {end_date})")

    if not bill_ids:
        # No Data Slide Handling
        txBox = slide1.shapes.add_textbox(Inches(1.0), Inches(2.0), Inches(8.0), Inches(2.0))
        tf = txBox.text_frame
        p = tf.paragraphs[0]
        p.text = f"No transaction data available for the period\n{start_date} to {end_date}"
        p.font.size = Pt(22)
        p.font.color.rgb = GRAY
        p.alignment = PP_ALIGN.CENTER
        
        prs.save(file_path)
        return file_path

    # Query detailed metrics
    placeholders = ",".join("?" for _ in bill_ids)
    items_query = f"""
    SELECT bi.*, p.name as product_name, p.brand, p.gst_slab
    FROM bill_items bi
    JOIN products p ON bi.product_id = p.id
    WHERE bi.bill_id IN ({placeholders})
    """
    items_data = conn.execute(items_query, bill_ids).fetchall()

    total_revenue = sum(i["line_total"] for i in items_data)
    total_tax = sum(i["cgst_amount"] + i["sgst_amount"] for i in items_data)
    total_orders = len(bill_ids)
    avg_order_val = total_revenue / total_orders if total_orders > 0 else 0

    # Render Executive Summary Metrics on Slide 1
    summary_text = (
        f"• Total Revenue Generated: ₹{total_revenue:,.2f}\n"
        f"• Total Finalized Bills: {total_orders}\n"
        f"• Average Order Value: ₹{avg_order_val:,.2f}\n"
        f"• Total GST Tax Collected: ₹{total_tax:,.2f}"
    )
    txBox = slide1.shapes.add_textbox(Inches(1.0), Inches(1.8), Inches(8.0), Inches(3.0))
    tf = txBox.text_frame
    p = tf.paragraphs[0]
    p.text = summary_text
    p.font.size = Pt(18)
    p.font.color.rgb = GRAY
    p.line_spacing = 1.4

    # Slide 2: Sales Trend Chart
    trend_query = f"""
    SELECT DATE(finalized_at) as sale_date, SUM(bi.line_total) as daily_sales
    FROM bills b
    JOIN bill_items bi ON b.id = bi.bill_id
    WHERE b.id IN ({placeholders})
    GROUP BY DATE(finalized_at)
    ORDER BY sale_date ASC
    """
    trend_rows = conn.execute(trend_query, bill_ids).fetchall()
    dates = [r["sale_date"] for r in trend_rows]
    sales = [r["daily_sales"] for r in trend_rows]

    fig, ax = plt.subplots(figsize=(8, 3.5), dpi=150)
    ax.bar(dates, sales, color='#2B6CB0', width=0.5)
    ax.set_title("Daily Sales Trend (₹)", fontsize=12, fontweight='bold', color='#1A365D')
    ax.set_ylabel("Revenue (₹)")
    ax.grid(axis='y', linestyle='--', alpha=0.5)
    plt.xticks(rotation=30, ha='right', fontsize=9)
    plt.tight_layout()

    chart1_path = os.path.join(temp_dir, "chart1.png")
    fig.savefig(chart1_path)
    plt.close(fig)

    slide2 = prs.slides.add_slide(blank_layout)
    add_title(slide2, "Sales Revenue Performance")
    slide2.shapes.add_picture(chart1_path, Inches(1.0), Inches(1.4), Inches(8.0), Inches(3.8))

    # Slide 3: Top SKUs Chart
    top_skus_query = f"""
    SELECT p.name as product_name, SUM(bi.quantity) as total_qty, SUM(bi.line_total) as total_val
    FROM bill_items bi
    JOIN products p ON bi.product_id = p.id
    WHERE bi.bill_id IN ({placeholders})
    GROUP BY p.id
    ORDER BY total_val DESC
    LIMIT 5
    """
    top_skus = conn.execute(top_skus_query, bill_ids).fetchall()
    p_names = [r["product_name"] for r in top_skus][::-1] # Reverse for horizontal bar chart
    p_vals = [r["total_val"] for r in top_skus][::-1]

    fig, ax = plt.subplots(figsize=(8, 3.5), dpi=150)
    ax.barh(p_names, p_vals, color='#319795')
    ax.set_title("Top 5 SKUs by Sales Value (₹)", fontsize=12, fontweight='bold', color='#1A365D')
    ax.set_xlabel("Total Sales (₹)")
    ax.grid(axis='x', linestyle='--', alpha=0.5)
    plt.tight_layout()

    chart2_path = os.path.join(temp_dir, "chart2.png")
    fig.savefig(chart2_path)
    plt.close(fig)

    slide3 = prs.slides.add_slide(blank_layout)
    add_title(slide3, "Top Selling Products")
    slide3.shapes.add_picture(chart2_path, Inches(1.0), Inches(1.4), Inches(8.0), Inches(3.8))

    # Slide 4: Inventory Health Chart
    inv_rows = conn.execute("SELECT quantity, reorder_level FROM products").fetchall()
    out_of_stock = sum(1 for r in inv_rows if r["quantity"] <= 0)
    low_stock = sum(1 for r in inv_rows if 0 < r["quantity"] <= r["reorder_level"])
    healthy = sum(1 for r in inv_rows if r["quantity"] > r["reorder_level"])

    fig, ax = plt.subplots(figsize=(8, 3.5), dpi=150)
    labels = ['Out of Stock', 'Low Stock', 'Healthy']
    sizes = [out_of_stock, low_stock, healthy]
    colors_pie = ['#E53E3E', '#DD6B20', '#38A169']
    
    # Filter non-zero
    filtered_data = [(l, s, c) for l, s, c in zip(labels, sizes, colors_pie) if s > 0]
    if filtered_data:
        f_labels, f_sizes, f_colors = zip(*filtered_data)
        ax.pie(f_sizes, labels=f_labels, colors=f_colors, autopct='%1.1f%%', startangle=140)
    else:
        ax.text(0.5, 0.5, "No Products Registered", ha='center', va='center')

    ax.set_title("Current Stock Health Overview", fontsize=12, fontweight='bold', color='#1A365D')
    plt.tight_layout()

    chart3_path = os.path.join(temp_dir, "chart3.png")
    fig.savefig(chart3_path)
    plt.close(fig)

    slide4 = prs.slides.add_slide(blank_layout)
    add_title(slide4, "Inventory Stock Health")
    slide4.shapes.add_picture(chart3_path, Inches(1.0), Inches(1.4), Inches(8.0), Inches(3.8))

    # Slide 5: GST Breakdown
    slide5 = prs.slides.add_slide(blank_layout)
    add_title(slide5, "GST Breakdown")

    standard_slabs = [0.0, 5.0, 12.0, 18.0]
    present_slabs = [float(i["gst_slab_at_sale"]) for i in items_data if i["gst_slab_at_sale"] is not None]
    all_slabs = sorted(list(set(standard_slabs + present_slabs)))

    slab_summary = []
    tot_cgst_sum = 0.0
    tot_sgst_sum = 0.0
    tot_gst_sum = 0.0

    for slab in all_slabs:
        slab_items = [i for i in items_data if float(i["gst_slab_at_sale"]) == slab]
        cgst = sum(i["cgst_amount"] for i in slab_items)
        sgst = sum(i["sgst_amount"] for i in slab_items)
        tot = cgst + sgst
        slab_summary.append({
            "slab": slab,
            "cgst": cgst,
            "sgst": sgst,
            "total": tot
        })
        tot_cgst_sum += cgst
        tot_sgst_sum += sgst
        tot_gst_sum += tot

    rows = len(slab_summary) + 2  # Header + slabs + Total row
    cols = 4
    table_shape = slide5.shapes.add_table(rows, cols, Inches(1.0), Inches(1.4), Inches(8.0), Inches(0.45 * rows))
    table = table_shape.table

    table.columns[0].width = Inches(2.0)
    table.columns[1].width = Inches(2.0)
    table.columns[2].width = Inches(2.0)
    table.columns[3].width = Inches(2.0)

    headers = ["GST Slab", "CGST Collected", "SGST Collected", "Total GST"]
    for c_idx, h_text in enumerate(headers):
        cell = table.cell(0, c_idx)
        cell.text = h_text
        cell.fill.solid()
        cell.fill.fore_color.rgb = NAVY
        p = cell.text_frame.paragraphs[0]
        p.font.bold = True
        p.font.size = Pt(13)
        p.font.color.rgb = WHITE
        p.alignment = PP_ALIGN.CENTER if c_idx == 0 else PP_ALIGN.RIGHT

    for r_idx, row_data in enumerate(slab_summary, 1):
        bg = RGBColor(245, 247, 250) if r_idx % 2 == 1 else WHITE
        slab_str = f"{row_data['slab']:g}%"
        vals = [
            slab_str,
            f"₹{row_data['cgst']:,.2f}",
            f"₹{row_data['sgst']:,.2f}",
            f"₹{row_data['total']:,.2f}"
        ]
        for c_idx, val_str in enumerate(vals):
            cell = table.cell(r_idx, c_idx)
            cell.text = val_str
            cell.fill.solid()
            cell.fill.fore_color.rgb = bg
            p = cell.text_frame.paragraphs[0]
            p.font.size = Pt(12)
            p.font.color.rgb = RGBColor(45, 55, 72)
            p.alignment = PP_ALIGN.CENTER if c_idx == 0 else PP_ALIGN.RIGHT

    # Total Row
    tot_row_idx = len(slab_summary) + 1
    tot_vals = [
        "Total GST",
        f"₹{tot_cgst_sum:,.2f}",
        f"₹{tot_sgst_sum:,.2f}",
        f"₹{tot_gst_sum:,.2f}"
    ]
    for c_idx, val_str in enumerate(tot_vals):
        cell = table.cell(tot_row_idx, c_idx)
        cell.text = val_str
        cell.fill.solid()
        cell.fill.fore_color.rgb = RGBColor(226, 232, 240)
        p = cell.text_frame.paragraphs[0]
        p.font.bold = True
        p.font.size = Pt(13)
        p.font.color.rgb = NAVY
        p.alignment = PP_ALIGN.CENTER if c_idx == 0 else PP_ALIGN.RIGHT

    prs.save(file_path)
    return file_path

