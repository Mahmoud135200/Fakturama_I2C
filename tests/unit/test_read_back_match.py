
import pytest

from fakturama_i2c.ui.controls import exact_match, numeric_match


@pytest.mark.parametrize("written,read", [
    ("0", "0%"),              # the observed Discount failure
    ("0", "0 %"),
    ("19", "19.00 %"),        # VAT value
    ("250.00", "250.00"),
    ("250", "250.00"),        # price reformatted with decimals
    ("250.00", "250,00"),     # comma decimal separator
    ("1234.50", "1,234.50"),  # thousands separator
    ("250.00", "250.00 EUR"), # currency suffix
    ("250.00", "€ 250.00"),
    ("0.00", "0"),
])
def test_formatting_differences_are_accepted(written, read):
    assert numeric_match(written, read)


@pytest.mark.parametrize("written,read", [
    ("250.00", "25.00"),      # a real price error must still fail
    ("250.00", "2500.00"),
    ("19", "7.00 %"),         # wrong VAT rate
    ("0", "10%"),             # discount actually applied
    ("0", "-0.01"),
    ("1234.50", "1.234,50"),  # ambiguous grouping must not silently pass
])
def test_value_differences_still_fail(written, read):
    assert not numeric_match(written, read)


@pytest.mark.parametrize("written,read", [
    ("250.00", ""),           # the async-empty read
    ("250.00", "abc"),
    ("250.00", "--"),
])
def test_unparseable_reads_fail(written, read):
    assert not numeric_match(written, read)


def test_exact_match_still_strict_for_text_fields():
    assert exact_match("Berlin", "Berlin")
    assert exact_match("Berlin", "  Berlin  ")
    assert not exact_match("Berlin", "Berlim")
    # Text fields must NOT get the numeric leniency.
    assert not exact_match("0", "0%")
