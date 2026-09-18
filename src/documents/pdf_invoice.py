import os
import tempfile
import logging
from typing import Dict, Any, Optional, Tuple
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

logger = logging.getLogger(__name__)

_REGISTERED_FONTS: Optional[Tuple[str, str]] = None

def get_invoice_font_names() -> Tuple[str, str]:
    """
    Registers a TrueType font in ReportLab that includes full Unicode support for the Indian Rupee symbol (₹).
    Returns (normal_font_name, bold_font_name).
    """
    global _REGISTERED_FONTS
    if _REGISTERED_FONTS is not None:
        return _REGISTERED_FONTS

    # Candidate font pairs: (Prefix, RegularTTFPath, BoldTTFPath)
    candidates = [
        ("InvoiceDejaVu", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ("InvoiceDejaVuAlt", "/usr/share/fonts/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"),
        ("InvoiceFreeFont", "/usr/share/fonts/truetype/freefont/FreeSans.ttf", "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"),
        ("InvoiceLiberation", "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
        ("InvoiceSegoeUI", "C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/segoeuib.ttf"),
        ("InvoiceArial", "C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
        ("InvoiceCalibri", "C:/Windows/Fonts/calibri.ttf", "C:/Windows/Fonts/calibrib.ttf"),
    ]

    for prefix, reg_path, bold_path in candidates:
        if os.path.exists(reg_path) and os.path.exists(bold_path):
            norm_name = f"{prefix}-Regular"
            bold_name = f"{prefix}-Bold"
            try:
                pdfmetrics.registerFont(TTFont(norm_name, reg_path))
                pdfmetrics.registerFont(TTFont(bold_name, bold_path))
                _REGISTERED_FONTS = (norm_name, bold_name)
                logger.info(f"Registered ReportLab invoice TrueType fonts: {norm_name}, {bold_name}")
                return _REGISTERED_FONTS
            except Exception as ex:
                logger.warning(f"Failed registering font pair ({reg_path}, {bold_path}): {ex}")

    _REGISTERED_FONTS = ("Helvetica", "Helvetica-Bold")
    return _REGISTERED_FONTS

def generate_pdf_invoice_file(bill_data: Dict[str, Any], preferences: Dict[str, str]) -> str:
    """
    Renders a GST-compliant PDF Tax Invoice for a finalized bill using ReportLab.
    Pulls shop info from preferences and bill metrics directly from database.
    """
    norm_font, bold_font = get_invoice_font_names()

    bill = bill_data["bill"]
    items = bill_data["items"]

    shop_name = preferences.get("shop_name", "Kirana Supermarket Store")
    shop_gstin = preferences.get("shop_gstin", "33AAAAA0000A1Z5")
    shop_address = preferences.get("shop_address", "Main Market, Main Road, City")
    shop_phone = preferences.get("shop_phone", "+91 98765 43210")

    # Output file setup
    temp_dir = tempfile.gettempdir()
    file_path = os.path.join(temp_dir, f"invoice_bill_{bill['id']}.pdf")

    doc = SimpleDocTemplate(
        file_path,
        pagesize=letter,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'InvoiceTitle',
        parent=styles['Heading1'],
        fontName=bold_font,
        fontSize=18,
        leading=22,
        textColor=colors.HexColor("#1A365D"),
        alignment=0
    )
    subtitle_style = ParagraphStyle(
        'InvoiceSubtitle',
        parent=styles['Normal'],
        fontName=norm_font,
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#4A5568")
    )
    bold_body = ParagraphStyle(
        'InvoiceBold',
        parent=styles['Normal'],
        fontName=bold_font,
        fontSize=9,
        leading=11,
        textColor=colors.HexColor("#2D3748")
    )
    normal_body = ParagraphStyle(
        'InvoiceBody',
        parent=styles['Normal'],
        fontName=norm_font,
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#2D3748")
    )

    elements = []

    # 1. Header Section
    header_data = [
        [
            Paragraph(f"<b>{shop_name}</b><br/>{shop_address}<br/>GSTIN: {shop_gstin}<br/>Phone: {shop_phone}", subtitle_style),
            Paragraph(f"<b>TAX INVOICE</b><br/>Invoice #: <b>BILL-{bill['id']}</b><br/>Date: {bill.get('finalized_at', bill['created_at'])}<br/>Mode: <b>{str(bill.get('payment_mode')).upper()}</b>", subtitle_style)
        ]
    ]
    header_table = Table(header_data, colWidths=[300, 240])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 10))

    # 2. Customer Section
    cust_name = bill.get("customer_name") or "Walk-in Customer"
    cust_info = f"<b>Billed To:</b> {cust_name}"
    if bill.get("payment_reference"):
        cust_info += f" &nbsp;|&nbsp; <b>Ref:</b> {bill['payment_reference']}"
    elements.append(Paragraph(cust_info, subtitle_style))
    elements.append(Spacer(1, 12))

    # 3. Line Items Table
    table_headers = ["#", "Item Description", "HSN", "Qty", "Unit Price", "GST %", "CGST", "SGST", "Line Total"]
    table_rows = [[Paragraph(f"<b>{h}</b>", bold_body) for h in table_headers]]

    for idx, item in enumerate(items, 1):
        table_rows.append([
            Paragraph(str(idx), normal_body),
            Paragraph(f"{item['product_name']} ({item['brand']})", normal_body),
            Paragraph(str(item['hsn_code']), normal_body),
            Paragraph(f"{item['quantity']} {item['unit']}", normal_body),
            Paragraph(f"₹{item['unit_price_at_sale']:.2f}", normal_body),
            Paragraph(f"{item['gst_slab_at_sale']:.0f}%", normal_body),
            Paragraph(f"₹{item['cgst_amount']:.2f}", normal_body),
            Paragraph(f"₹{item['sgst_amount']:.2f}", normal_body),
            Paragraph(f"₹{item['line_total']:.2f}", normal_body),
        ])

    items_table = Table(table_rows, colWidths=[20, 150, 45, 45, 55, 40, 50, 50, 65])
    items_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#EDF2F7")),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor("#2D3748")),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('ALIGN', (3, 0), (-1, -1), 'RIGHT'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E0")),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    elements.append(items_table)
    elements.append(Spacer(1, 14))

    # 4. Totals Breakdown Table
    summary_data = [
        [Paragraph("Taxable Amount:", normal_body), Paragraph(f"₹{bill_data['subtotal']:.2f}", normal_body)],
        [Paragraph("Total CGST:", normal_body), Paragraph(f"₹{bill_data['total_cgst']:.2f}", normal_body)],
        [Paragraph("Total SGST:", normal_body), Paragraph(f"₹{bill_data['total_sgst']:.2f}", normal_body)],
        [Paragraph("<b>Grand Total:</b>", bold_body), Paragraph(f"<b>₹{bill_data['grand_total']:.2f}</b>", title_style)]
    ]
    summary_table = Table(summary_data, colWidths=[150, 100])
    summary_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))

    wrapper_table = Table([[Paragraph("<i>Thank you for your business!</i>", subtitle_style), summary_table]], colWidths=[290, 250])
    wrapper_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
        ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
    ]))
    elements.append(wrapper_table)

    doc.build(elements)
    return file_path
