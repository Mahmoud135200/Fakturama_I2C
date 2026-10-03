from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal, Optional

Action = Literal["select", "create", "review"]


@dataclass
class Decision:
    action: Action
    row: Optional[dict] = None
    reason: str = ""
    truncated: bool = False


_ELLIPSIS_CHARS = ".…"


def _visible_prefix(displayed: str) -> str:
    """The cell text with its truncation marker removed."""
    return (displayed or "").strip().rstrip(_ELLIPSIS_CHARS).strip()


def _is_truncated(displayed: str) -> bool:
    d = (displayed or "").strip()
    return bool(d) and d[-1] in _ELLIPSIS_CHARS


def _eq_displayed(displayed: str, expected: str) -> bool:
    d = (displayed or "").strip()
    e = (expected or "").strip()
    if d == e:
        return True
    if _is_truncated(d):
        prefix = _visible_prefix(d)
        if prefix and e.startswith(prefix):
            return True
    return False


def match_debtor(rows: list[dict], company: str, first_name: str, last_name: str,
                  zip_: str, city: str) -> Decision:
    fields = (("company", company), ("first_name", first_name), ("name", last_name),
              ("zip", zip_), ("city", city))

    hits = [r for r in rows
            if all(_eq_displayed(r.get(key), expected) for key, expected in fields)]

    if len(hits) == 1:
        row = hits[0]
        relied_on_prefix = any(_is_truncated(row.get(key)) for key, _ in fields)
        return Decision("select", row=row, truncated=relied_on_prefix)
    if len(hits) == 0:
        return Decision("create")
    return Decision("review", reason=f"{len(hits)} conflicting/ambiguous Debtor matches for "
                                      f"company={company!r} name={first_name} {last_name!r} zip={zip_} city={city}")


def match_payment_method(rows: list[dict], method: str) -> Decision:
    hits = [r for r in rows if _eq_displayed(r.get("name"), method)]
    if len(hits) == 1:
        row = hits[0]
        return Decision("select", row=row, truncated=_is_truncated(row.get("name")))
    if len(hits) == 0:
        return Decision("create")
    return Decision("review", reason=f"{len(hits)} conflicting/ambiguous payment methods named {method!r}")


PAYMENT_CODE_MAP = {
    "Bank Transfer": "Credit transfer",
    "Credit Card": "Credit card",
    "SEPA Direct Debit": "SEPA direct debit",
}


def _vat_value(raw) -> Optional[Decimal]:
    text = str(raw or "").strip()
    match = re.match(r"-?\d+(?:[.,]\d+)?", text)
    if not match:
        return None
    try:
        return Decimal(match.group(0).replace(",", "."))
    except (InvalidOperation, ArithmeticError):
        return None


def match_vat(rows: list[dict], vat_pct: Decimal) -> Decision:
    want_name = f"VAT {fmt_pct(vat_pct)}%"
    hits = []
    conflicts = []

    for r in rows:
        name = (r.get("name") or "").strip()
        name_ok = (_eq_displayed(name, want_name)
                   or _eq_displayed(name, "VAT")
                   or name.casefold().startswith("vat"))
        if not name_ok:
            continue

        claims_this_rate = (any(ch.isdigit() for ch in _visible_prefix(name))
                            and _eq_displayed(name, want_name))

        value = _vat_value(r.get("value"))

        if value is None:
            if claims_this_rate:
                conflicts.append(r)
            continue

        if value != vat_pct:
            if claims_this_rate:
                conflicts.append(r)
            continue

        code = r.get("code")
        if code in (None, "", "S"):
            hits.append(r)
        else:
            conflicts.append(r)

    if hits and not conflicts:
        if len(hits) == 1:
            return Decision("select", row=hits[0])
        return Decision("review", reason=f"{len(hits)} duplicate exact VAT rows named {want_name!r}")
    if conflicts:
        return Decision("review", reason=f"VAT row named {want_name!r} exists but value/code do not match "
                                          f"(got {[{'value': c.get('value'), 'code': c.get('code')} for c in conflicts]})")
    return Decision("create")


def fmt_pct(p: Decimal) -> str:
    p = p.normalize()
    return format(p, "f").rstrip("0").rstrip(".") if "." in format(p, "f") else format(p, "f")


def match_product(rows: list[dict], sku: str) -> Decision:
    from ..extract import normalize as N

    def _repaired(value: str) -> str:
        fixed, _ = N.code(value)
        return fixed or ""

    hits = [r for r in rows
            if _eq_displayed(r.get("item_no"), sku)
            or _eq_displayed(_repaired(r.get("item_no", "")), _repaired(sku))]
    if len(hits) == 1:
        row = hits[0]
        return Decision("select", row=row, truncated=_is_truncated(row.get("item_no")))
    if len(hits) == 0:
        return Decision("create")
    return Decision("review", reason=f"{len(hits)} conflicting Product rows for SKU {sku!r}")


_OCR_PERCENT = "0/0"


def parse_number(raw) -> Optional[Decimal]:
    text = str(raw or "").replace(_OCR_PERCENT, "%").strip()
    match = re.search(r"-?\d[\d.,]*", text)
    if not match:
        return None

    token = match.group(0).rstrip(".,")
    if "." in token and "," in token:
        # Whichever separator comes last is the decimal point.
        if token.rfind(",") > token.rfind("."):
            token = token.replace(".", "").replace(",", ".")
        else:
            token = token.replace(",", "")
    elif "," in token:
        head, _, tail = token.rpartition(",")
        token = f"{head}.{tail}" if len(tail) in (1, 2) else token.replace(",", "")

    try:
        return Decimal(token)
    except (InvalidOperation, ArithmeticError):
        return None


_LINE_TOLERANCE = Decimal("0")


def match_order_line(row: dict, quantity: Decimal, unit_net: Decimal,
                     discount_pct: Decimal, vat_pct: Decimal,
                     line_net: Decimal) -> Decision:
    expected = {
        "Qty.": quantity,
        "U.Price": unit_net,
        "Discount": discount_pct,
        "VAT": vat_pct,
        "Price": line_net,
    }

    checked: list[str] = []
    missing: list[str] = []
    wrong: list[str] = []

    for column, want in expected.items():
        got = parse_number(row.get(column))
        if got is None:
            missing.append(column)
            continue
        if column == "Discount":
            got = abs(got)
        checked.append(column)
        if abs(got - want) > _LINE_TOLERANCE:
            wrong.append(f"{column}: expected {want}, grid shows {got}")

    if wrong:
        return Decision("review", reason="; ".join(wrong))
    if not checked:
        return Decision("review",
                        reason=f"none of {list(expected)} could be read from the "
                               f"item row {row!r}")
    return Decision("select", row=row,
                    reason=(f"verified {checked}"
                            + (f"; not rendered: {missing}" if missing else "")))


def totals_match(ui_net: Decimal, ui_vat: Decimal, ui_gross: Decimal,
                  src_net: Decimal, src_vat: Decimal, src_gross: Decimal) -> Decision:
    if (ui_net, ui_vat, ui_gross) == (src_net, src_vat, src_gross):
        return Decision("select")
    return Decision("review", reason=f"UI totals net={ui_net} vat={ui_vat} gross={ui_gross} != "
                                      f"source net={src_net} vat={src_vat} gross={src_gross}")
