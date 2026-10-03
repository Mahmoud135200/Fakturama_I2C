
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional

# Characters OCR commonly returns in place of digits.
_DIGIT_FIXES = str.maketrans({"O": "0", "o": "0", "D": "0", "I": "1", "l": "1", "|": "1", "S": "5", "B": "8"})


def money(s: Optional[str]) -> Optional[Decimal]:
    if not s:
        return None
    s = re.sub(r"(?i)\b(eur|€)\b|€", "", s).strip().translate(_DIGIT_FIXES).replace(" ", "")
    # Accept 1,234.56 and 1.234,56
    if re.fullmatch(r"\d{1,3}(\.\d{3})*,\d{2}", s):
        s = s.replace(".", "").replace(",", ".")
    s = s.replace(",", "")
    if not re.fullmatch(r"-?\d+(\.\d{1,2})?", s):
        return None
    try:
        return Decimal(s).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def percent(s: Optional[str]) -> Optional[Decimal]:
    if not s:
        return None
    # Windows OCR often renders '%' as '0/0' or 'o/o' ('7%' -> '70/0').
    m = re.fullmatch(r"\s*([\dOoIl.,]+?)\s*(?:%|0/0|o/o|O/O|°/o)\s*", s)
    if not m:
        return None
    v = m.group(1).translate(_DIGIT_FIXES).replace(",", ".")
    try:
        return Decimal(v).normalize() if "." in v else Decimal(v)
    except InvalidOperation:
        return None


def quantity(s: Optional[str]) -> Optional[Decimal]:
    if not s:
        return None
    v = s.strip().translate(_DIGIT_FIXES).replace(",", ".")
    return Decimal(v) if re.fullmatch(r"\d+(\.\d+)?", v) else None


def iso_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    v = s.strip().translate(_DIGIT_FIXES)
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", v) or None
    if m:
        y, mo, d = map(int, m.groups())
    else:
        m = re.fullmatch(r"(\d{1,2})[./](\d{1,2})[./](\d{4})", v)
        if not m:
            return None
        d, mo, y = map(int, m.groups())
    try:
        return date(y, mo, d)
    except ValueError:
        return None


_CONF = str.maketrans({"O": "0", "I": "1", "L": "1", "|": "1"})


def code(s: Optional[str]) -> tuple[Optional[str], bool]:
  
    if not s:
        return None, False
    v = unit_digits(re.sub(r"\s+", "", s).upper())
    parts = v.split("-")
    out = []
    def numeric_like(t):
        return t and len(t) <= 6 and all(c.isdigit() or c in "OIL|" for c in t)

    for i, seg in enumerate(parts):
        if i == len(parts) - 1 and numeric_like(seg) and len(seg) <= 3:
            # short final segment made only of digits/look-alikes: 'OI' -> '01'
            seg = seg.translate(_CONF)
        else:
            head, body = (seg[0], seg[1:]) if seg[:1].isalpha() and len(seg) > 1 else ("", seg)
            # letter + numeric body with at least one real digit: 'CI1' -> 'C11'
            if numeric_like(body) and any(c.isdigit() for c in body):
                seg = head + body.translate(_CONF)
        out.append(seg)
    fixed = "-".join(out)
    return fixed, fixed != s.strip()


_UNIT_AFTER_DIGIT = re.compile(r"(?<![A-Za-z])[Il|](?=\s?(?:kg|KG|g|G|ml|ML|l|L|cm|CM|mm|MM|m|M)\b)")


def unit_digits(s: str) -> str:
   
    return _UNIT_AFTER_DIGIT.sub("1", s)


def sku(s: Optional[str]) -> tuple[Optional[str], bool]:
    return code(s)


_ZIP_CITY = re.compile(r"^\s*(\d{4,5})\s+(.+?)\s*$")


def split_zip_city(line: str) -> tuple[str, str]:
    m = _ZIP_CITY.match(line.translate(str.maketrans({"O": "0", "I": "1"})) if line[:5].strip().isalnum() else line)
    if m:
        return m.group(1), m.group(2)
    return "", line.strip()


def split_name(full: str) -> tuple[str, str]:
    parts = full.strip().split()
    if len(parts) < 2:
        return "", full.strip()
    return " ".join(parts[:-1]), parts[-1]
