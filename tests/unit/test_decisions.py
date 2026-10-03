import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from fakturama_i2c.ui import decisions as D  # noqa: E402


def test_debtor_exact_match_selects():
    rows = [{"company": "Northstar Office GmbH", "first_name": "Marta", "name": "Klein", "zip": "10117", "city": "Berlin"}]
    d = D.match_debtor(rows, "Northstar Office GmbH", "Marta", "Klein", "10117", "Berlin")
    assert d.action == "select" and d.row is rows[0]


def test_debtor_no_match_creates():
    d = D.match_debtor([], "Acme", "A", "B", "1", "X")
    assert d.action == "create"


def test_debtor_partial_match_is_not_a_match():
    rows = [{"company": "Northstar Office GmbH", "first_name": "Marta", "name": "Klein", "zip": "99999", "city": "Berlin"}]
    d = D.match_debtor(rows, "Northstar Office GmbH", "Marta", "Klein", "10117", "Berlin")
    assert d.action == "create"


def test_debtor_ambiguous_reviews():
    row = {"company": "Acme", "first_name": "A", "name": "B", "zip": "1", "city": "X"}
    d = D.match_debtor([row, dict(row)], "Acme", "A", "B", "1", "X")
    assert d.action == "review"


def test_payment_method_map():
    assert D.PAYMENT_CODE_MAP["Bank Transfer"] == "Credit transfer"
    assert D.PAYMENT_CODE_MAP["Credit Card"] == "Credit card"
    assert D.PAYMENT_CODE_MAP["SEPA Direct Debit"] == "SEPA direct debit"


def test_payment_method_select_vs_create():
    assert D.match_payment_method([{"name": "Bank Transfer"}], "Bank Transfer").action == "select"
    assert D.match_payment_method([], "Bank Transfer").action == "create"
    assert D.match_payment_method([{"name": "Bank Transfer"}, {"name": "Bank Transfer"}], "Bank Transfer").action == "review"


def test_vat_exact_match():
    rows = [{"name": "VAT 19%", "value": "19", "code": "S"}]
    d = D.match_vat(rows, Decimal("19"))
    assert d.action == "select"


def test_vat_missing_creates():
    assert D.match_vat([], Decimal("7")).action == "create"


def test_vat_name_matches_but_value_conflicts_reviews():
    rows = [{"name": "VAT 19%", "value": "20", "code": "S"}]
    d = D.match_vat(rows, Decimal("19"))
    assert d.action == "review"


def test_vat_wrong_code_reviews():
    rows = [{"name": "VAT 19%", "value": "19", "code": "Z"}]
    assert D.match_vat(rows, Decimal("19")).action == "review"


def test_product_exact_sku():
    rows = [{"item_no": "CHR-ERG-01"}]
    assert D.match_product(rows, "CHR-ERG-01").action == "select"
    assert D.match_product([], "CHR-ERG-01").action == "create"
    assert D.match_product(rows + rows, "CHR-ERG-01").action == "review"


def test_totals_match():
    ok = D.totals_match(Decimal("570.00"), Decimal("108.30"), Decimal("678.30"),
                         Decimal("570.00"), Decimal("108.30"), Decimal("678.30"))
    assert ok.action == "select"
    bad = D.totals_match(Decimal("570.00"), Decimal("108.30"), Decimal("678.30"),
                          Decimal("570.00"), Decimal("108.30"), Decimal("678.31"))
    assert bad.action == "review"
