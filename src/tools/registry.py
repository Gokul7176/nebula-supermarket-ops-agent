from typing import List, Callable, Dict
from src.tools.product_tools import add_product, receive_stock, get_stock
from src.tools.bill_tools import start_bill, add_item_to_bill, remove_item_from_bill, get_draft_bill, list_draft_bills, finalize_bill
from src.tools.khata_tools import get_khata_balance, add_khata_charge, record_khata_payment
from src.tools.report_tools import close_day, generate_invoice_pdf, generate_analysis_deck
from src.tools.pref_tools import set_preference, get_preference

# Master list of model-facing tools
ALL_TOOLS: List[Callable] = [
    add_product,
    receive_stock,
    get_stock,
    start_bill,
    add_item_to_bill,
    remove_item_from_bill,
    get_draft_bill,
    list_draft_bills,
    finalize_bill,
    get_khata_balance,
    add_khata_charge,
    record_khata_payment,
    close_day,
    generate_invoice_pdf,
    generate_analysis_deck,
    set_preference,
    get_preference,
]

# Lookup map for executing tool calls returned by LLM
TOOL_MAP: Dict[str, Callable] = {tool.__name__: tool for tool in ALL_TOOLS}
