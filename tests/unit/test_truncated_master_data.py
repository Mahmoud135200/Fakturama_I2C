
from decimal import Decimal

import pytest

from fakturama_i2c.ui.decisions import (match_payment_method, match_product,
                                         match_vat)


# ----------------------------------------------------- payment methods

@pytest.mark.parametrize("displayed", [
    "SEPA Direct Debit",      # untruncated
    "SEPA Direct Debit .",    # OCR reads the ellipsis as one period
    "SEPA Direct Deb...",
    "SEPA Direct Deb…",
])
def test_existing_payment_method_is_reused_not_recreated(displayed):
    d = match_payment_method([{"name": displayed}], "SEPA Direct Debit")
    assert d.action == "select", "a truncated row must not read as 'absent'"


def test_absent_payment_method_is_still_created():
    assert match_payment_method([{"name": "Bank Transfer"}],
                                 "SEPA Direct Debit").action == "create"


def test_payment_prefix_that_disagrees_is_not_reused():
    assert match_payment_method([{"name": "SEPA Instant Cre..."}],
                                 "SEPA Direct Debit").action == "create"


def test_two_truncated_payment_rows_go_to_review():
    rows = [{"name": "SEPA Direct Deb..."}, {"name": "SEPA Direct Deb..."}]
    assert match_payment_method(rows, "SEPA Direct Debit").action == "review"


# ------------------------------------------------------------ products

@pytest.mark.parametrize("displayed", ["CHR-ERG-01", "CHR-ERG-0.", "CHR-ERG..."])
def test_existing_product_is_reused_not_recreated(displayed):
    assert match_product([{"item_no": displayed}], "CHR-ERG-01").action == "select"


def test_different_sku_is_still_created():
    assert match_product([{"item_no": "MAT-DESK-02"}],
                         "CHR-ERG-01").action == "create"


# ---------------------------------------------------------------- VATs

def test_existing_vat_is_reused_when_its_name_is_truncated():
    rows = [{"name": "VAT 19.", "value": Decimal("19"), "code": "S"}]
    assert match_vat(rows, Decimal("19")).action == "select"


def test_truncated_vat_name_with_wrong_value_still_conflicts():
    """Leniency on the NAME must not excuse a wrong rate."""
    rows = [{"name": "VAT 19.", "value": Decimal("7"), "code": "S"}]
    assert match_vat(rows, Decimal("19")).action == "review"
