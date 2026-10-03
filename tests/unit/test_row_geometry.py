
import pytest

from fakturama_i2c.ui.decisions import match_debtor, match_product
from fakturama_i2c.ui.flow import _row_to_debtor_match, _row_to_product_match

GEOMETRY = {"_cy": 38.0, "_top": 31.7, "_bottom": 44.3}


def debtor_grid_row(**over):
    row = {"No.": "1 CUST000016", "First Name": "Marta", "Name": "Klein",
           "Company": "Northstar Office GmbH", "ZIP": "10117", "City": "Berlin"}
    row.update(GEOMETRY)
    row.update(over)
    return row


def product_grid_row(**over):
    row = {"Item No.": "CHR-ERG-01", "Name": "Ergonomic Desk Chair"}
    row.update(GEOMETRY)
    row.update(over)
    return row


@pytest.mark.parametrize("key,value", GEOMETRY.items())
def test_debtor_mapping_keeps_geometry(key, value):
    assert _row_to_debtor_match(debtor_grid_row())[key] == value


@pytest.mark.parametrize("key,value", GEOMETRY.items())
def test_product_mapping_keeps_geometry(key, value):
    assert _row_to_product_match(product_grid_row())[key] == value


def test_matched_debtor_row_is_still_clickable():
    """The exact end-to-end path that raised KeyError '_cy'."""
    rows = [_row_to_debtor_match(debtor_grid_row())]
    decision = match_debtor(rows, "Northstar Office GmbH", "Marta", "Klein",
                            "10117", "Berlin")
    assert decision.action == "select"
    assert "_cy" in decision.row, "the row handed to click_row lost its geometry"


def test_matched_product_row_is_still_clickable():
    rows = [_row_to_product_match(product_grid_row())]
    decision = match_product(rows, "CHR-ERG-01")
    assert decision.action == "select"
    assert "_cy" in decision.row


def test_mapping_survives_a_truncated_company():
    """Truncated cells are the case that finally reached the click path."""
    rows = [_row_to_debtor_match(debtor_grid_row(Company="Northstar Office ."))]
    decision = match_debtor(rows, "Northstar Office GmbH", "Marta", "Klein",
                            "10117", "Berlin")
    assert decision.action == "select"
    assert decision.truncated is True
    assert "_cy" in decision.row


def test_mapping_tolerates_a_row_without_geometry():
    """Fake rows in tests have no geometry; mapping must not blow up."""
    mapped = _row_to_debtor_match({"Company": "X", "First Name": "A",
                                   "Name": "B", "ZIP": "1", "City": "C"})
    assert mapped["company"] == "X"
    assert "_cy" not in mapped
