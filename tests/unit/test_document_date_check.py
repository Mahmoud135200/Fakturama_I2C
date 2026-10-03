
from __future__ import annotations

from datetime import date

from fakturama_i2c.ui.flow import _date_matches

ORDER_DATE = date(2026, 7, 14)


class TestRenderedFormsMatch:
    """Whatever Fakturama/OCR renders for the right date must be accepted."""

    def test_fakturama_long_form(self):
        assert _date_matches("Jul 14, 2026", ORDER_DATE)

    def test_with_ocr_bleed_from_the_next_column(self):
        # The cell is OCR'd with its neighbour's text attached.
        assert _date_matches("Jul 14, 2026 No", ORDER_DATE)

    def test_iso_form(self):
        assert _date_matches("2026-07-14", ORDER_DATE)

    def test_german_form(self):
        assert _date_matches("14.07.2026", ORDER_DATE)


class TestWrongDatesStillFail:
    """The tolerance is about READABILITY, never about correctness."""

    def test_different_day(self):
        assert not _date_matches("Jul 15, 2026", ORDER_DATE)

    def test_different_month(self):
        assert not _date_matches("Aug 14, 2026", ORDER_DATE)

    def test_different_year(self):
        assert not _date_matches("Jul 14, 2025", ORDER_DATE)

    def test_todays_date_instead_of_the_order_date(self):
        # The failure mode if set_date silently did nothing: the editor keeps
        # Fakturama's proposed date.
        assert not _date_matches("Oct 3, 2026", ORDER_DATE)


class TestUnreadableIsNotAMatch:
    """An empty/garbled cell must never be read as agreement.

    4.5 turns an empty cell into a fallback read, and a failure when both
    sources are empty. That is only safe while `_date_matches` keeps
    refusing blank input -- if it ever returned True for '', the fallback
    would be skipped and an unverified date would pass as verified.
    """

    def test_empty(self):
        assert not _date_matches("", ORDER_DATE)

    def test_whitespace(self):
        assert not _date_matches("   ", ORDER_DATE)

    def test_none(self):
        assert not _date_matches(None, ORDER_DATE)

    def test_unrelated_text(self):
        assert not _date_matches("No", ORDER_DATE)
