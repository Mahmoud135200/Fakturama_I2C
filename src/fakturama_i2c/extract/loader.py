
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PIL import Image


REFERENCE_WIDTH = 900


MIN_SCALE_RATIO = 0.6
MAX_SCALE_RATIO = 1.4


DEFAULT_PDF_DPI = 300

PDF_SUFFIXES = {".pdf"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".gif", ".webp"}


class UnsupportedDocumentError(Exception):
    """The file is neither a readable image nor a PDF."""


def is_pdf(path: str | Path) -> bool:
 
    p = Path(path)
    try:
        with open(p, "rb") as fh:
            if fh.read(5) == b"%PDF-":
                return True
    except OSError:
        pass
    return p.suffix.lower() in PDF_SUFFIXES


def pdf_page_count(path: str | Path) -> int:
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(path))
    try:
        return len(doc)
    finally:
        doc.close()


def embedded_raster_width(path: str | Path, page: int = 1) -> Optional[int]:
 
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(path))
    try:
        if not 1 <= page <= len(doc):
            return None
        images = [o for o in doc[page - 1].get_objects()
                  if type(o).__name__ == "PdfImage"]
        if len(images) != 1:
            return None
        try:
            return int(images[0].get_px_size()[0]) or None
        except Exception:
            return None
    except Exception:
        return None
    finally:
        doc.close()


def pdf_render_widths(path: str | Path, page: int = 1) -> list[int]:

    widths: list[int] = []
    native = embedded_raster_width(path, page)
    if native:
        widths.append(native)
    for w in (REFERENCE_WIDTH, 1100, 1400):
        if all(abs(w - existing) > 8 for existing in widths):
            widths.append(w)
    return widths


def render_pdf_page(path: str | Path, page: int = 1,
                    dpi: Optional[int] = None,
                    width: Optional[int] = None) -> Image.Image:

    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(path))
    try:
        total = len(doc)
        if not 1 <= page <= total:
            raise UnsupportedDocumentError(
                f"{Path(path).name} has {total} page(s); page {page} was requested")
        pdf_page = doc[page - 1]
        width_pt = pdf_page.get_width()            # points, 1pt = 1/72 inch
        if dpi is not None:
            scale = dpi / 72
        elif width is not None and width_pt:
            scale = width / width_pt
        elif width_pt:
            scale = REFERENCE_WIDTH / width_pt
        else:
            scale = DEFAULT_PDF_DPI / 72
        return pdf_page.render(scale=scale).to_pil().convert("RGB")
    finally:
        doc.close()


def normalize_for_parser(img: Image.Image) -> Image.Image:
   
    if img.width <= 0:
        return img
    ratio = img.width / REFERENCE_WIDTH
    if MIN_SCALE_RATIO <= ratio <= MAX_SCALE_RATIO:
        return img
    height = max(1, round(img.height * REFERENCE_WIDTH / img.width))
    return img.resize((REFERENCE_WIDTH, height), Image.LANCZOS)


def load_document(path: str | Path, page: int = 1,
                  dpi: Optional[int] = None,
                  width: Optional[int] = None) -> Image.Image:
 
    p = Path(path)
    if not p.is_file():
        raise UnsupportedDocumentError(f"no such file: {p}")

    if is_pdf(p):
        return render_pdf_page(p, page=page, dpi=dpi, width=width)

    try:
        return normalize_for_parser(Image.open(p).convert("RGB"))
    except UnsupportedDocumentError:
        raise
    except Exception as exc:
        suffix = p.suffix.lower() or "(none)"
        raise UnsupportedDocumentError(
            f"could not read {p.name} as an image (suffix {suffix}): {exc}. "
            f"Supported: PDF, {', '.join(sorted(s.lstrip('.') for s in IMAGE_SUFFIXES))}"
        ) from exc


def describe_source(path: str | Path, page: int = 1,
                    dpi: Optional[int] = None) -> Optional[str]:
    
    if is_pdf(path):
        how = f"{dpi} DPI" if dpi else f"auto-scaled to ~{REFERENCE_WIDTH}px wide"
        return f"source: PDF page {page} of {pdf_page_count(path)}, rendered {how}"
    return None
