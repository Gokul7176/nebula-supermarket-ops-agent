from typing import Dict, Any, Optional
from src.db.connection import get_db_connection, immediate_transaction
from src.services.khata_service import (
    get_khata_balance_service, add_khata_charge_service, record_khata_payment_service
)

def get_khata_balance(customer_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Queries customer khata credit balance and recent transactions.
    
    Args:
        customer_name: Optional customer name. Omit to list all active khatas.
    """
    with get_db_connection() as conn:
        res = get_khata_balance_service(conn, customer_name)
    return {"status": "success", "khatas": res}

def add_khata_charge(customer_name: str, amount: float, notes: Optional[str] = None) -> Dict[str, Any]:
    """
    Adds a manual credit charge to a customer's khata ledger.
    
    Args:
        customer_name: Customer name
        amount: Credit charge amount in INR
        notes: Optional description or note
    """
    with get_db_connection() as conn:
        with immediate_transaction(conn):
            res = add_khata_charge_service(conn, customer_name, amount, notes)
    return {"status": "success", "khata": res}

def record_khata_payment(customer_name: str, amount: float, payment_mode: str = 'cash',
                         reference: Optional[str] = None) -> Dict[str, Any]:
    """
    Records a settlement payment for customer credit.
    Refuses payment if customer has no khata record or payment exceeds balance owed.
    
    Args:
        customer_name: Customer name
        amount: Payment amount received
        payment_mode: Settlement payment mode (cash/upi/card)
        reference: Optional payment transaction ID
    """
    with get_db_connection() as conn:
        with immediate_transaction(conn):
            res = record_khata_payment_service(conn, customer_name, amount, payment_mode, reference)
    return {"status": "success", "khata": res}
