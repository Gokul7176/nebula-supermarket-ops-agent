from typing import Dict, Any, Optional
from src.db.connection import get_db_connection, immediate_transaction
from src.services.stock_service import add_product_service, receive_stock_service, get_stock_service

def add_product(name: str, brand: str, unit: str, is_loose: bool, hsn_code: str, gst_slab: float,
                cost_price: float, sell_price: float, mrp: float, quantity: float,
                reorder_level: float = 5.0) -> Dict[str, Any]:
    """
    Creates a new product SKU in the database with prices, HSN code, and GST slab.
    
    Args:
        name: Unique product name (e.g. 'Aashirvaad Atta 5kg')
        brand: Brand name (e.g. 'Aashirvaad')
        unit: Measurement unit (kg/g/litre/ml/packet/dozen/piece)
        is_loose: True if unbranded/loose staple item
        hsn_code: HSN Code string
        gst_slab: GST Slab percentage (0, 5, 12, or 18)
        cost_price: Cost price per unit in INR
        sell_price: Selling price per unit in INR
        mrp: MRP per unit in INR
        quantity: Initial stock quantity
        reorder_level: Reorder alert quantity threshold
    """
    data = {
        "name": name, "brand": brand, "unit": unit, "is_loose": is_loose,
        "hsn_code": hsn_code, "gst_slab": gst_slab, "cost_price": cost_price,
        "sell_price": sell_price, "mrp": mrp, "quantity": quantity, "reorder_level": reorder_level
    }
    with get_db_connection() as conn:
        with immediate_transaction(conn):
            res = add_product_service(conn, data)
    return {"status": "success", "product": res}

def receive_stock(product_id_or_name: str, quantity: float, cost_price: Optional[float] = None,
                  mrp: Optional[float] = None, sell_price: Optional[float] = None) -> Dict[str, Any]:
    """
    Increments quantity for an existing product SKU.
    Optionally updates cost price, MRP, or sell price. Preserves existing prices if omitted.
    
    Args:
        product_id_or_name: Product ID or product name
        quantity: Quantity to add to stock
        cost_price: Optional updated cost price
        mrp: Optional updated MRP
        sell_price: Optional updated selling price
    """
    with get_db_connection() as conn:
        with immediate_transaction(conn):
            res = receive_stock_service(conn, product_id_or_name, quantity, cost_price, mrp, sell_price)
    return {"status": "success", "updated_product": res}

def get_stock(query: Optional[str] = None, low_stock_only: bool = False) -> Dict[str, Any]:
    """
    Queries current stock quantities for products. Supports low-stock reorder filter.
    
    Args:
        query: Optional search term for product name/brand
        low_stock_only: If True, returns only items where stock quantity <= reorder_level
    """
    with get_db_connection() as conn:
        res = get_stock_service(conn, query, low_stock_only)
    return {"status": "success", "count": len(res), "products": res}
