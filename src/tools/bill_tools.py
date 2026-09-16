from typing import Dict, Any, Optional
from src.db.connection import get_db_connection, immediate_transaction
from src.services.billing_service import (
    start_bill_service, add_item_to_bill_service, remove_item_from_bill_service,
    get_bill_details_service, finalize_bill_service
)

def start_bill(customer_name: Optional[str] = None, payment_mode: str = 'cash') -> Dict[str, Any]:
    """
    Initializes a new multi-turn draft bill. Stock is NOT modified until finalization.
    
    Args:
        customer_name: Optional customer name for the bill
        payment_mode: Provisional payment mode (cash/upi/card/khata)
    """
    with get_db_connection() as conn:
        with immediate_transaction(conn):
            res = start_bill_service(conn, customer_name, payment_mode)
    return {"status": "success", "bill_details": res}

def add_item_to_bill(bill_id: int, product_id_or_name: str, quantity: float) -> Dict[str, Any]:
    """
    Adds a product item and quantity to an active draft bill.
    
    Args:
        bill_id: Active draft bill ID
        product_id_or_name: Product ID or product name
        quantity: Quantity to add
    """
    with get_db_connection() as conn:
        with immediate_transaction(conn):
            res = add_item_to_bill_service(conn, bill_id, product_id_or_name, quantity)
    return {"status": "success", "bill_details": res}

def remove_item_from_bill(bill_id: int, item_id_or_product_name: str) -> Dict[str, Any]:
    """
    Removes a line item from an active draft bill.
    
    Args:
        bill_id: Active draft bill ID
        item_id_or_product_name: Line item ID or product name to remove
    """
    with get_db_connection() as conn:
        with immediate_transaction(conn):
            res = remove_item_from_bill_service(conn, bill_id, item_id_or_product_name)
    return {"status": "success", "bill_details": res}

def get_draft_bill(bill_id: int) -> Dict[str, Any]:
    """
    Inspects an active draft bill's line items, subtotal, and provisional GST breakdown.
    
    Args:
        bill_id: Active bill ID
    """
    with get_db_connection() as conn:
        res = get_bill_details_service(conn, bill_id)
    return {"status": "success", "bill_details": res}

def finalize_bill(bill_id: int, payment_mode: Optional[str] = None,
                  payment_reference: Optional[str] = None,
                  override_below_cost: bool = False) -> Dict[str, Any]:
    """
    Finalizes a draft bill:
    1. Verifies stock availability (refuses if oversold).
    2. Calculates per-item CGST+SGST split rounded to nearest paisa per item.
    3. Decrements stock atomically inside write lock.
    4. If payment_mode is 'khata', records khata_transactions charge & updates khata.balance in SAME transaction.
    5. IDEMPOTENT: If already finalized, returns existing finalized result without duplicate mutations.
    
    Args:
        bill_id: Bill ID to finalize
        payment_mode: Final payment mode (cash/upi/card/khata)
        payment_reference: Optional payment transaction ID
        override_below_cost: Set to True if store owner explicitly authorized selling below cost
    """
    with get_db_connection() as conn:
        with immediate_transaction(conn):
            res = finalize_bill_service(conn, bill_id, payment_mode, payment_reference, override_below_cost)
    return {"status": "success", "finalized_bill": res}
