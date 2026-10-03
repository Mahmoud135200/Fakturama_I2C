
from types import SimpleNamespace

import pytest

from fakturama_i2c.ui.flow import (
    _debtor_combination_key,
    _debtor_search_terms,
    _search_existing_debtor,
)

COMPANY = "Northstar Office GmbH"
#: All five 2.3 fields in the order 'Select the address' renders them.
KEY = "Marta Klein Northstar Office GmbH 10117 Berlin"


def debtor():
    return SimpleNamespace(
        company=COMPANY, first_name="Marta", last_name="Klein",
        billing=SimpleNamespace(zip="10117", city="Berlin"),
    )


def grid_row(company=COMPANY):
    return {"Company": company, "First Name": "Marta", "Name": "Klein",
            "ZIP": "10117", "City": "Berlin"}


class FakeDialog:
    """Address selector whose filter only surfaces rows for certain terms.

    Refuses a second search, exactly as the real one now does: re-filtering a
    live selector can make it confirm its first row and close by itself.
    """

    def __init__(self, results: dict, editor: "FakeOrderEditor"):
        self.results = results
        self.editor = editor
        self._term = None
        self._searched = False
        self.cancelled = False

    def search(self, text):
        assert not self._searched, "a dialog must only ever be filtered once"
        self._searched = True
        self._term = text
        self.editor.searched.append(text)

    def rows_stable(self, timeout=10.0):
        return self.results.get(self._term, [])

    def cancel(self):
        self.cancelled = True


class FakeOrderEditor:
    """Hands out a fresh address selector per search term."""

    def __init__(self, results: dict):
        self.results = results
        self.searched: list[str] = []
        self.dialogs: list[FakeDialog] = []

    def open_address_selector(self):
        dlg = FakeDialog(self.results, self)
        self.dialogs.append(dlg)
        return dlg


def test_finds_on_the_first_term_without_searching_again():
    """The combination key is one search that means "all five fields at once"."""
    editor = FakeOrderEditor({KEY: [grid_row()]})
    decision, attempts, dialog = _search_existing_debtor(editor, debtor())
    assert decision.action == "select"
    assert editor.searched == [KEY], "should stop as soon as it finds the row"
    assert len(attempts) == 1
    assert dialog is editor.dialogs[-1], "the matching dialog is handed back open"
    assert not dialog.cancelled


def test_each_term_gets_a_fresh_dialog():
    """Re-filtering an open selector is what made it self-confirm and close."""
    editor = FakeOrderEditor({"Klein": [grid_row()]})
    _search_existing_debtor(editor, debtor())
    assert len(editor.dialogs) == len(editor.searched)
    assert all(d.cancelled for d in editor.dialogs[:-1])


def test_falls_back_to_the_cleared_filter_when_the_key_matches_nothing():
    """Fakturama may filter per CELL rather than over the whole row.

    The combination key then matches nothing even though the Debtor exists,
    so the cleared filter -- which lists every Debtor -- has to find it.
    """
    editor = FakeOrderEditor({KEY: [], "": [grid_row()]})
    decision, _, _ = _search_existing_debtor(editor, debtor())
    assert decision.action == "select"
    assert editor.searched == [KEY, ""]


def test_falls_back_to_an_empty_filter_as_a_last_resort():
    editor = FakeOrderEditor({"": [grid_row()]})
    decision, _, _ = _search_existing_debtor(editor, debtor())
    assert decision.action == "select", "clearing the filter must still find it"
    assert "" in editor.searched


def test_creates_only_after_every_term_has_been_tried():
    editor = FakeOrderEditor({})
    decision, attempts, _ = _search_existing_debtor(editor, debtor())
    assert decision.action == "create"
    assert editor.searched == _debtor_search_terms(debtor())
    assert len(attempts) == len(editor.searched)


def test_ambiguity_stops_immediately_and_does_not_keep_searching():
    """Two conflicting rows is a real answer -- never search past it."""
    editor = FakeOrderEditor({KEY: [grid_row(), grid_row()]})
    decision, _, _ = _search_existing_debtor(editor, debtor())
    assert decision.action == "review"
    assert editor.searched == [KEY]


def test_truncated_company_cell_is_found_rather_than_duplicated():
    """The grid ellipses the Company column; that must not mean 'not found'."""
    editor = FakeOrderEditor({KEY: [grid_row(company="Northstar Office ...")]})
    decision, _, _ = _search_existing_debtor(editor, debtor())
    assert decision.action == "select"
    assert decision.truncated is True


def test_search_terms_are_unique_and_end_with_the_cleared_filter():
    terms = _debtor_search_terms(debtor())
    assert len(terms) == len(set(terms))
    assert terms[0] == KEY
    assert terms[-1] == ""
    assert len(terms) == 2, "one keyed search plus the exhaustive one"


def test_combination_key_is_every_2_3_field_in_grid_column_order():
    """The grid renders No. | First Name | Name | Company | ZIP | City, and the
    Search box filters on the rendered row, so the five match fields joined in
    that order are a substring of the right row and of no other."""
    key = _debtor_combination_key(debtor())
    assert key == KEY
    row = "CUST000016 Marta Klein Northstar Office GmbH 10117 Berlin"
    assert key in row
    assert key not in "CUST000017 hvjhghy hgjy uhgwiudg 657 nggu"


def test_combination_key_skips_fields_the_source_did_not_supply():
    d = SimpleNamespace(company="Acme", first_name="", last_name="",
                        billing=SimpleNamespace(zip="", city=""))
    assert _debtor_combination_key(d) == "Acme"
    assert _debtor_search_terms(d) == ["Acme", ""]
