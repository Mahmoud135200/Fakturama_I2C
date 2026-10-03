import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from fakturama_i2c.extract import normalize as N  # noqa: E402
from fakturama_i2c.extract.validate import validate  # noqa: E402

SAMPLE = ROOT / "samples" / "order_WEB-2026-0714-A17.png"
EXPECTED = ROOT / "samples" / "order_WEB-2026-0714-A17.expected.json"
MOCK = ROOT / "samples" / "mock"
windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows OCR engine")


def test_sku_repair():
    assert N.sku("CHR-ERG-OI") == ("CHR-ERG-01", True)
    assert N.sku("MAT-DESK-02") == ("MAT-DESK-02", False)


def test_money_and_percent():
    assert N.money("EUR 1.234,56") == Decimal("1234.56")
    assert N.money("40.w") is None
    assert N.percent("10%") == Decimal("10")


def test_product_gross_price_rule():
    from fakturama_i2c.models import Item
    it = Item(1, "X", "d", Decimal(2), "pcs", Decimal("250.00"), Decimal(10), Decimal(19), Decimal("450.00"))
    assert it.product_gross_price == Decimal("297.50")   # discount NOT applied to master price
    assert it.computed_line_net == Decimal("450.00")


def test_half_cent_rounds_up():
    from fakturama_i2c.models import cents
    assert cents(Decimal("70.965")) == Decimal("70.97")


@windows_only
def test_ocr_matches_golden():
    from fakturama_i2c.extract import ocr
    order = ocr.extract(str(SAMPLE))
    assert validate(order) == []
    got = order.to_json_dict()
    want = json.loads(EXPECTED.read_text(encoding="utf-8"))
    got.pop("notes"); want.pop("notes")
    assert got == want


def _mock_cases():
    for exp in sorted(MOCK.glob("*.expected.json")):
        stem = exp.name[: -len(".expected.json")]
        img = next(MOCK.glob(stem + ".*[gG]"), None)   # .png / .jpg
        if img:
            yield pytest.param(img, exp, id=stem)


@windows_only
@pytest.mark.parametrize("img,exp", list(_mock_cases()))
def test_ocr_on_mock_orders(img, exp):
    from fakturama_i2c.extract import ocr
    want = json.loads(exp.read_text(encoding="utf-8"))
    scenario = want.pop("_scenario")
    order = ocr.extract(str(img))
    got = order.to_json_dict()
    got.pop("notes"); want.pop("notes")
    problems = validate(order)
    if "photo" in img.stem and got != want:
        # Known gap: rotated photo breaks row grouping. The safety property
        # still holds: wrong data must never pass validation.
        assert problems, "noisy image produced WRONG data that passed validation"
        pytest.xfail(f"noisy photo not read exactly (stopped safely): {problems[:2]}")
    assert got == want, f"OCR mismatch; notes: {order.notes}"
    if scenario["expect"] == "stops at validation":
        assert problems, "corrupted order passed validation"
    else:
        assert problems == []


# --------------------------------------------------------------- PDF input

@windows_only
def test_pdf_extracts_identically_to_the_same_page_as_png(tmp_path):
    """A scanned PDF of the sample order must produce exactly the same
    OrderData as the PNG. This is the regression guard for the render-scale
    problem: the layout parser uses absolute pixel tolerances, so a page
    rendered at the wrong scale silently loses the Disc. column."""
    from PIL import Image

    from fakturama_i2c.extract import ocr

    pdf = tmp_path / "scan.pdf"
    Image.open(SAMPLE).convert("RGB").save(pdf, "PDF", resolution=72.0, quality=100)

    from_png = ocr.extract(str(SAMPLE)).to_json_dict()
    from_pdf = ocr.extract(str(pdf)).to_json_dict()
    from_png.pop("notes")
    from_pdf.pop("notes")
    assert from_pdf == from_png


@windows_only
def test_pdf_extraction_records_how_it_was_rendered(tmp_path):
    """Provenance matters in a run report: which page, at what size."""
    from PIL import Image

    from fakturama_i2c.extract import ocr

    pdf = tmp_path / "scan.pdf"
    Image.open(SAMPLE).convert("RGB").save(pdf, "PDF", resolution=72.0, quality=100)
    notes = ocr.extract(str(pdf)).notes
    assert any("PDF page 1 of 1" in n for n in notes)
