from __future__ import annotations

import difflib
import time
from pathlib import Path
from typing import Optional

import uiautomation as auto
from PIL import Image, ImageOps

from ..errors import VerificationError
from ..extract.ocr import Line, ocr_lines
from .wait import wait_until


def _similar(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a.upper(), b.upper()).ratio()


_DARK_SCANLINE = 150


_ROW_CLICK_WIDTH_FRACTION = 4


_ROW_CLICK_MIN_INSET_PX = 60


_ROW_GROUPING_TOLERANCE_PX = 14


_HEADER_BAND_PX = 12


_HEADER_TOP_MARGIN_PX = 6


_HEADER_LINE_SIMILARITY = 0.7
_HEADER_CELL_SIMILARITY = 0.6


def _normalize_polarity(img: Image.Image, sample_step: int = 4) -> Image.Image:
    grey = ImageOps.grayscale(img)
    source = grey.load()
    out = grey.copy()
    target = out.load()
    width, height = grey.size
    columns = range(0, width, sample_step)

    for y in range(height):
        samples = sorted(source[x, y] for x in columns)
        if samples[len(samples) // 2] < _DARK_SCANLINE:
            for x in range(width):
                target[x, y] = 255 - source[x, y]
    return out.convert("RGB")


_HIGHLIGHT_SCALE = 6


def _grid_lines(img: Image.Image, scale: int) -> list[Line]:
    big = img.resize((img.width * scale, img.height * scale), Image.LANCZOS)
    normal = ocr_lines(big, scale)

    try:
        flat = _normalize_polarity(img)
        extra = ocr_lines(
            flat.resize((img.width * _HIGHLIGHT_SCALE, img.height * _HIGHLIGHT_SCALE),
                        Image.LANCZOS),
            _HIGHLIGHT_SCALE)
    except Exception:
        return normal
    if not extra:
        return normal

    def covered(line: Line) -> bool:
        centre = (line.y + line.bottom) / 2
        right = max(w.x + w.w for w in line.words)
        for other in normal:
            if not (other.y <= centre <= other.bottom):
                continue

            if line.x < max(w.x + w.w for w in other.words) and other.x < right:
                return True
        return False

    return normal + [ln for ln in extra if not covered(ln)]


def _park_cursor(app) -> None:
    try:
        rect = app.window.BoundingRectangle
        auto.SetCursorPos((rect.left + rect.right) // 2, rect.top + 4)

        time.sleep(0.15)
    except Exception:
        pass


def capture(ctrl: auto.Control, tmp_path: Optional[Path] = None, app=None) -> Image.Image:
    if app is not None:
        app.ensure_visible()
        _park_cursor(app)
    import tempfile

    last: Optional[Exception] = None
    for _ in range(4):
        path = tmp_path or Path(tempfile.mktemp(suffix=".png"))
        try:
            ctrl.CaptureToImage(str(path))
            if path.exists():
                img = Image.open(path).convert("RGB")
                if tmp_path is None:
                    path.unlink(missing_ok=True)
                return img
        except Exception as exc:
            last = exc
        if tmp_path is None:
            Path(path).unlink(missing_ok=True)
        time.sleep(0.3)

    rect = ctrl.BoundingRectangle
    if rect.width() > 0 and rect.height() > 0:
        try:
            from PIL import ImageGrab

            img = ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom),
                                 all_screens=True)
            if img.width and img.height:
                grabbed = img.convert("RGB")
                if tmp_path is not None:
                    grabbed.save(str(tmp_path))
                return grabbed
        except Exception as exc:
            last = exc

    raise VerificationError(
        "capture a grid image",
        "a screenshot of the control's rectangle",
        f"CaptureToImage produced no file after 4 attempts and the screen grab "
        f"of rect ({rect.left},{rect.top},{rect.right},{rect.bottom}) also "
        f"failed ({last})",
    )


def read_rows_and_columns(img: Image.Image, headers: list[str],
                           scale: int = 3) -> tuple[list[dict[str, str]], dict[str, float]]:
    rows = read_rows(img, headers, scale=scale)
    return rows, _column_centers(img, headers, scale=scale)


def _column_centers(img: Image.Image, headers: list[str],
                     scale: int = 3) -> dict[str, float]:
    lines = _grid_lines(img, scale)
    if not lines:
        return {}
    scored = [(ln, max(_similar(ln.text, h) for h in headers)) for ln in lines]
    header_lines = [ln for ln, s in scored if s >= _HEADER_LINE_SIMILARITY]
    if not header_lines:
        return {}
    header_y = min(ln.y for ln in header_lines)
    header_band = [ln for ln in lines if abs(ln.y - header_y) < _HEADER_BAND_PX]

    centers: dict[str, float] = {}
    for h in headers:
        cand = max(header_band, key=lambda l: _similar(l.text, h), default=None)
        if cand is not None and _similar(cand.text, h) >= _HEADER_CELL_SIMILARITY:
            centers[h] = sum(w.cx for w in cand.words) / len(cand.words)

    for i, h in enumerate(headers):
        if h in centers:
            continue
        before = next((headers[j] for j in range(i - 1, -1, -1)
                       if headers[j] in centers), None)
        after = next((headers[j] for j in range(i + 1, len(headers))
                      if headers[j] in centers), None)
        if before and after:
            centers[h] = (centers[before] + centers[after]) / 2
    return centers


def read_rows(img: Image.Image, headers: list[str], scale: int = 3) -> list[dict[str, str]]:
    lines = _grid_lines(img, scale)
    if not lines:
        return []

    # Header row: the band of lines with the most header-label matches.
    scored = [(ln, max(_similar(ln.text, h) for h in headers)) for ln in lines]
    header_lines = [ln for ln, s in scored if s >= _HEADER_LINE_SIMILARITY]
    if not header_lines:
        return []
    header_y = min(ln.y for ln in header_lines)
    header_band = [ln for ln in lines if abs(ln.y - header_y) < _HEADER_BAND_PX]

    centers: dict[str, float] = {}
    for h in headers:
        cand = max(header_band, key=lambda l: _similar(l.text, h), default=None)
        if cand is not None and _similar(cand.text, h) >= _HEADER_CELL_SIMILARITY:
            centers[h] = sum(w.cx for w in cand.words) / len(cand.words)
    if not centers:
        return []

    header_bottom = max(ln.bottom for ln in header_band)
    body = [ln for ln in lines if ln.y > header_bottom + 2]

    rows: list[list[Line]] = []
    for ln in sorted(body, key=lambda l: l.y):
        if rows and abs(rows[-1][0].y - ln.y) < _ROW_GROUPING_TOLERANCE_PX:
            rows[-1].append(ln)
        else:
            rows.append([ln])

    out = []
    for r in rows:
        row: dict[str, str] = {}
        for ln in r:
            col = min(centers, key=lambda h: abs(centers[h] - ln.x))
            row[col] = (row.get(col, "") + " " + ln.text).strip()
        if row:
            tops = [w.y for ln in r for w in ln.words]
            bottoms = [w.y + w.h for ln in r for w in ln.words]
            row["_top"] = min(tops)
            row["_bottom"] = max(bottoms)
            row["_cy"] = (row["_top"] + row["_bottom"]) / 2

            words = [w for ln in r for w in ln.words]
            leftmost = min(words, key=lambda w: w.x)
            row["_x0"] = leftmost.cx
            out.append(row)
    return out


def read_grid(ctrl: auto.Control, headers: list[str], app=None) -> list[dict[str, str]]:
    return read_rows(capture(ctrl, app=app), headers)


def find_band(img: Image.Image, headers: list[str], stop_labels: tuple[str, ...],
              scale: int = 2) -> tuple[int, int]:
    big = img.resize((img.width * scale, img.height * scale), Image.LANCZOS)
    try:
        lines = ocr_lines(big, scale)
    except Exception:
        return 0, img.height
    if not lines:
        return 0, img.height

    def header_score(line: Line) -> int:
        words = line.text.split()
        return sum(1 for h in headers
                   if any(_similar(w, h) >= 0.8 for w in words))

    header = max(lines, key=header_score, default=None)
    if header is None or header_score(header) < 2:
        return 0, img.height

    top = max(0, int(header.y) - _HEADER_TOP_MARGIN_PX)
    below = [ln for ln in lines if ln.y > header.bottom]
    stop = next((ln for ln in sorted(below, key=lambda l: l.y)
                 if any(_similar(w, label) >= 0.85
                        for w in ln.text.split() for label in stop_labels)), None)
    bottom = int(stop.y) - 3 if stop is not None else img.height
    return top, max(top + 10, min(bottom, img.height))


def row_click_point(ctrl: auto.Control, row: dict) -> tuple[int, int]:
    """Screen point to click for `row`, from the grid's live UIA rectangle
    plus the row's OCR-measured vertical centre. No fixed screen coordinate
    and no fixed row height."""
    if "_cy" not in row:
        raise VerificationError(
            "click a grid row",
            "a row carrying its grid geometry ('_cy')",
            f"got {sorted(row)} -- this row did not come from grid_ocr, or a "
            "matcher rebuilt it and dropped the geometry (see "
            "flow._carry_geometry)",
        )
    rect = ctrl.BoundingRectangle

    width = rect.right - rect.left
    x = rect.left + max(_ROW_CLICK_MIN_INSET_PX, width // _ROW_CLICK_WIDTH_FRACTION)
    y = rect.top + int(round(row["_cy"]))
    return x, y


def cell_point(origin: tuple[int, int], row: dict, centers: dict[str, float],
               header: str) -> Optional[tuple[int, int]]:
    if header not in centers or "_cy" not in row:
        return None
    left, top = origin
    return (left + int(round(centers[header])), top + int(round(row["_cy"])))


def edit_cell(origin: tuple[int, int], row: dict, centers: dict[str, float],
              header: str, value: str, app) -> bool:
    point = cell_point(origin, row, centers, header)
    if point is None:
        return False
    x, y = point
    app.ensure_visible()
    auto.Click(x, y, waitTime=0.15)
    double_click(x, y)
    auto.SendKeys("{Ctrl}a", waitTime=0.05)
    auto.SendKeys(str(value), waitTime=0.02)
    auto.SendKeys("{Enter}", waitTime=0.3)
    return True


def _band_mean(img: Image.Image, row: dict) -> Optional[tuple[float, float, float]]:
    """Mean colour of a row's left-hand strip, clear of its glyphs."""
    top = max(0, int(row["_top"]))
    bottom = min(img.height, int(row["_bottom"]) + 1)
    if bottom <= top:
        return None
    strip = img.crop((0, top, max(1, img.width // 12), bottom))
    pixels = list(strip.getdata())
    if not pixels:
        return None
    return tuple(sum(p[i] for p in pixels) / len(pixels) for i in range(3))


def _distance(a, b) -> float:
    return sum(abs(a[i] - b[i]) for i in range(3))


def selected_row_index(ctrl: auto.Control, rows: list[dict], app=None,
                        threshold: float = 60.0) -> Optional[int]:
    img = capture(ctrl, app=app)
    means = [(i, _band_mean(img, r)) for i, r in enumerate(rows)]
    means = [(i, m) for i, m in means if m is not None]
    if not means:
        return None
    if len(means) == 1:
        base_strip = img.crop((0, max(0, img.height - 12),
                               max(1, img.width // 12), img.height))
        pixels = list(base_strip.getdata())
        if not pixels:
            return None
        base = tuple(sum(p[i] for p in pixels) / len(pixels) for i in range(3))
        return means[0][0] if _distance(means[0][1], base) > threshold else None

    scored = []
    for i, mean in means:
        others = [m for j, m in means if j != i]
        median = tuple(sorted(o[c] for o in others)[len(others) // 2] for c in range(3))
        scored.append((_distance(mean, median), i))

    scored.sort(reverse=True)
    best_distance, best_index = scored[0]
    return best_index if best_distance > threshold else None


def row_is_selected(ctrl: auto.Control, row: dict, rows: list[dict], app=None) -> bool:
    """Is `row` -- specifically, not merely some row -- the selected one?"""
    try:
        target = next(i for i, r in enumerate(rows) if r is row)
    except StopIteration:
        target = next((i for i, r in enumerate(rows)
                       if r.get("_cy") == row.get("_cy")), None)
        if target is None:
            return False
    return selected_row_index(ctrl, rows, app=app) == target


def double_click(x: int, y: int) -> None:
    auto.SetCursorPos(x, y)
    for _ in range(2):
        auto.PressMouse(x, y, waitTime=0)
        auto.ReleaseMouse(waitTime=0)
    time.sleep(0.4)


def click_row(ctrl: auto.Control, row: dict, app, rows: Optional[list[dict]] = None,
              attempts: int = 3) -> None:
    app.ensure_visible()
    all_rows = rows if rows else [row]
    x, y = row_click_point(ctrl, row)

    for attempt in range(attempts):
        auto.Click(x, y, waitTime=0.2)
        double_click(x, y)

        try:
            if not ctrl.Exists(0.3, 0.2):
                return
        except Exception:
            return

        try:
            wait_until(lambda: row_is_selected(ctrl, row, all_rows, app),
                       "the intended grid row to become selected",
                       timeout=2, interval=0.2)
            return
        except Exception:
            if attempt == attempts - 1:
                got = selected_row_index(ctrl, all_rows, app=app)
                wanted = {k: v for k, v in row.items() if not k.startswith("_")}
                got_row = (
                    {k: v for k, v in all_rows[got].items() if not k.startswith("_")}
                    if got is not None else None
                )
                raise VerificationError(
                    "select grid row",
                    f"row {wanted} selected",
                    f"clicked ({x}, {y}) {attempts}x; selected row is "
                    f"{got_row!r} (index {got})",
                )
