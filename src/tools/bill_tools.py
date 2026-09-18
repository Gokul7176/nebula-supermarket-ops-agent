import logging
from typing import Dict, Any, Optional, List
from src.db.connection import get_db_connection, immediate_transaction
from src.agent.context import current_chat_id_var
from src.services.billing_service import (
    start_bill_service, add_item_to_bill_service, remove_item_from_bill_service,
    get_bill_details_service, finalize_bill_service, list_draft_bills_service,
    BelowCostOverrideRequiredError
)

logger = logging.getLogger(__name__)

def start_bill(customer_name: Optional[str] = None, payment_mode: str = 'cash', chat_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Initializes a new multi-turn draft bill and sets it as the active draft for the chat session.
    Stock is NOT modified until finalization.
    
    Args:
        customer_name: Optional customer name for the bill
        payment_mode: Provisional payment mode (cash/upi/card/khata)
        chat_id: Optional chat session ID (auto-resolved from session if omitted)
    """
    c_id = chat_id or current_chat_id_var.get()
    logger.info(f"[TOOL start_bill] customer_name={customer_name}, payment_mode={payment_mode}, chat_id='{c_id}'")
    with get_db_connection() as conn:
        with immediate_transaction(conn):
            res = start_bill_service(conn, customer_name, payment_mode, chat_id=c_id)
    return {"status": "success", "bill_details": res}

def add_item_to_bill(product_id_or_name: str, quantity: float, bill_id: Optional[int] = None, chat_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Adds a product item and quantity to a draft bill.
    If bill_id is omitted, automatically targets the active draft bill for the current chat session.
    DO NOT call start_bill before calling add_item_to_bill if a draft bill is already active. Call add_item_to_bill directly.
    
    Args:
        product_id_or_name: Product ID or product name
        quantity: Quantity to add
        bill_id: Optional active draft bill ID (auto-resolved from chat session if omitted)
        chat_id: Optional chat session ID
    """
    c_id = chat_id or current_chat_id_var.get()
    logger.info(f"[TOOL add_item_to_bill] product='{product_id_or_name}', quantity={quantity}, tool_arg_bill_id={bill_id}, chat_id='{c_id}'")
    with get_db_connection() as conn:
        with immediate_transaction(conn):
            res = add_item_to_bill_service(conn, bill_id, product_id_or_name, quantity, chat_id=c_id)
    return {"status": "success", "bill_details": res}

def remove_item_from_bill(item_id_or_product_name: str, bill_id: Optional[int] = None, chat_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Removes a line item from a draft bill.
    If bill_id is omitted, targets the active draft bill for the current chat session.
    
    Args:
        item_id_or_product_name: Line item ID or product name to remove
        bill_id: Optional active draft bill ID (auto-resolved from chat session if omitted)
        chat_id: Optional chat session ID
    """
    c_id = chat_id or current_chat_id_var.get()
    logger.info(f"[TOOL remove_item_from_bill] item='{item_id_or_product_name}', tool_arg_bill_id={bill_id}, chat_id='{c_id}'")
    with get_db_connection() as conn:
        with immediate_transaction(conn):
            res = remove_item_from_bill_service(conn, bill_id, item_id_or_product_name, chat_id=c_id)
    return {"status": "success", "bill_details": res}

def get_draft_bill(bill_id: Optional[int] = None, chat_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Inspects a draft bill's line items, subtotal, and provisional GST breakdown.
    If bill_id is omitted, targets the active draft bill for the current chat session.
    
    Args:
        bill_id: Optional active bill ID (auto-resolved from chat session if omitted)
        chat_id: Optional chat session ID
    """
    c_id = chat_id or current_chat_id_var.get()
    logger.info(f"[TOOL get_draft_bill] tool_arg_bill_id={bill_id}, chat_id='{c_id}'")
    with get_db_connection() as conn:
        res = get_bill_details_service(conn, bill_id, chat_id=c_id)
    return {"status": "success", "bill_details": res}

def list_draft_bills(chat_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Lists open draft bills for the current chat session.
    Use this tool when multiple open drafts exist to inspect them before asking the owner for clarification.
    
    Args:
        chat_id: Optional chat session ID (auto-resolved from session if omitted)
    """
    c_id = chat_id or current_chat_id_var.get()
    logger.info(f"[TOOL list_draft_bills] chat_id='{c_id}'")
    with get_db_connection() as conn:
        res = list_draft_bills_service(conn, chat_id=c_id)
    return {"status": "success", "draft_bills": res}

def finalize_bill(bill_id: Optional[int] = None, payment_mode: Optional[str] = None,
                  payment_reference: Optional[str] = None,
                  override_below_cost: bool = False,
                  chat_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Finalizes a draft bill:
    1. Verifies stock availability (refuses if oversold).
    2. Calculates per-item CGST+SGST split rounded to nearest paisa per item.
    3. Decrements stock atomically inside write lock.
    4. If payment_mode is 'khata', records khata_transactions charge & updates khata.balance in SAME transaction.
    5. Clears active draft association upon successful finalization.
    6. IDEMPOTENT: If already finalized, returns existing finalized result without duplicate mutations.
    
    Args:
        bill_id: Optional bill ID to finalize (auto-resolved from chat session if omitted)
        payment_mode: Final payment mode (cash/upi/card/khata)
        payment_reference: Optional payment transaction ID
        override_below_cost: Defaults to False. MUST ONLY be set to True if the store owner explicitly authorized selling below cost in their CURRENT request message.
        chat_id: Optional chat session ID
    """
    c_id = chat_id or current_chat_id_var.get()
    logger.info(
        f"[TOOL finalize_bill] tool_arg_bill_id={bill_id}, chat_id='{c_id}', "
        f"payment_mode={payment_mode}, override_below_cost={override_below_cost}"
    )
    with get_db_connection() as conn:
        try:
            with immediate_transaction(conn):
                res = finalize_bill_service(conn, bill_id, payment_mode, payment_reference, override_below_cost, chat_id=c_id)
            return {"status": "success", "finalized_bill": res}
        except BelowCostOverrideRequiredError as ex:
            return {
                "status": "error",
                "error_code": "BELOW_COST_REQUIRES_EXPLICIT_OVERRIDE",
                "message": str(ex.message),
                "bill_id": ex.bill_id,
                "item_name": ex.product_name,
                "sell_price": ex.sell_price,
                "cost_price": ex.cost_price
            }
