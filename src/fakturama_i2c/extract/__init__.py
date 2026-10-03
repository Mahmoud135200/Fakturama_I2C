
from __future__ import annotations

from ..models import OrderData
from . import loader, ocr
from .loader import UnsupportedDocumentError  # noqa: F401  (re-exported)
from .validate import ExtractionError, require_valid


def extract(path: str, page: int = 1, dpi: int | None = None) -> OrderData:
    
    order = ocr.extract(path, page=page, dpi=dpi)
    order.notes.append("engine: windows-ocr")
    return require_valid(order)
