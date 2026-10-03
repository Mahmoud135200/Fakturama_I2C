
from __future__ import annotations

import pytest

from fakturama_i2c.ui import pages


@pytest.fixture
def editor(monkeypatch):
    """An OrderEditor with no live app behind it.

    `_is_dirty` only reaches the UI through the module-level `_tab_exists`,
    so faking the set of open tabs is enough to drive every branch.
    """
    ed = object.__new__(pages.OrderEditor)
    ed.app = object()
    ed.pane = object()
    ed.tab_title = pages.OrderEditor.NEW_EDITOR_TITLE

    open_tabs: set[str] = set()
    monkeypatch.setattr(pages, "_tab_exists", lambda app, name: name in open_tabs)
    ed._open_tabs = open_tabs          # test handle
    return ed


def test_fresh_editor_is_dirty_as_new_order(editor):
    editor._open_tabs.add("*New Order")
    assert editor._is_dirty()


def test_saved_editor_is_clean(editor):
    editor._open_tabs.add("PO000041")
    editor.tab_title = "PO000041"
    assert not editor._is_dirty()


def test_resaved_editor_is_dirty_under_its_number(editor):
    """The regression: a renamed tab dirties as '*PO000041'.

    The old check looked only for '*New Order', so this read as clean and a
    save that never happened would have been reported as successful.
    """
    editor.tab_title = "PO000041"
    editor._open_tabs.add("*PO000041")
    assert editor._is_dirty()


def test_invoice_editor_checks_its_own_title(editor):
    """InvoiceEditor inherits save(); it must not look for '*New Order'."""
    inv = object.__new__(pages.InvoiceEditor)
    inv.app, inv.pane = object(), object()
    inv.tab_title = inv.NEW_EDITOR_TITLE
    assert inv.NEW_EDITOR_TITLE == "New Invoice"

    editor._open_tabs.add("*New Invoice")
    assert inv._is_dirty()
    # ...and the Order editor must not claim the Invoice's dirty marker.
    assert not editor._is_dirty()


def test_unrelated_dirty_editor_is_not_claimed(editor):
    """Another editor being dirty says nothing about this one."""
    editor._open_tabs.update({"*New Invoice", "*Ergonomic Desk Chair"})
    assert not editor._is_dirty()
