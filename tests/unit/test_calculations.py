
from decimal import Decimal

import pytest

from fakturama_i2c.models import Item, cents


def item(**kw) -> Item:
    base = dict(position=1, sku="X", description="d", quantity=Decimal(1), unit="pcs",
                unit_net=Decimal("100.00"), discount_pct=Decimal(0), vat_pct=Decimal(19),
                line_net=Decimal("100.00"))
    base.update(kw)
    return Item(**base)


# ------------------------------------------------------- product master price

def test_product_gross_price_adds_vat():
    it = item(unit_net=Decimal("250.00"), vat_pct=Decimal(19))
    assert it.product_gross_price == Decimal("297.50")


def test_product_gross_price_ignores_line_discount():
    """Task 3.9 says explicitly: do NOT apply the line discount here."""
    plain = item(unit_net=Decimal("250.00"), vat_pct=Decimal(19), discount_pct=Decimal(0))
    discounted = item(unit_net=Decimal("250.00"), vat_pct=Decimal(19), discount_pct=Decimal(10))
    assert plain.product_gross_price == discounted.product_gross_price == Decimal("297.50")


@pytest.mark.parametrize("net,vat,expected", [
    ("40.00", 19, "47.60"),
    ("100.00", 7, "107.00"),
    ("19.99", 19, "23.79"),     # 23.7881 -> half-up
    ("0.01", 19, "0.01"),       # 0.0119 -> rounds down, must not vanish
])
def test_product_gross_price_rounding(net, vat, expected):
    it = item(unit_net=Decimal(net), vat_pct=Decimal(vat))
    assert it.product_gross_price == Decimal(expected)


# ------------------------------------------------------------------ line price

def test_line_price_with_discount():
    it = item(quantity=Decimal(2), unit_net=Decimal("250.00"), discount_pct=Decimal(10))
    assert it.computed_line_net == Decimal("450.00")


def test_line_price_without_discount():
    it = item(quantity=Decimal(3), unit_net=Decimal("40.00"), discount_pct=Decimal(0))
    assert it.computed_line_net == Decimal("120.00")


@pytest.mark.parametrize("qty,net,disc,expected", [
    (1, "100.00", 0, "100.00"),
    (1, "100.00", 100, "0.00"),      # fully discounted is legal, not an error
    (5, "19.99", 15, "84.96"),       # 84.9575 -> half-up
    (12, "4.15", 5, "47.31"),        # 47.31
])
def test_line_price_cases(qty, net, disc, expected):
    it = item(quantity=Decimal(qty), unit_net=Decimal(net), discount_pct=Decimal(disc))
    assert it.computed_line_net == Decimal(expected)


# -------------------------------------------------------------------- rounding

def test_rounding_is_half_up_not_bankers():
    """Python's default is banker's rounding, which would make this 70.96.
    Invoices round half away from zero."""
    assert cents(Decimal("70.965")) == Decimal("70.97")
    assert cents(Decimal("0.005")) == Decimal("0.01")


def test_no_binary_float_drift():
    """0.1+0.2 != 0.3 in binary float; Decimal must not inherit that."""
    it = item(quantity=Decimal(3), unit_net=Decimal("0.10"), discount_pct=Decimal(0))
    assert it.computed_line_net == Decimal("0.30")
