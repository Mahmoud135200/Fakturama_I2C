
import pytest

from fakturama_i2c.ui.decisions import match_debtor

COMPANY = "Northstar Office GmbH"
ARGS = (COMPANY, "Marta", "Klein", "10117", "Berlin")


def row(company=COMPANY, first="Marta", name="Klein", zip_="10117", city="Berlin"):
    return {"company": company, "first_name": first, "name": name,
            "zip": zip_, "city": city}


def test_untruncated_exact_match_still_selects():
    d = match_debtor([row()], *ARGS)
    assert d.action == "select"
    assert d.truncated is False


@pytest.mark.parametrize("displayed", [
    "Northstar Office ...",
    "Northstar Office …",
    "Northstar Offi...",
    "N...",
    # LIVE-OBSERVED (tools/diagnose_row_click.py): Windows OCR read the
    # grid's ellipsis back as a SINGLE period. An earlier version of this
    # rule only accepted '...'/'…' and so still failed to match this exact
    # string -- the one the real app actually produces.
    "Northstar Office .",
    "Northstar Office ..",
])
def test_ellipsed_company_matches_by_prefix(displayed):
    """The observed failure: the row is right there but reads truncated."""
    d = match_debtor([row(company=displayed)], *ARGS)
    assert d.action == "select"
    assert d.truncated is True, "a prefix-based match must be flagged for the report"


def test_ellipsed_prefix_that_disagrees_does_not_match():
    d = match_debtor([row(company="Southstar Offi...")], *ARGS)
    assert d.action == "create"


def test_other_fields_must_still_match_exactly():
    """Truncation leniency must not leak into the fields that read fine."""
    assert match_debtor([row(company="Northstar Office ...", city="Hamburg")],
                        *ARGS).action == "create"
    assert match_debtor([row(company="Northstar Office ...", zip_="10553")],
                        *ARGS).action == "create"
    assert match_debtor([row(company="Northstar Office ...", first="Marte")],
                        *ARGS).action == "create"


def test_two_rows_sharing_the_prefix_go_to_review():
    """'Northstar Office ...' could be GmbH or AG -- never guess between them."""
    rows = [row(company="Northstar Office ..."), row(company="Northstar Office ...")]
    d = match_debtor(rows, *ARGS)
    assert d.action == "review"


def test_a_bare_ellipsis_cell_does_not_match_everything():
    """An unreadable cell must not become a wildcard."""
    assert match_debtor([row(company="...")], *ARGS).action == "create"


def test_no_rows_still_means_create():
    assert match_debtor([], *ARGS).action == "create"
