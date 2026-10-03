
from datetime import date
from decimal import Decimal

import pytest

from fakturama_i2c.extract.validate import validate
from fakturama_i2c.models import Address, Debtor, Item, OrderData, Payment, Totals


def make_order(**overrides) -> OrderData:
    """The sample order: 2 lines, 570.00 net / 108.30 VAT / 678.30."""
    order = OrderData(
        external_reference="WEB-2026-0714-A17",
        order_date=date(2026, 7, 14),
        debtor=Debtor(
            company="Northstar Office GmbH", first_name="Marta", last_name="Klein",
            alias="NORTHSTAR-BERLIN", email="marta.klein@example.test",
            phone="+49 30 5550 1420", customer_id="CUST-1007",
            billing=Address("Northstar Office GmbH", "Friedrichstrasse 88", "10117", "Berlin", "Germany"),
            delivery=Address("Northstar Office Warehouse", "Beusselstrasse 44", "10553", "Berlin", "Germany"),
        ),
        payment=Payment(method="Bank Transfer", status="PAID", payment_date=date(2026, 7, 18)),
        items=[
            Item(1, "CHR-ERG-01", "Ergonomic Desk Chair", Decimal(2), "pcs",
                 Decimal("250.00"), Decimal(10), Decimal(19), Decimal("450.00")),
            Item(2, "MAT-DESK-02", "Anti-Fatigue Desk Mat", Decimal(3), "pcs",
                 Decimal("40.00"), Decimal(0), Decimal(19), Decimal("120.00")),
        ],
        totals=Totals(net=Decimal("570.00"), vat=Decimal("108.30"), gross=Decimal("678.30")),
    )
    for key, value in overrides.items():
        setattr(order, key, value)
    return order


def test_valid_order_passes():
    assert validate(make_order()) == []


# --------------------------------------------------------------- arithmetic

def test_line_total_mismatch_is_caught():
    """The mock order_06 scenario: a printed line total that does not match
    qty x price x (1-disc). This is the main defence against OCR digit errors."""
    order = make_order()
    order.items[0].line_net = Decimal("460.00")
    problems = validate(order)
    assert problems and any("CHR-ERG-01" in p for p in problems)


def test_sum_of_lines_must_equal_net_total():
    order = make_order()
    order.totals = Totals(net=Decimal("999.00"), vat=Decimal("108.30"), gross=Decimal("678.30"))
    assert any("net total" in p for p in validate(order))


def test_vat_total_must_match_computed_vat():
    order = make_order()
    order.totals = Totals(net=Decimal("570.00"), vat=Decimal("100.00"), gross=Decimal("670.00"))
    assert any("VAT" in p for p in validate(order))


def test_net_plus_vat_must_equal_gross():
    order = make_order()
    order.totals = Totals(net=Decimal("570.00"), vat=Decimal("108.30"), gross=Decimal("700.00"))
    assert any("gross" in p for p in validate(order))


# ------------------------------------------------------------ required fields

@pytest.mark.parametrize("field_name", ["company", "first_name", "last_name"])
def test_missing_debtor_fields_are_caught(field_name):
    order = make_order()
    setattr(order.debtor, field_name, "")
    assert any(field_name in p for p in validate(order))


def test_missing_external_reference_is_caught():
    order = make_order()
    order.external_reference = ""
    assert any("external reference" in p for p in validate(order))


def test_missing_order_date_is_caught():
    order = make_order()
    order.order_date = None
    assert any("date" in p for p in validate(order))


def test_no_items_is_caught():
    order = make_order()
    order.items = []
    assert any("item" in p.lower() for p in validate(order))


@pytest.mark.parametrize("part", ["street", "zip", "city"])
def test_incomplete_billing_address_is_caught(part):
    order = make_order()
    setattr(order.debtor.billing, part, "")
    assert any("billing" in p for p in validate(order))


def test_missing_numeric_field_is_caught():
    order = make_order()
    order.items[0].quantity = None
    assert any("quantity" in p for p in validate(order))


# ---------------------------------------------------------------- payment

def test_unknown_payment_method_is_rejected():
    """Only the three mapped methods are acceptable; anything
    else would have no valid Fakturama payment code."""
    order = make_order()
    order.payment = Payment(method="Carrier Pigeon", status="PAID", payment_date=date(2026, 7, 18))
    assert any("payment method" in p for p in validate(order))


def test_paid_without_payment_date_is_rejected():
    """Task 5.3: never invent a payment date."""
    order = make_order()
    order.payment = Payment(method="Bank Transfer", status="PAID", payment_date=None)
    assert any("PAID" in p for p in validate(order))


def test_unpaid_without_payment_date_is_fine():
    order = make_order()
    order.payment = Payment(method="Bank Transfer", status="UNPAID", payment_date=None)
    assert validate(order) == []


@pytest.mark.parametrize("method", ["Bank Transfer", "Credit Card", "SEPA Direct Debit"])
def test_all_mapped_payment_methods_are_accepted(method):
    order = make_order()
    order.payment = Payment(method=method, status="UNPAID", payment_date=None)
    assert validate(order) == []
