
from __future__ import annotations

import difflib
import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Optional

from PIL import Image, ImageFilter, ImageOps

from ..models import Address, Debtor, Item, OrderData, Payment, Totals
from . import loader
from . import normalize as N
from .validate import validate


@dataclass
class Word:
    text: str
    x: float
    y: float
    w: float
    h: float

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2


@dataclass
class Line:
    text: str
    words: list[Word]

    @property
    def x(self) -> float:
        return min(w.x for w in self.words)

    @property
    def y(self) -> float:
        return min(w.y for w in self.words)

    @property
    def bottom(self) -> float:
        return max(w.y + w.h for w in self.words)


# OCR

def _variants(img: Image.Image) -> Iterable[tuple[str, int, Image.Image]]:
    for s in (2, 3, 4):
        big = img.resize((img.width * s, img.height * s), Image.LANCZOS)
        yield f"x{s}", s, big
        yield f"x{s}-gray", s, ImageOps.grayscale(big).convert("RGB")
        yield f"x{s}-sharp", s, big.filter(ImageFilter.SHARPEN)


def ocr_lines(img: Image.Image, scale: int) -> list[Line]:
    import winocr  

    res = winocr.recognize_pil_sync(img, "en")
    out = []
    for ln in res["lines"]:
        words = [Word(w["text"], *(w["bounding_rect"][k] / scale for k in ("x", "y", "width", "height")))
                 for w in ln["words"]]
        out.append(Line(ln["text"], words))
    return out


#parsing

def _similar(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a.upper(), b.upper()).ratio()


def _find_label(lines: list[Line], label: str, min_ratio: float = 0.75) -> Optional[Line]:
    best = max(lines, key=lambda l: _similar(l.text, label), default=None)
    return best if best and _similar(best.text, label) >= min_ratio else None


def _below(lines: list[Line], anchor: Line, max_lines: int = 1, x_tol: float = 20, gap: float = 30) -> list[str]:
    """Lines left-aligned with `anchor` directly beneath it, stopping at a vertical gap."""
    col = sorted((l for l in lines if abs(l.x - anchor.x) <= x_tol and l.y > anchor.y + 2), key=lambda l: l.y)
    out, last_bottom = [], anchor.bottom
    for l in col:
        if l.y - last_bottom > gap or len(out) >= max_lines:
            break
        out.append(l.text.strip())
        last_bottom = l.bottom
    return out


def _value(lines, label, **kw) -> Optional[str]:
    a = _find_label(lines, label)
    if not a:
        return None
    v = _below(lines, a, **kw)
    return v[0] if v else None


def _address(lines, label) -> list[str]:
    a = _find_label(lines, label)
    return _below(lines, a, max_lines=5) if a else []


_NUMERIC_HEADERS = {"qty": "Qty", "unit": "Unit", "unit_net": "Unit net", "discount": "Disc.",
                    "vat": "VAT", "line_net": "Line net"}
_CODE = re.compile(r"^[A-Z0-9|]+(-[A-Z0-9|]+)+$")


def _items(lines: list[Line]) -> list[dict]:
   
    labels = list(_NUMERIC_HEADERS.values())
    hits = [l for l in lines if max(_similar(l.text, lab) for lab in labels) >= 0.75]
    if not hits:
        return []
    anchor = max(hits, key=lambda h: sum(abs(o.y - h.y) < 15 for o in hits))
    header_band = [l for l in lines if abs(l.y - anchor.y) < 15]
    if sum(l in hits for l in header_band) < 3:
        return []

    centers: dict[str, float] = {}
    for key, label in _NUMERIC_HEADERS.items():
        cand = max(header_band, key=lambda l: _similar(l.text, label))
        if _similar(cand.text, label) >= 0.75:
            centers[key] = sum(w.cx for w in cand.words) / len(cand.words)
    # "Unit" and "Unit net" fuzzy-match each other; keep the exact owner.
    if "unit" in centers and "unit_net" in centers and abs(centers["unit"] - centers["unit_net"]) < 5:
        del centers["unit"]
    if "qty" not in centers:
        return []
    keys = sorted(centers, key=centers.get)
    nxt = min((c for c in centers.values() if c > centers["qty"]), default=centers["qty"] + 50)
    text_limit = centers["qty"] - (nxt - centers["qty"]) / 2      # left edge of the Qty column

    header_bottom = max(l.bottom for l in header_band)
    stop = _find_label(lines, "NET TOTAL")
    stop_y = stop.y if stop else float("inf")
    words = [w for l in lines if header_bottom < l.y < stop_y for w in l.words]
    cols = {}
    for i, k in enumerate(keys):
        left = (centers[keys[i - 1]] + centers[k]) / 2 if i else text_limit
        right = (centers[k] + centers[keys[i + 1]]) / 2 if i + 1 < len(keys) else 2 * centers[k] - left
        cols[k] = (left, right)

    rows: list[list[Word]] = []
    for w in sorted(words, key=lambda w: w.cy):
        if rows and abs(sum(x.cy for x in rows[-1]) / len(rows[-1]) - w.cy) < 16:
            rows[-1].append(w)
        else:
            rows.append([w])

    out = []
    for r in rows:
        r = sorted(r, key=lambda w: w.x)
        text = [w for w in r if w.cx < text_limit]
        nums = [w for w in r if w.cx >= text_limit]
        row: dict[str, str] = {}
        if text and text[0].text.isdigit() and len(text) > 1:
            row["pos"] = text.pop(0).text
        sku_i = next((i for i, w in enumerate(text) if _CODE.match(w.text)), None)
        if sku_i is None:
            continue
        row["sku"] = text[sku_i].text
        row["description"] = " ".join(w.text for w in text[sku_i + 1:])
        cells: dict[str, list[Word]] = {}
        for w in nums:
            cells.setdefault(min(keys, key=lambda k: abs(centers[k] - w.cx)), []).append(w)
        row.update({k: " ".join(x.text for x in v) for k, v in cells.items()})
       
        row["_cy"] = sum(w.cy for w in r) / len(r)
        row["_cols"] = cols
        out.append(row)
    return out


def parse(lines: list[Line]) -> dict:
    
    r: dict = {
        "external_reference": _value(lines, "EXTERNAL REFERENCE"),
        "order_date": _value(lines, "ORDER DATE"),
        "customer_id": _value(lines, "CUSTOMER ID"),
        "currency": _value(lines, "CURRENCY"),
        "company": _value(lines, "COMPANY"),
        "alias": _value(lines, "CUSTOMER ALIAS"),
        "contact": _value(lines, "CONTACT NAME"),
        "email": _value(lines, "EMAIL"),
        "phone": _value(lines, "PHONE"),
        "payment_method": _value(lines, "PAYMENT METHOD"),
        "paid_status": _value(lines, "PAID STATUS"),
        "payment_date": _value(lines, "PAYMENT DATE"),
        "net_total": _value(lines, "NET TOTAL", x_tol=40),
        "vat_total": _value(lines, "VAT TOTAL", x_tol=40),
        "gross_total": _value(lines, "GROSS TOTAL", x_tol=40),
    }
    for kind, label in (("billing", "BILLING ADDRESS"), ("delivery", "DELIVERY ADDRESS")):
        for i, v in enumerate(_address(lines, label)):
            r[f"{kind}_{i}"] = v
    for i, row in enumerate(_items(lines)):
        for k, v in row.items():
            r[f"item{i}_{k}" if not k.startswith("_") else f"item{i}_{k}"] = v
    return r


# voting

_VALIDATORS = {
    "order_date": N.iso_date, "payment_date": N.iso_date,
    "net_total": N.money, "vat_total": N.money, "gross_total": N.money,
}


def _field_ok(key: str, val: str) -> bool:
    if key in _VALIDATORS:
        return _VALIDATORS[key](val) is not None
    if key.endswith(("_unit_net", "_line_net")):
        return N.money(val) is not None
    if key.endswith(("_discount", "_vat")):
        return N.percent(val) is not None
    if key.endswith("_qty"):
        return N.quantity(val) is not None
    return True


def vote(parses: list[dict]) -> tuple[dict, list[str]]:
    keys = {k for p in parses for k in p if "__" not in k}
    out, notes = {}, []
    for k in sorted(keys):
        vals = [p[k] for p in parses if p.get(k) and _field_ok(k, p[k])]
        if not vals:
            continue
        (best, n), *rest = Counter(vals).most_common()
        out[k] = best
        if rest and rest[0][1] == n:
            notes.append(f"OCR tie on {k}: {[v for v, c in Counter(vals).most_common() if c == n]}")
    return out, notes


#to OrderData

def _addr(raw: dict, kind: str) -> Address:
    lines = [raw.get(f"{kind}_{i}", "") for i in range(5)]
    lines = [l for l in lines if l]
    zi = next((i for i, l in enumerate(lines) if N.split_zip_city(l)[0]), None)
    zip_, city = N.split_zip_city(lines[zi]) if zi is not None else ("", "")
    street = lines[zi - 1] if zi and zi >= 1 else ""
    name = lines[0] if zi and zi >= 2 else ""
    country = lines[zi + 1] if zi is not None and zi + 1 < len(lines) else ""
    return Address(name=name, street=street, zip=zip_, city=city, country=country)


def to_order(raw: dict, notes: list[str]) -> OrderData:
    first, last = N.split_name(raw.get("contact") or "")
    items = []
    i = 0
    while f"item{i}_sku" in raw:
        g = lambda k: raw.get(f"item{i}_{k}")
        s, repaired = N.sku(g("sku"))
        if repaired:
            notes.append(f"item {i + 1}: SKU OCR-repaired {g('sku')!r} -> {s!r}")
        pos = N.quantity(g("pos"))
        items.append(Item(
            position=int(pos) if pos else i + 1,
            sku=s or "",
            description=N.unit_digits(g("description") or ""),
            quantity=N.quantity(g("qty")),
            unit=g("unit") or "",
            unit_net=N.money(g("unit_net")),
            discount_pct=N.percent(g("discount")) if g("discount") else None,
            vat_pct=N.percent(g("vat")),
            line_net=N.money(g("line_net")),
        ))
        i += 1
    status = (raw.get("paid_status") or "").upper()
    ref, repaired = N.code(raw.get("external_reference"))
    if repaired:
        notes.append(f"external reference OCR-repaired {raw.get('external_reference')!r} -> {ref!r}")
    return OrderData(
        external_reference=ref or "",
        order_date=N.iso_date(raw.get("order_date")),
        debtor=Debtor(
            company=raw.get("company") or "", first_name=first, last_name=last,
            alias=raw.get("alias") or "", email=raw.get("email") or "", phone=raw.get("phone") or "",
            customer_id=raw.get("customer_id"),
            billing=_addr(raw, "billing"), delivery=_addr(raw, "delivery"),
        ),
        payment=Payment(method=raw.get("payment_method") or "", status=status,
                        payment_date=N.iso_date(raw.get("payment_date"))),
        items=items,
        totals=Totals(net=N.money(raw.get("net_total")), vat=N.money(raw.get("vat_total")),
                      gross=N.money(raw.get("gross_total")), currency=(raw.get("currency") or "EUR").strip()),
        notes=notes,
    )


_CELL_FIELDS = ("qty", "unit_net", "discount", "vat", "line_net")
_rapid = None


def init_cell_engine():
   
    global _rapid
    if _rapid is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
            _rapid = RapidOCR()
        except ImportError:
            _rapid = False
    return _rapid


def cell_texts(crop: Image.Image) -> list[str]:
    
    if _rapid:
        import numpy as np
        big = crop.resize((crop.width * 3, crop.height * 3), Image.LANCZOS)
        res, _ = _rapid(np.array(big))
        return [" ".join(r[1] for r in res or [])]

    out: list[str] = []
    for scale, border, transform in (
        (8, 120, None),
        (9, 120, None),
        (6, 120, None),
        (12, 80, None),
        (8, 120, "sharpen"),
        (9, 120, "threshold"),
        (6, 120, "autocontrast"),
        (3, 60, None),          # original variant, kept as a last resort
    ):
        big = crop.resize((crop.width * scale, crop.height * scale), Image.LANCZOS)
        if transform == "sharpen":
            big = big.filter(ImageFilter.SHARPEN)
        elif transform == "autocontrast":
            big = ImageOps.autocontrast(ImageOps.grayscale(big)).convert("RGB")
        elif transform == "threshold":
            grey = ImageOps.grayscale(big)
            big = grey.point(lambda v: 255 if v > 140 else 0).convert("RGB")
        padded = ImageOps.expand(big, border=border, fill="white")
        try:
            text = " ".join(l.text for l in ocr_lines(padded, 1)).strip()
        except Exception:
            continue
        if not text:
            continue
        out.append(text)
       
        squashed = text.replace(" ", "")
        if squashed != text:
            out.append(squashed)
    return out


def cell_text(crop: Image.Image) -> str:
    """First non-empty reading of a cell (kept for callers wanting one value)."""
    texts = cell_texts(crop)
    return texts[0] if texts else ""


def _reocr_cells(img: Image.Image, parses: list[dict], raw: dict, notes: list[str]) -> None:
    
    n = sum(1 for k in raw if k.endswith("_sku"))
    geo = next((p for p in parses if sum(1 for k in p if k.endswith("_sku")) == n), None)
    if not geo:
        return
    for i in range(n):
        cols, cy = geo.get(f"item{i}__cols", {}), geo.get(f"item{i}__cy")
        for f in _CELL_FIELDS:
            key = f"item{i}_{f}"
            if key in raw or f not in cols:
                continue
            left, right = cols[f]
            crop = img.crop((int(left) + 3, int(cy - 15), int(right) - 3, int(cy + 15)))
            for t in cell_texts(crop):
                t = t.strip()
                if t and _field_ok(key, t):
                    raw[key] = t
                    notes.append(f"item {i + 1}: {f} recovered by cell OCR -> {t!r}")
                    break


def _extract_image(img: Image.Image) -> OrderData:
   
    parses = [parse(ocr_lines(v, s)) for _, s, v in _variants(img)]
    raw, notes = vote(parses)
    _reocr_cells(img, parses, raw, notes)
    return to_order(raw, notes)


def extract(path: str, page: int = 1, dpi: int | None = None) -> OrderData:
    
    init_cell_engine()

    if dpi is not None or not loader.is_pdf(path):
        img = loader.load_document(path, page=page, dpi=dpi)
        order = _extract_image(img)
        note = loader.describe_source(path, page=page, dpi=dpi)
        if note:
            order.notes.append(note)
        return order

    first: OrderData | None = None
    widths = loader.pdf_render_widths(path, page)
    for width in widths:
        img = loader.load_document(path, page=page, width=width)
        order = _extract_image(img)
        order.notes.append(
            f"source: PDF page {page} of {loader.pdf_page_count(path)}, "
            f"rendered {img.width}x{img.height}")
        if not validate(order):
            if width != widths[0]:
                order.notes.append(
                    f"render widths {widths[:widths.index(width)]} did not validate; "
                    f"{width}px did")
            return order
        if first is None:
            first = order

    assert first is not None
    first.notes.append(f"no render width in {widths} passed validation")
    return first
