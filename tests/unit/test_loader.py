
from pathlib import Path

import pytest
from PIL import Image

from fakturama_i2c.extract import loader

ROOT = Path(__file__).resolve().parents[2]
SAMPLE_PNG = ROOT / "samples" / "order_WEB-2026-0714-A17.png"


@pytest.fixture
def pdf_from_sample(tmp_path) -> Path:
    """A one-page PDF wrapping the sample order image, like a scan would be."""
    out = tmp_path / "scan.pdf"
    Image.open(SAMPLE_PNG).convert("RGB").save(out, "PDF", resolution=72.0, quality=100)
    return out


# ------------------------------------------------------------------ detection

def test_pdf_detected_by_magic_bytes_not_suffix(tmp_path, pdf_from_sample):
    """A scanner that names a PDF '.jpg' must still work -- otherwise the
    failure surfaces much later as 'cannot identify image file'."""
    misnamed = tmp_path / "order.jpg"
    misnamed.write_bytes(pdf_from_sample.read_bytes())
    assert loader.is_pdf(misnamed) is True


def test_real_image_is_not_mistaken_for_pdf():
    assert loader.is_pdf(SAMPLE_PNG) is False


def test_missing_file_raises_clearly(tmp_path):
    with pytest.raises(loader.UnsupportedDocumentError, match="no such file"):
        loader.load_document(tmp_path / "nope.png")


def test_unreadable_file_lists_supported_types(tmp_path):
    junk = tmp_path / "order.xyz"
    junk.write_bytes(b"not an image")
    with pytest.raises(loader.UnsupportedDocumentError, match="Supported: PDF"):
        loader.load_document(junk)


# --------------------------------------------------------------------- images

def test_image_loads_as_rgb():
    img = loader.load_document(SAMPLE_PNG)
    assert img.mode == "RGB"
    assert img.width == 883            # untouched: already near REFERENCE_WIDTH


def test_oversized_image_is_scaled_to_the_parser_reference(tmp_path):
    big = tmp_path / "huge.png"
    Image.open(SAMPLE_PNG).convert("RGB").resize((3532, 4856)).save(big)
    assert loader.load_document(big).width == loader.REFERENCE_WIDTH


def test_image_near_the_reference_is_left_alone(tmp_path):
    """The 963px phone photo must not be resampled for no reason."""
    photo = tmp_path / "photo.png"
    Image.open(SAMPLE_PNG).convert("RGB").resize((963, 1293)).save(photo)
    assert loader.load_document(photo).width == 963


# ----------------------------------------------------------------------- PDFs

def test_pdf_page_count(pdf_from_sample):
    assert loader.pdf_page_count(pdf_from_sample) == 1


def test_pdf_renders_to_rgb(pdf_from_sample):
    img = loader.load_document(pdf_from_sample)
    assert img.mode == "RGB" and img.width > 0


def test_native_raster_width_is_detected(pdf_from_sample):
    """This is what lets us render 1:1 with the scan and avoid resampling."""
    assert loader.embedded_raster_width(pdf_from_sample) == 883


def test_native_width_is_the_first_candidate(pdf_from_sample):
    widths = loader.pdf_render_widths(pdf_from_sample)
    assert widths[0] == 883
    assert loader.REFERENCE_WIDTH in widths      # fallback for vector PDFs


def test_candidate_widths_are_not_near_duplicates(pdf_from_sample):
    widths = loader.pdf_render_widths(pdf_from_sample)
    assert len(widths) == len(set(widths))
    assert all(abs(a - b) > 8 for i, a in enumerate(widths) for b in widths[i + 1:])


def test_explicit_width_is_honoured(pdf_from_sample):
    img = loader.render_pdf_page(pdf_from_sample, width=1200)
    assert abs(img.width - 1200) <= 2


def test_explicit_dpi_overrides_width(pdf_from_sample):
    at_150 = loader.render_pdf_page(pdf_from_sample, dpi=150)
    at_300 = loader.render_pdf_page(pdf_from_sample, dpi=300)
    assert at_300.width > at_150.width


def test_out_of_range_page_is_rejected(pdf_from_sample):
    with pytest.raises(loader.UnsupportedDocumentError, match="page 2 was requested"):
        loader.load_document(pdf_from_sample, page=2)


def test_source_note_records_provenance(pdf_from_sample):
    note = loader.describe_source(pdf_from_sample)
    assert note and "PDF page 1 of 1" in note


def test_no_source_note_for_plain_images():
    assert loader.describe_source(SAMPLE_PNG) is None
