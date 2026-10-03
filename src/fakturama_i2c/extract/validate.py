
from __future__ import annotations

from decimal import Decimal

from ..models import OrderData, cents

KNOWN_PAYMENT_METHODS = {"Bank Transfer", "Credit Card", "SEPA Direct Debit"}


class ExtractionError(Exception):
    def __init__(self, problems: list[str]):
        super().__init__("Extraction failed validation:\n  - " + "\n  - ".join(problems))
        self.problems = problems


def validate(order: OrderData) -> list[str]:
    """Return a list of problems; empty list means the extraction is consistent."""
    p: list[str] = []
    if not order.external_reference:
        p.append("missing external reference")
    if not order.items:
        p.append("no item rows")
    d = order.debtor
    for name in ("company", "first_name", "last_name"):
        if not getattr(d, name):
            p.append(f"missing debtor {name}")
    for kind, a in (("billing", d.billing), ("delivery", d.delivery)):
        if not (a.street and a.zip and a.city):
            p.append(f"incomplete {kind} address")

    missing = [f"item {it.position} ({it.sku}) missing {f}" for it in order.items
               for f in ("quantity", "unit_net", "discount_pct", "vat_pct", "line_net") if getattr(it, f) is None]
    missing += [f"missing {f} total" for f in ("net", "vat", "gross") if getattr(order.totals, f) is None]
    if order.order_date is None:
        missing.append("missing/unparseable order date")
    if missing:
        return p + missing     

    for it in order.items:
        if it.computed_line_net != it.line_net:
            p.append(f"item {it.position} ({it.sku}): {it.quantity} x {it.unit_net} - {it.discount_pct}% "
                     f"= {it.computed_line_net}, source says {it.line_net}")

    net = sum((i.line_net for i in order.items), Decimal(0))
    if net != order.totals.net:
        p.append(f"sum of lines {net} != net total {order.totals.net}")
    vat = cents(sum((i.line_net * i.vat_pct / 100 for i in order.items), Decimal(0)))
    if vat != order.totals.vat:
        p.append(f"computed VAT {vat} != VAT total {order.totals.vat}")
    if order.totals.net + order.totals.vat != order.totals.gross:
        p.append(f"net {order.totals.net} + VAT {order.totals.vat} != gross {order.totals.gross}")

    if order.payment.method not in KNOWN_PAYMENT_METHODS:
        p.append(f"unknown payment method {order.payment.method!r}")
    if order.payment.is_paid and order.payment.payment_date is None:
        p.append("status PAID but no payment date")
    return p


def require_valid(order: OrderData) -> OrderData:
    problems = validate(order)
    if problems:
        raise ExtractionError(problems)
    return order
