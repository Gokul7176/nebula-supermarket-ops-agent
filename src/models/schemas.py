from typing import Optional, List, Literal
from pydantic import BaseModel, Field

UnitType = Literal['kg', 'g', 'litre', 'ml', 'packet', 'dozen', 'piece']
GstSlabType = Literal[0, 5, 12, 18]
PaymentModeType = Literal['cash', 'upi', 'card', 'khata']

# 1. Product Models
class ProductCreate(BaseModel):
    name: str = Field(..., description="Unique product name e.g. 'Aashirvaad Atta 5kg'")
    brand: str = Field(..., description="Brand name e.g. 'Aashirvaad'")
    unit: UnitType = Field(..., description="Measurement unit (kg/g/litre/ml/packet/dozen/piece)")
    is_loose: bool = Field(False, description="True if loose item (e.g. unbranded loose rice/sugar)")
    hsn_code: str = Field(..., description="HSN Code e.g. '1101'")
    gst_slab: GstSlabType = Field(..., description="GST Slab percentage: 0, 5, 12, or 18")
    cost_price: float = Field(..., ge=0, description="Cost price per unit in INR")
    sell_price: float = Field(..., ge=0, description="Selling price per unit in INR")
    mrp: float = Field(..., ge=0, description="Maximum Retail Price (MRP) per unit in INR")
    quantity: float = Field(..., ge=0, description="Initial stock quantity")
    reorder_level: Optional[float] = Field(None, ge=0, description="Reorder threshold quantity (defaults to 5.0 if omitted)")

class ReceiveStockInput(BaseModel):
    product_id_or_name: str = Field(..., description="Product ID or exact/partial product name")
    quantity: float = Field(..., gt=0, description="Quantity to add to current stock")
    cost_price: Optional[float] = Field(None, ge=0, description="Optional new cost price per unit")
    mrp: Optional[float] = Field(None, ge=0, description="Optional new MRP per unit")
    sell_price: Optional[float] = Field(None, ge=0, description="Optional new selling price per unit")

class GetStockInput(BaseModel):
    query: Optional[str] = Field(None, description="Optional product name search term")
    low_stock_only: bool = Field(False, description="If True, returns only items where quantity <= reorder_level")

# 2. Bill Models
class StartBillInput(BaseModel):
    customer_name: Optional[str] = Field(None, description="Optional customer name for the bill")
    payment_mode: PaymentModeType = Field('cash', description="Provisional payment mode (cash/upi/card/khata)")

class AddItemToBillInput(BaseModel):
    bill_id: int = Field(..., description="Draft bill ID")
    product_id_or_name: str = Field(..., description="Product ID or name to add")
    quantity: float = Field(..., gt=0, description="Quantity to add to the bill")

class RemoveItemFromBillInput(BaseModel):
    bill_id: int = Field(..., description="Draft bill ID")
    item_id_or_product_name: str = Field(..., description="Line item ID or product name to remove")

class GetDraftBillInput(BaseModel):
    bill_id: int = Field(..., description="Draft bill ID to inspect")

class FinalizeBillInput(BaseModel):
    bill_id: int = Field(..., description="Bill ID to finalize")
    payment_mode: Optional[PaymentModeType] = Field(None, description="Final payment mode (cash/upi/card/khata)")
    payment_reference: Optional[str] = Field(None, description="Optional payment reference/transaction ID")
    override_below_cost: bool = Field(False, description="Set to True if store owner explicitly authorized selling below cost")

# 3. Khata Models
class GetKhataBalanceInput(BaseModel):
    customer_name: Optional[str] = Field(None, description="Customer name to query balance for. Omit to list all active khatas.")

class AddKhataChargeInput(BaseModel):
    customer_name: str = Field(..., description="Customer name")
    amount: float = Field(..., gt=0, description="Credit amount to charge to customer khata")
    notes: Optional[str] = Field(None, description="Optional notes or description")

class RecordKhataPaymentInput(BaseModel):
    customer_name: str = Field(..., description="Customer name settling credit")
    amount: float = Field(..., gt=0, description="Payment amount received")
    payment_mode: Literal['cash', 'upi', 'card'] = Field('cash', description="Payment mode used for settlement")
    reference: Optional[str] = Field(None, description="Optional payment reference ID")

# 4. Reporting Models
class CloseDayInput(BaseModel):
    date: Optional[str] = Field(None, description="Date in YYYY-MM-DD format (defaults to today)")

class GenerateInvoicePdfInput(BaseModel):
    bill_id: int = Field(..., description="Finalized bill ID to render PDF invoice for")

class GenerateAnalysisDeckInput(BaseModel):
    start_date: str = Field(..., description="Start date in YYYY-MM-DD format")
    end_date: str = Field(..., description="End date in YYYY-MM-DD format")

# 5. Preference Models
class SetPreferenceInput(BaseModel):
    key: str = Field(..., description="Preference key (e.g. shop_name, shop_gstin, default_payment_mode)")
    value: str = Field(..., description="Preference value string")

class GetPreferenceInput(BaseModel):
    key: Optional[str] = Field(None, description="Preference key to fetch. Omit to list all preferences.")
