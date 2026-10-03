
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

CENT = Decimal("0.01")


def cents(v: Decimal) -> Decimal:
    
    return v.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass
class Address:
    name: str                      
    street: str
    zip: str
    city: str
    country: str


@dataclass
class Debtor:
    company: str
    first_name: str
    last_name: str
    alias: str
    email: str
    phone: str
    customer_id: Optional[str]     
    billing: Address
    delivery: Address

    @property
    def same_billing_and_delivery(self) -> bool:
        b, d = self.billing, self.delivery
        return (b.street, b.zip, b.city, b.country) == (d.street, d.zip, d.city, d.country) and b.name == d.name


@dataclass
class Payment:
    method: str                  
    status: str                   
    payment_date: Optional[date]

    @property
    def is_paid(self) -> bool:
        return self.status.upper() == "PAID"


@dataclass
class Item:
    position: int
    sku: str
    description: str
    quantity: Decimal
    unit: str
    unit_net: Decimal
    discount_pct: Decimal
    vat_pct: Decimal
    line_net: Decimal            
    @property
    def computed_line_net(self) -> Decimal:
        return cents(self.quantity * self.unit_net * (1 - self.discount_pct / 100))

    @property
    def product_gross_price(self) -> Decimal:
        
        return cents(self.unit_net * (1 + self.vat_pct / 100))


@dataclass
class Totals:
    net: Decimal
    vat: Decimal
    gross: Decimal
    currency: str = "EUR"


@dataclass
class OrderData:
    external_reference: str
    order_date: date
    debtor: Debtor
    payment: Payment
    items: list[Item]
    totals: Totals
    notes: list[str] = field(default_factory=list)

    def to_json_dict(self) -> dict:
        def conv(o):
            if isinstance(o, dict):
                return {k: conv(v) for k, v in o.items()}
            if isinstance(o, list):
                return [conv(v) for v in o]
            if isinstance(o, Decimal):
                return str(o)
            if isinstance(o, date):
                return o.isoformat()
            return o
        return conv(asdict(self))
