from __future__ import annotations

import re
import time
from decimal import Decimal
from typing import Optional

import uiautomation as auto

from . import controls, fields, grid_ocr
from .app import App
from ..errors import VerificationError
from .controls import click, exists, find, set_text, read_text, type_into_search_box
from .wait import wait_until, wait_stable


class DuplicateContact(Exception):
    def __init__(self, company: str):
        super().__init__(f"Fakturama reports an existing contact with the same name and street "
                          f"(attempted Company {company!r})")
        self.company = company


_ACK_POPUPS = ("Duplicate Contact", "Information", "Warning")


_SCROLLBAR_EDGE_TOLERANCE_PX = 40


_SCROLLBAR_MIN_HEIGHT_PX = 80


def _ack_blocking_popups(app: App, timeout: float = 1.5) -> list[str]:
    return [title for title in _ACK_POPUPS
            if controls.dismiss_modal(app.window, title, "OK", timeout=timeout)]


def _visible_modal_title(app: App) -> Optional[str]:
    try:
        for ctrl, _ in auto.WalkControl(app.window, includeTop=False, maxDepth=4):
            try:
                if ctrl.ControlTypeName != "WindowControl":
                    continue
                if not ctrl.BoundingRectangle.width():
                    continue
                name = (ctrl.Name or "").strip()
                if name:
                    return name
            except Exception:
                continue
    except Exception:
        pass
    return None


def _editor_pane(app: App, name: str, timeout: float = 15.0) -> auto.PaneControl:
    def _find():
        p = auto.PaneControl(searchFromControl=app.window, searchDepth=30, Name=name)
        return p if p.Exists(0, 0) else None
    return wait_until(_find, f"editor pane {name!r}", timeout=timeout)


def _tabs_named(app: App, name: str) -> list[auto.Control]:
    seen: set[tuple[int, int, int, int]] = set()
    found: list[auto.Control] = []
    try:
        for ctrl, _ in auto.WalkControl(app.window, includeTop=False, maxDepth=30):
            try:
                if ctrl.ControlTypeName != "TabItemControl":
                    continue
                if (ctrl.Name or "") != name:
                    continue
                r = ctrl.BoundingRectangle
                key = (r.left, r.top, r.right, r.bottom)
                if key in seen:
                    continue
                seen.add(key)
                found.append(ctrl)
            except Exception:
                continue
    except Exception:
        pass
    return found


def _tab_exists(app: App, name: str) -> bool:
    item = auto.TabItemControl(searchFromControl=app.window, searchDepth=30, Name=name)
    return bool(item.Exists(0.4, 0.2))


def _saved_editor_title(app: App, preferred: tuple[str, ...]) -> Optional[str]:
    for candidate in preferred:
        if candidate and _tab_exists(app, candidate):
            return candidate
    return None


class AmbiguousEditorTab(VerificationError):
    """More than one editor tab carries the same name."""


def _unique_tab(app: App, name: str) -> Optional[auto.Control]:
    tabs = _tabs_named(app, name)
    if not tabs:
        return None
    if len(tabs) > 1:
        raise AmbiguousEditorTab(
            "editor tab",
            f"exactly one tab named {name!r}",
            f"{len(tabs)} tabs share that name -- left over from earlier runs. "
            f"Close the stale ones (or restart Fakturama without saving) so "
            f"the automation cannot act on the wrong editor",
        )
    return tabs[0]


def _any_open_editor_title(app: App, exclude: tuple[str, ...] = ()) -> Optional[str]:
    skip = {e for e in exclude} | {f"*{e}" for e in exclude}
    try:
        for ctrl, _ in auto.WalkControl(app.window, includeTop=False, maxDepth=30):
            try:
                if ctrl.ControlTypeName != "TabItemControl":
                    continue
                name = (ctrl.Name or "").strip()
                if not name or name in skip:
                    continue
                if _tab_is_selected(ctrl):
                    return name.lstrip("*")
            except Exception:
                continue
    except Exception:
        pass
    return None


def _activate_editor(app: App, *names: str, timeout: float = 10.0) -> auto.PaneControl:
    candidates: list[str] = []
    for name in names:
        if not name:
            continue
        candidates += [name, f"*{name}", name.lstrip("*")]

    for candidate in candidates:
        item = _unique_tab(app, candidate)
        if item is not None and item.Exists(0.5, 0.2):
            if not _tab_is_selected(item):
                click(item, app)
                try:
                    wait_until(lambda: _tab_is_selected(item),
                               f"editor tab {candidate!r} to activate", timeout=3, interval=0.2)
                except Exception:
                    continue
            pane_name = candidate.lstrip("*")
            for attempt in (pane_name, candidate):
                pane = auto.PaneControl(searchFromControl=app.window, searchDepth=30, Name=attempt)
                if pane.Exists(1, 0.3):
                    return pane

    raise VerificationError("editor activation", f"one of {list(names)}",
                            "no matching editor tab could be activated")


LEFTOVER_DIALOG_TITLES = ("Select the address", "Select a product")


def dismiss_leftover_dialogs(app: App) -> list[str]:
    closed: list[str] = []
    for title in LEFTOVER_DIALOG_TITLES:
        for _ in range(3):
            dlg = auto.WindowControl(searchFromControl=app.window, searchDepth=6, Name=title)
            if not dlg.Exists(0.4, 0.2):
                break
            try:
                click(find(dlg, auto.ButtonControl, timeout=2, Name="Cancel"), app)
            except Exception:
                try:
                    app.ensure_visible()
                    dlg.SendKeys("{Esc}", waitTime=0.2)
                except Exception:
                    break
            if not dlg.Exists(0.4, 0.2):
                closed.append(title)
                break
    return closed


def discard_editor(app: App, title: str) -> bool:
    for candidate in (f"*{title}", title):
        try:
            item = _unique_tab(app, candidate)
        except Exception:
            return False
        if item is None or not item.Exists(0.3, 0.2):
            continue
        try:
            click(item, app)
            app.ensure_visible()
            app.window.SendKeys("{Ctrl}{F4}", waitTime=0.2)
            dlg = controls.find_modal(app.window, "Save Parts", timeout=3)
            if dlg is not None:
                entry = find(dlg, auto.ListItemControl, timeout=2)
                entry.SetFocus()
                entry.SendKeys("{space}", waitTime=0.1)   # uncheck -> do not save
                click(find(dlg, auto.ButtonControl, timeout=2, Name="OK"), app)
            wait_until(lambda: _unique_tab(app, candidate) is None,
                       f"editor tab {candidate!r} to close", timeout=8)
            return True
        except Exception:
            return False
    return False


def _toolbar_button(app: App, tooltip: str, timeout: float = 10.0) -> auto.Control:
    return find(app.window, auto.ButtonControl, timeout=timeout, Name=tooltip)


def _nav_label(app: App, text: str, timeout: float = 10.0) -> auto.Control:
    return find(app.window, auto.TextControl, timeout=timeout, Name=text)


def _tab_is_selected(item: auto.Control) -> bool:
    try:
        return bool(item.GetSelectionItemPattern().IsSelected)
    except Exception:
        return False


def _data_tab(
    app: App,
    name: str,
    timeout: float = 10.0,
    attempts: int = 3,
) -> auto.Control:
    last: Optional[Exception] = None

    for _ in range(max(1, attempts)):
        try:
            _click_data_navigation(app, name, timeout)

            def _find_tab():
                item = auto.TabItemControl(
                    searchFromControl=app.window,
                    searchDepth=30,
                    Name=name,
                )

                return item if item.Exists(0, 0) else None

            item = wait_until(
                _find_tab,
                f"Data Browser tab {name!r}",
                timeout=timeout,
            )

            if not _tab_is_selected(item):
                click(item, app)

            if _tab_is_selected(item):
                return item

            last = VerificationError(
                f"Data Browser tab {name!r}",
                "the tab to be selected",
                "it was found but never became selected",
            )
        except Exception as exc:  # noqa: BLE001
            last = exc

    raise last if last is not None else VerificationError(
        f"Data Browser tab {name!r}", "an open, selected tab", "not reached")


def _grid_of(container: auto.Control, timeout: float = 8.0) -> auto.Control:
    for name in ("Horizontal", "Vertical"):
        if exists(container, auto.ScrollBarControl, timeout=timeout / 2, Name=name):
            return find(container, auto.ScrollBarControl, timeout=1, Name=name).GetParentControl()
    panes = [c for c in container.GetChildren() if c.ControlTypeName == "PaneControl"]
    if panes:
        return panes[-1]
    return container


def _data_browser_tabcontrol(app: App, timeout: float = 10.0) -> auto.Control:
    known_tabs = {
        "Documents",
        "Products",
        "Creditors",
        "Debtors",
        "terms of payment",
        "Shippings",
        "VATs",
        "Texts",
        "Lists",
        "Expenditure Vouchers",
        "Receipt Vouchers",
    }

    def _find():
        candidates = []

        def walk(parent, depth=0):
            if depth > 30:
                return

            try:
                children = parent.GetChildren()
            except Exception:
                return

            for child in children:
                try:
                    if child.ControlTypeName == "TabControl":
                        try:
                            tab_items = child.GetChildren()
                        except Exception:
                            tab_items = []

                        names = []
                        selected = None

                        for item in tab_items:
                            try:
                                if item.ControlTypeName != "TabItemControl":
                                    continue

                                name = (item.Name or "").strip()

                                if name:
                                    names.append(name)

                                if _tab_is_selected(item):
                                    selected = item
                            except Exception:
                                continue

                        matching = set(names) & known_tabs

                        if matching:
                            candidates.append((child, names, selected))

                    walk(child, depth + 1)

                except Exception:
                    continue

        walk(app.window)

        selected_candidates = [
            c for c in candidates
            if c[2] is not None
        ]

        if selected_candidates:
            return selected_candidates[0][0]

        if candidates:
            return candidates[0][0]

        return None

    return wait_until(
        _find,
        "Data Browser TabControl",
        timeout=timeout,
    )


def _wait_rows_stable(get_rows, timeout: float = 10.0) -> list[dict]:
    return wait_stable(lambda: tuple(tuple(sorted(r.items())) for r in get_rows()),
                        "selector list to stabilize", timeout=timeout) and get_rows()


# Order

class OrderEditor:
    NEW_EDITOR_TITLE = "New Order"

    def __init__(self, app: App, pane: auto.PaneControl):
        self.app = app
        self.pane = pane
        self.tab_title = self.NEW_EDITOR_TITLE

    @classmethod
    def open_new(cls, app: App) -> "OrderEditor":
        stale = _tabs_named(app, f"*{cls.NEW_EDITOR_TITLE}")
        if stale:
            raise AmbiguousEditorTab(
                "open New Order",
                f"no leftover '*{cls.NEW_EDITOR_TITLE}' tabs before starting",
                f"{len(stale)} unsaved '{cls.NEW_EDITOR_TITLE}' tab(s) are already "
                f"open from earlier runs. Close them (or restart Fakturama and "
                f"choose not to save) so the automation cannot fill one Order "
                f"and verify another",
            )
        click(_toolbar_button(app, "Create: New Order"), app)
        return cls(app, _editor_pane(app, cls.NEW_EDITOR_TITLE))

    def activate(self) -> None:
        self.pane = _activate_editor(self.app, self.tab_title, self.NEW_EDITOR_TITLE)

    def read_no(self) -> str:
        self.activate()
        return read_text(fields.field(self.pane, "No."))

    def read_date(self) -> str:
        self.activate()
        return (read_text(fields.field(self.pane, "Date")) or "").strip()

    def set_date(self, iso_date: str) -> None:
        self.activate()
        set_text(fields.field(self.pane, "Date"), iso_date, read_back=False, app=self.app)

    def set_cust_ref(self, value: str) -> None:
        self.activate()
        set_text(fields.field(self.pane, "Cust.Ref."), value, app=self.app)

    PRICE_MODES = ("Net", "Gross")
    VAT_MODES = ("With VAT", "Without VAT")

    def _combo_holding(self, allowed: tuple[str, ...]) -> auto.Control:
        """The Order editor's combo whose current value is one of `allowed`."""
        for ctrl, _ in auto.WalkControl(self.pane, includeTop=False, maxDepth=32):
            try:
                if ctrl.ControlTypeName != "ComboBoxControl":
                    continue
                if (_combo_value(ctrl) or "").strip() in allowed:
                    return ctrl
            except Exception:
                continue
        raise VerificationError(
            "Order editor combo", f"a combo currently showing one of {allowed}",
            "none found")

    def set_price_mode_net(self) -> None:
        self.activate()
        combo = self._combo_holding(self.PRICE_MODES)
        if not set_combo(combo, "Net", must_exist=True, app=self.app):
            raise VerificationError("document price mode", "Net",
                                    f"combo reads {_combo_value(combo)!r}")

    def set_vat_mode_with_vat(self) -> None:
        """1.7: keep VAT as 'With VAT' (assert rather than assume)."""
        self.activate()
        combo = self._combo_holding(self.VAT_MODES)
        if not set_combo(combo, "With VAT", must_exist=True, app=self.app):
            raise VerificationError("Order VAT mode", "With VAT",
                                    f"combo reads {_combo_value(combo)!r}")

    def open_address_selector(self) -> "AddressSelectDialog":
        self.activate()
        icon = fields.existing_contact_icon(self.pane)
        click(icon, self.app)

        try:
            return AddressSelectDialog.open(self.app, timeout=10)
        except Exception as exc:
            if _tab_exists(self.app, f"*{DebtorEditor.NEW_EDITOR_TITLE}")                     or _tab_exists(self.app, DebtorEditor.NEW_EDITOR_TITLE):
                raise VerificationError(
                    "Addresses existing-contact icon",
                    f"the {AddressSelectDialog.TITLE!r} dialog",
                    "a New Debtor editor opened instead -- the lower green '+' was clicked. "
                    "Refusing to continue so no duplicate Debtor is created.") from exc
            raise

    def confirm_addresses_populated(self, expect: tuple[str, ...] = ()) -> bool:
        self.activate()
        if not exists(self.pane, auto.TabControl, timeout=3, Name="Invoice address"):
            return False
        if not expect:
            return True

        wanted = [v.strip() for v in expect if v and v.strip()]
        if not wanted:
            return True

        def _shows_everything() -> bool:
            tab = find(self.pane, auto.TabControl, timeout=3, Name="Invoice address")
            text = " ".join(
                ln.text for ln in grid_ocr.ocr_lines(
                    grid_ocr.capture(tab, app=self.app).resize(
                        (tab.BoundingRectangle.width() * 2,
                         tab.BoundingRectangle.height() * 2)), 2)
            ).casefold()
            return all(v.casefold() in text for v in wanted)

        try:
            wait_until(_shows_everything,
                       f"Order address to show {wanted}", timeout=8, interval=0.5)
            return True
        except Exception:
            return False

    ITEM_ICON_COUNT = 4
    PRODUCT_SELECT_INDEX = 0

    def open_product_selector(self, attempts: int = 3) -> "ProductSelectDialog":
        last: Optional[Exception] = None
        for _ in range(attempts):
            self.activate()
            icons = fields.icon_group(self.pane, "Items", self.ITEM_ICON_COUNT)
            click(icons[self.PRODUCT_SELECT_INDEX], self.app)
            try:
                return ProductSelectDialog.open(self.app, timeout=8)
            except Exception as exc:
                last = exc
                if _tab_exists(self.app, f"*{ProductEditor.NEW_EDITOR_TITLE}"):
                    raise VerificationError(
                        "Items product-selection icon",
                        f"the {ProductSelectDialog.TITLE!r} dialog",
                        "a New product editor opened instead -- the green '+' was "
                        "clicked. Refusing to continue so no blank Product is "
                        "created.") from exc
        raise VerificationError(
            "Items product-selection icon",
            f"the {ProductSelectDialog.TITLE!r} dialog",
            f"it did not open after {attempts} attempts ({last})")

    def items_area(self) -> auto.Control:
        """The Pane holding the Items table: the sibling immediately to the
        right of the 'Items' label/icon strip, sharing its horizontal band."""
        self.activate()
        lbl = find(self.pane, auto.TextControl, Name="Items")
        strip = lbl.GetParentControl()
        band = strip.BoundingRectangle

        siblings = []
        for child in strip.GetParentControl().GetChildren():
            try:
                if child.ControlTypeName != "PaneControl":
                    continue
                r = child.BoundingRectangle
                # To the right of the icon strip, overlapping it vertically.
                if r.left >= band.right and r.top < band.bottom and r.bottom > band.top:
                    siblings.append((r.left, child))
            except Exception:
                continue

        if not siblings:
            raise VerificationError(
                "Items table",
                "a Pane to the right of the Items icon strip",
                "none found -- the Order editor's layout is not the expected "
                "one, and reading the wrong pane would type item quantities "
                "into the totals panel")

        siblings.sort(key=lambda pair: pair[0])
        return siblings[0][1]

    def _scroll_items(self, button_name: str, clicks: int = 1) -> bool:
        try:
            bar = find(self.items_area(), auto.ScrollBarControl, timeout=2,
                       Name="Vertical")
            button = find(bar, auto.ButtonControl, timeout=2, Name=button_name)
        except Exception:
            return False
        self.app.ensure_visible()
        for _ in range(clicks):
            r = button.BoundingRectangle
            auto.Click((r.left + r.right) // 2, (r.top + r.bottom) // 2, waitTime=0.1)
        return True

    ITEM_HEADERS = ["Pos.", "Qty.", "Item No.", "Picture", "Name",
                    "Description", "VAT", "U.Price", "Discount", "Price"]

    def find_item_row(self, sku: str, rows: Optional[list[dict]] = None) -> Optional[dict]:
        from ..extract import normalize as _N

        def _norm(text: str) -> str:
            fixed, _ = _N.code(text or "")
            return (fixed or "").replace(" ", "")

        want = _norm(sku)
        if not want:
            return None
        for row in (rows if rows is not None else self.items_view(sku)[1]):
            for key, value in row.items():
                if key.startswith("_"):
                    continue
                if want in _norm(str(value)):
                    return row
        return None

    def _form_scrollbar(self) -> Optional[auto.Control]:
        edge = self.pane.BoundingRectangle
        best = None
        for ctrl, _ in auto.WalkControl(self.pane, includeTop=False, maxDepth=32):
            try:
                if ctrl.ControlTypeName != "ScrollBarControl" or ctrl.Name != "Vertical":
                    continue
                r = ctrl.BoundingRectangle
                if (r.right < edge.right - _SCROLLBAR_EDGE_TOLERANCE_PX
                        or r.height() < _SCROLLBAR_MIN_HEIGHT_PX):
                    continue
                if best is None or r.height() > best.BoundingRectangle.height():
                    best = ctrl
            except Exception:
                continue
        return best

    def _scroll_form(self, button_name: str, times: int = 3) -> bool:
        """Nudge the Order form with its scrollbar's own Line up/down button."""
        bar = self._form_scrollbar()
        if bar is None:
            return False
        try:
            button = find(bar, auto.ButtonControl, timeout=2, Name=button_name)
        except Exception:
            return False
        for _ in range(times):
            click(button, self.app)
        return True

    ITEMS_END_LABELS = ("Remarks",)

    def items_view(self, sku: str = "", max_scrolls: int = 6):
        self.activate()
        rows: list[dict] = []
        centers: dict[str, float] = {}
        origin = (0, 0)

        def read_here() -> set:
            nonlocal rows, centers, origin
            rect = self.pane.BoundingRectangle
            img = grid_ocr.capture(self.pane, app=self.app)
            top, bottom = grid_ocr.find_band(img, self.ITEM_HEADERS,
                                             self.ITEMS_END_LABELS)
            band = img.crop((0, top, img.width, bottom))
            rows, centers = grid_ocr.read_rows_and_columns(band, self.ITEM_HEADERS)
            origin = (rect.left, rect.top + top)
            self._last_items_read = {
                "pane_rect": (rect.left, rect.top, rect.right, rect.bottom),
                "capture_size": img.size,
                "band": (top, bottom),
                "columns": sorted(centers),
                "rows": [{k: v for k, v in r.items() if not k.startswith("_")}
                         for r in rows],
            }
            self._last_items_img, self._last_items_band = img, band
            return {self._row_key(r) for r in rows}

        def found() -> bool:
            return not sku or self.find_item_row(sku, rows) is not None

        for _ in range(2):
            read_here()
            if found():
                return origin, rows, centers

        for direction, limit in (("Line down", max_scrolls),
                                 ("Line up", max_scrolls * 2)):
            previous: Optional[set] = None
            for _ in range(limit):
                if not self._scroll_items(direction):
                    if not self._scroll_form(direction):
                        break
                keys = read_here()
                if found():
                    return origin, rows, centers
                if keys == previous:
                    break           # the table did not move: end of travel
                previous = keys

        return origin, rows, centers

    def set_current_line(self, qty: Decimal, unit_net: Decimal,
                         discount_pct: Decimal, sku: str = "") -> None:
        origin, rows, centers = self.items_view(sku)

        if not rows:
            raise VerificationError(
                "complete item line", "at least one row in the Items table",
                "the Items table read back empty")

        target = self.find_item_row(sku, rows) if sku else None

        if target is None:
            # Never fall back onto the totals strip that sits under the grid.
            data_rows = [r for r in rows
                         if "total" not in " ".join(
                             str(v) for k, v in r.items()
                             if not k.startswith("_")).casefold()]
            target = (data_rows or rows)[-1]

        for header, value in (("Qty.", qty),
                              ("U.Price", unit_net),
                              ("Discount", discount_pct)):
            if not grid_ocr.edit_cell(origin, target, centers, header, value, self.app):
                raise VerificationError(
                    f"item line {header}", str(value),
                    f"could not reach that cell (columns found: {sorted(centers)})")

    # layout
    _MAXIMIZE_KEYS = "{Ctrl}m"

    def _pane_height(self) -> int:
        try:
            return self.pane.BoundingRectangle.height()
        except Exception:
            return 0

    def _refresh_pane(self) -> None:
        # Re-resolve `pane` after a layout change; its old rect goes stale.
        try:
            self.pane = _activate_editor(self.app, self.tab_title,
                                         self.NEW_EDITOR_TITLE)
        except Exception:
            pass

    def _toggle_maximize(self, want_taller: bool) -> bool:
        # Ctrl+M the editor; True only when the pane really changed size.
        before = self._pane_height()
        try:
            self.app.ensure_visible()
            self.app.window.SendKeys(self._MAXIMIZE_KEYS, waitTime=0.3)
            wait_until(
                lambda: (self._refresh_pane() or True) and (
                    self._pane_height() > before if want_taller
                    else self._pane_height() < before),
                "editor part to change size after Ctrl+M",
                timeout=4, interval=0.25)
            return True
        except Exception:
            return False

    # diagnostics
    _last_items_read: Optional[dict] = None
    _last_items_img = None
    _last_items_band = None

    def dump_last_items_capture(self, out_dir, name: str) -> Optional[dict]:
        # Save the exact pane image and band the last Items read worked from.
        info = self._last_items_read
        if info is None:
            return None
        try:
            from pathlib import Path
            d = Path(out_dir)
            d.mkdir(parents=True, exist_ok=True)
            if self._last_items_img is not None:
                self._last_items_img.save(d / f"{name}-pane.png")
            if self._last_items_band is not None:
                self._last_items_band.save(d / f"{name}-band.png")
        except Exception:
            pass
        return info

    def _row_key(self, row: dict) -> str:
        return "|".join(str(row.get(h, "")).strip() for h in self.ITEM_HEADERS)

    def _collect_item_rows(self, max_scrolls: int) -> list[dict]:
        # Read the Items table at each scroll position and union the results.
        self.activate()
        seen: set[str] = set()
        out: list[dict] = []
        nudges: list[Optional[str]] = [None]
        nudges += ["Line down"] * max_scrolls

        for nudge in nudges:
            if nudge is not None and not self._scroll_items(nudge):
                break
            img = grid_ocr.capture(self.pane, app=self.app)
            top, bottom = grid_ocr.find_band(img, self.ITEM_HEADERS,
                                             self.ITEMS_END_LABELS)
            band = img.crop((0, top, img.width, bottom))
            rows, _ = grid_ocr.read_rows_and_columns(band, self.ITEM_HEADERS)

            fresh = 0
            for row in rows:
                key = self._row_key(row)
                if key.strip("|") and key not in seen:
                    seen.add(key)
                    out.append(row)
                    fresh += 1
            # A scroll that reveals nothing new means the bottom is reached.
            if nudge is not None and fresh == 0:
                break
        return out

    def read_all_item_rows(self, max_scrolls: int = 6) -> list[dict]:
        rows = self._collect_item_rows(max_scrolls)
        if rows:
            return rows
        # Nothing at all -- the table may be squeezed flat; give it the window.
        if not self._toggle_maximize(want_taller=True):
            return rows
        try:
            return self._collect_item_rows(max_scrolls)
        finally:
            self._toggle_maximize(want_taller=False)
            self._refresh_pane()

    def read_item_rows(self, sku: str = "") -> list[dict]:
        return self.items_view(sku)[1]

    def totals(self) -> tuple[Optional[str], Optional[str], Optional[str]]:
        self.activate()

        def rd(label):
            try:
                return read_text(fields.field(self.pane, label, timeout=2))
            except Exception:
                return None
        return rd("Total Net"), rd("VAT"), rd("Total")

    NO_SHIPPING = "Free of shipping costs"

    def order_level_settings(self) -> dict[str, str]:
        self.activate()
        out: dict[str, str] = {}
        for label in ("Discount", "Shipping"):
            try:
                out[label] = (read_text(fields.field(self.pane, label, timeout=3))
                              or "").strip()
            except Exception:
                out[label] = ""
        return out

    def set_order_discount_zero(self) -> None:
        """Put the ORDER-level discount back to 0% (4.2)."""
        self.activate()
        set_text(fields.field(self.pane, "Discount"), "0", app=self.app,
                 match=controls.numeric_match)

    def _is_dirty(self) -> bool:
        titles = {f"*{self.NEW_EDITOR_TITLE}"}
        if self.tab_title:
            titles.add(f"*{self.tab_title}")
        return any(_tab_exists(self.app, t) for t in titles)

    def _click_save(self) -> None:
        self.activate()
        try:
            self.pane.SetFocus()
        except Exception:
            pass
        button = _toolbar_button(self.app, "Save the current contents")
        try:
            wait_until(lambda: button.IsEnabled, "Save button to become enabled",
                       timeout=5)
        except Exception as exc:
            raise VerificationError(
                f"save {self.NEW_EDITOR_TITLE}",
                "an enabled toolbar Save control",
                "Save stayed disabled, so Fakturama does not consider this "
                "editor saveable (nothing to save, or it is not the active part)",
            ) from exc
        click(button, self.app)
        _ack_blocking_popups(self.app)

    def save(self) -> str:
        self.activate()
        number = read_text(fields.field(self.pane, "No.")).strip()

        def _settled() -> bool:
            _ack_blocking_popups(self.app, timeout=0.2)
            return not self._is_dirty()

        self._click_save()
        try:
            wait_until(_settled, f"{self.NEW_EDITOR_TITLE} to lose its unsaved marker",
                       timeout=15)
        except Exception:
            self._click_save()          # only reached while still dirty
            try:
                wait_until(_settled,
                           f"{self.NEW_EDITOR_TITLE} to lose its unsaved marker "
                           f"(second attempt)", timeout=15)
            except Exception as exc:
                blocker = _visible_modal_title(self.app)
                raise VerificationError(
                    f"save {self.NEW_EDITOR_TITLE}",
                    "the editor to lose its unsaved '*' marker",
                    (f"still unsaved after two Save clicks; a {blocker!r} dialog "
                     f"is blocking the save"
                     if blocker else
                     "still unsaved after two Save clicks, with no dialog on "
                     "screen and the Save control enabled -- Fakturama is "
                     "refusing to persist this record rather than losing the click"),
                ) from exc

        if number and _tab_exists(self.app, number):
            self.tab_title = number
        return number

    def create_invoice(self) -> "InvoiceEditor":
        self.activate()
        grp = find(self.pane, auto.GroupControl, Name="Create a follow-up document")
        click(find(grp, auto.ButtonControl, Name="Invoice"), self.app)
        return InvoiceEditor.open(self.app)


# Address dlg

class SelectorDialog:
    HEADERS: list[str] = []
    TITLE = ""

    def __init__(self, app: App, dialog: auto.WindowControl):
        self.app = app
        self.dialog = dialog
        self._last_rows: Optional[list[dict]] = None
        self._searched = False
        self.self_confirmed = False

    @classmethod
    def open(cls, app: App, timeout: float = 10.0):
        def _find():
            d = auto.WindowControl(searchFromControl=app.window, searchDepth=6, Name=cls.TITLE)
            return d if d.Exists(0, 0) else None
        return cls(app, wait_until(_find, f"dialog {cls.TITLE!r}", timeout=timeout))

    def search(self, text: str) -> bool:
        if self._searched:
            raise VerificationError(
                f"search {self.TITLE!r}",
                "one search per dialog",
                "this dialog has already been filtered. Re-filtering can make "
                "it confirm its first row and close by itself; close it and "
                "open a new one instead",
            )
        self._searched = True
        edit = fields.field(self.dialog, "Search:")
        type_into_search_box(edit, text, app=self.app)
        self.self_confirmed = not self.is_open()
        return not self.self_confirmed

    def grid(self) -> auto.Control:
        return _grid_of(self.dialog)

    def rows(self) -> list[dict]:
        self._last_rows = grid_ocr.read_grid(self.grid(), self.HEADERS, app=self.app)
        return self._last_rows

    def rows_stable(self, timeout: float = 10.0) -> list[dict]:
        self._last_rows = _wait_rows_stable(self.rows, timeout=timeout)
        return self._last_rows

    def select_row(self, row: dict) -> None:
        grid_ocr.click_row(self.grid(), row, self.app, rows=self._last_rows)

    def is_open(self) -> bool:
        try:
            return bool(self.dialog.Exists(0.3, 0.2))
        except Exception:
            return False

    def ok(self, attempts: int = 3) -> None:
        """Confirm the selected row and verify that the dialog closes."""

        if not self.is_open():
            return

        last_error = None

        for attempt in range(attempts):
            try:
                self.app.ensure_visible()

                # Re-acquire the live dialog/button on every attempt.
                btn = find(self.dialog, auto.ButtonControl, timeout=3, Name="OK")

                # Make sure the button/dialog has focus.
                try:
                    btn.SetFocus()
                except Exception:
                    pass

                if attempt == 0:
                    # SWT dialogs generally respond very reliably to Enter.
                    auto.SendKeys("{ENTER}")
                elif attempt == 1:
                    # Space activates the currently focused SWT button.
                    auto.SendKeys("{SPACE}")
                else:
                    r = btn.BoundingRectangle
                    auto.Click(((r.left + r.right) // 2, (r.top + r.bottom) // 2))

                wait_until(lambda: not self.is_open(),
                           f"{self.TITLE!r} to close after OK",
                           timeout=4, interval=0.2)
                return

            except Exception as exc:
                last_error = exc

                # It may have closed even if the verification itself raced.
                if not self.is_open():
                    return

                time.sleep(0.5)

        raise VerificationError(
            f"confirm {self.TITLE!r}",
            f"the {self.TITLE!r} dialog to close",
            f"dialog remained open after {attempts} attempts; "
            f"last error: {last_error}",
        )

    def cancel(self) -> None:
        if not self.is_open():
            return
        click(find(self.dialog, auto.ButtonControl, Name="Cancel"), self.app)
        try:
            wait_until(lambda: not self.is_open(),
                       f"{self.TITLE!r} to close after Cancel", timeout=5, interval=0.2)
        except Exception:
            pass


class AddressSelectDialog(SelectorDialog):
    """Columns: No. / First Name / Name / Company / ZIP / City."""

    HEADERS = ["No.", "First Name", "Name", "Company", "ZIP", "City"]
    TITLE = "Select the address"


# Debtor

class DebtorEditor:
    """The Debtor editor (Addresses + Miscellaneous tabs). The Payment Method
    field lives inside Miscellaneous; this Fakturama version has no separate
    "Payment" tab."""

    NEW_EDITOR_TITLE = "New Debtor"

    def __init__(self, app: App, pane: auto.PaneControl):
        self.app = app
        self.pane = pane
        self.tab_title = self.NEW_EDITOR_TITLE

    def activate(self) -> None:
        self.pane = _activate_editor(self.app, self.tab_title, self.NEW_EDITOR_TITLE)

    @classmethod
    def open_new(cls, app: App) -> "DebtorEditor":
        stale = _tabs_named(app, f"*{cls.NEW_EDITOR_TITLE}")
        if stale:
            raise AmbiguousEditorTab(
                "open New Debtor",
                f"no leftover '*{cls.NEW_EDITOR_TITLE}' tabs before starting",
                f"{len(stale)} unsaved '{cls.NEW_EDITOR_TITLE}' tab(s) are already "
                f"open from earlier runs. Close them (or restart Fakturama and "
                f"choose not to save)",
            )
        click(_nav_label(app, "New Contact"), app)
        return cls(app, _editor_pane(app, "New Debtor"))

    def set_company(self, company: str) -> None:
        set_text(fields.field(self.pane, "Company"), company, app=self.app)

    def set_names(self, first: str, last: str) -> None:
        fn, ln = fields.dual_field(self.pane, "First Name Last Name")
        set_text(fn, first, app=self.app)
        set_text(ln, last, app=self.app)

    def fill_main_address(self, street: str, zip_: str, city: str, country: str, email: str, phone: str) -> None:
        set_text(fields.field(self.pane, "Street"), street, app=self.app)
        z, c = fields.dual_field(self.pane, "ZIP - City")
        set_text(z, zip_, app=self.app)
        set_text(c, city, app=self.app)
        set_combo(fields.field(self.pane, "Country"), country, app=self.app)
        if email:
            set_text(fields.field(self.pane, "E-Mail"), email, app=self.app)
        if phone:
            set_text(fields.field(self.pane, "Telephone"), phone, app=self.app)

    ADDRESS_ROLE_NAMES = ("Invoice address", "Delivery address")

    def _role_checkbox(self, name: str, timeout: float = 1.0) -> Optional[auto.Control]:
        """The role checkbox from the popup, searched from the APP WINDOW
        (not the editor pane -- see ADDRESS_ROLE_NAMES)."""
        c = auto.CheckBoxControl(searchFromControl=self.app.window, searchDepth=40, Name=name)
        return c if c.Exists(timeout, 0.2) else None

    def _role_popup_open(self, timeout: float = 0.4) -> bool:
        return self._role_checkbox(self.ADDRESS_ROLE_NAMES[0], timeout=timeout) is not None

    def _address_type_expander(self) -> auto.Control:
        label = find(self.pane, auto.TextControl, timeout=5, Name="address type")
        band = label.BoundingRectangle

        candidates = []
        for ctrl, _ in auto.WalkControl(self.pane, includeTop=False, maxDepth=32):
            try:
                if ctrl.ControlTypeName != "ButtonControl":
                    continue
                r = ctrl.BoundingRectangle
                if r.top < band.bottom and r.bottom > band.top and r.left >= band.right:
                    candidates.append((r.left, ctrl))
            except Exception:
                continue

        if not candidates:
            raise VerificationError(
                "address-type expander",
                "a Button on the 'address type' row",
                "none found -- cannot open the Invoice/Delivery role popup",
            )
        candidates.sort(key=lambda pair: pair[0])
        return candidates[0][1]

    def open_address_role_popup(self) -> None:
        """Press '>' and wait for the role popup. Idempotent."""
        if self._role_popup_open():
            return
        click(self._address_type_expander(), self.app)
        try:
            wait_until(self._role_popup_open,
                       "address-role popup with Invoice/Delivery checkboxes", timeout=8)
        except Exception as exc:
            raise VerificationError(
                "address-type expander",
                "the Invoice/Delivery address role popup",
                "pressed '>' but the popup did not appear",
            ) from exc

    def close_address_role_popup(self) -> None:
        if not self._role_popup_open():
            return
        self.app.ensure_visible()
        self.app.window.SendKeys("{Esc}", waitTime=0.1)
        try:
            wait_until(lambda: not self._role_popup_open(timeout=0.3),
                       "address-role popup to close", timeout=5)
        except Exception:
            try:
                click(self._address_type_expander(), self.app)
            except Exception:
                pass

    def set_address_role_invoice(self, also_delivery: bool) -> None:
        self.open_address_role_popup()
        try:
            for name, wanted in (("Invoice address", True),
                                 ("Delivery address", also_delivery)):
                box = self._role_checkbox(name, timeout=3)
                if box is None:
                    raise VerificationError(
                        f"{name} checkbox", "present in the address-role popup", "not found")
                if not controls.set_checkbox(box, wanted, app=self.app):
                    raise VerificationError(
                        f"{name} checkbox",
                        "checked" if wanted else "unchecked",
                        f"state did not settle (read back "
                        f"{'checked' if controls.checkbox_checked(box) else 'unchecked'})",
                    )
        finally:
            self.close_address_role_popup()

    def goto_miscellaneous(self) -> None:
        if controls.exists_by_name(self.pane, "Payment", timeout=0.4):
            return
        item = find(self.pane, auto.TabItemControl, Name="Miscellaneous")
        click(item, self.app)
        wait_until(lambda: controls.exists_by_name(self.pane, "Payment", timeout=0.4),
                   "Miscellaneous tab content (Payment combo)", timeout=8)

    def set_alias(self, alias: str) -> None:
        set_text(fields.field(self.pane, "Alias name"), alias, app=self.app)

    def set_discount_zero(self) -> None:
        set_text(fields.field(self.pane, "Discount"), "0", app=self.app,
                 match=controls.numeric_match)

    def set_net_or_gross_net(self) -> None:
        set_combo(fields.field(self.pane, "Net or Gross"), "Net", app=self.app)

    def payment_method_combo(self) -> auto.Control:
        return fields.field(self.pane, "Payment")

    def set_payment_method(self, method: str) -> bool:
        """Returns True if the method was present in the dropdown."""
        return set_combo(self.payment_method_combo(), method, must_exist=True, app=self.app)

    DUPLICATE_DIALOG = "Duplicate Contact"

    def save(self) -> str:
        company = read_text(fields.field(self.pane, "Company")).strip()

        if not company:
            raise VerificationError(
                "Debtor Company before save",
                "the extracted company name",
                "the Company field is empty -- refusing to save a Debtor "
                "with no company",
            )

        try:
            fn, ln = fields.dual_field(self.pane, "First Name Last Name")
            first, last = read_text(fn), read_text(ln)
        except Exception:
            first = last = ""
        click(_toolbar_button(self.app, "Save the current contents"), self.app)

        if controls.dismiss_modal(self.app.window, self.DUPLICATE_DIALOG, "OK", timeout=3):
            raise DuplicateContact(company)

        try:
            wait_until(lambda: not _tab_exists(self.app, f"*{self.NEW_EDITOR_TITLE}"),
                       "Debtor editor to lose its unsaved marker", timeout=15)
        except Exception as exc:
            blocker = _visible_modal_title(self.app)
            raise VerificationError(
                "save Debtor",
                "the editor to lose its unsaved '*' marker",
                (f"still unsaved; a {blocker!r} dialog is blocking the save"
                 if blocker else
                 "still unsaved and no dialog was found -- the Save toolbar "
                 "click may not have registered, or a required field is "
                 "rejected"),
            ) from exc

        self.tab_title = (
            _saved_editor_title(self.app,
                                preferred=(f"{first} {last}".strip(), company))
            or _any_open_editor_title(self.app, exclude=(self.NEW_EDITOR_TITLE,))
            or company
        )
        try:
            self.pane = _activate_editor(self.app, self.tab_title, company)
        except Exception:
            pass
        return company

    def discard(self) -> None:
        """Close this unsaved editor, telling Fakturama not to persist it, so
        a rejected Debtor does not linger as a dirty '*New Debtor' tab."""
        discard_editor(self.app, self.NEW_EDITOR_TITLE)


# Product

class ProductSelectDialog(SelectorDialog):
    """Columns: Item No. / Name / Description / Stock / Price / VAT."""

    HEADERS = ["Item No.", "Name", "Description", "Stock", "Price", "VAT"]
    TITLE = "Select a product"

    def rows(self) -> list[dict]:
        rows = super().rows()
        for r in rows:
            if "Item No." not in r and "Item" in r:
                r["Item No."] = r.pop("Item")
        return rows


class ProductEditor:
    """The Product editor (3.8-3.10)."""

    def __init__(self, app: App, pane: auto.PaneControl):
        self.app = app
        self.pane = pane

    NEW_EDITOR_TITLE = "New product"

    @classmethod
    def open_new(cls, app: App) -> "ProductEditor":
        """3.7: open New product (only after the required VAT exists, so
        the rate is offered in the VAT dropdown -- the caller's job)."""
        stale = _tabs_named(app, f"*{cls.NEW_EDITOR_TITLE}")
        if stale:
            raise AmbiguousEditorTab(
                "open New product",
                f"no leftover '*{cls.NEW_EDITOR_TITLE}' tabs before starting",
                f"{len(stale)} unsaved '{cls.NEW_EDITOR_TITLE}' tab(s) are already "
                f"open from earlier runs. Close them so the automation cannot "
                f"fill one Product and save another",
            )
        click(_toolbar_button(app, "Create a new product"), app)
        return cls(app, _editor_pane(app, cls.NEW_EDITOR_TITLE))

    def activate(self) -> None:
        self.pane = _activate_editor(self.app, self.NEW_EDITOR_TITLE)

    def fill(self, sku: str, description: str, price_gross: Decimal, vat_name: str) -> None:
        """3.8-3.10."""
        set_text(fields.field(self.pane, "Item Number"), sku, app=self.app)
        set_text(fields.field(self.pane, "Name"), description, app=self.app)
        set_text(fields.field(self.pane, "Description"), description, app=self.app,
                 commit_key="")
        price_field = _first_existing(self.pane, ["Price (gross)", "Price"])
        set_text(price_field, str(price_gross), app=self.app, match=controls.numeric_match)
        cost_field = _first_existing(self.pane, ["cost price (net)", "cost price", "Cost price (net)"])
        set_text(cost_field, "0.00", app=self.app, match=controls.numeric_match)
        vat_combo = _first_existing(self.pane, ["VAT"])
        if vat_combo is None:
            raise VerificationError("Product VAT", f"a VAT combo offering {vat_name!r}",
                                    "no VAT combo found in the Product editor")
        if not set_combo(vat_combo, vat_name, must_exist=True, app=self.app):
            raise VerificationError(
                "Product VAT", vat_name,
                f"not offered in the dropdown (it holds "
                f"{combo_entries(vat_combo, self.app)}); combo reads "
                f"{_combo_value(vat_combo)!r}")
        set_text(fields.field(self.pane, "Stock"), "0.00", app=self.app,
                 match=controls.numeric_match)

    def read_back(self, title: str = "") -> dict[str, str]:
        """What the editor currently holds, for post-save verification (3.11)."""
        self.pane = _activate_editor(self.app, title or self.NEW_EDITOR_TITLE)
        out: dict[str, str] = {}
        for label in ("Item Number", "Name"):
            try:
                out[label] = read_text(fields.field(self.pane, label, timeout=2)).strip()
            except Exception:
                out[label] = ""
        for key, labels in (("Price", ["Price (gross)", "Price"]),
                            ("VAT", ["VAT"])):
            ctrl = _first_existing(self.pane, labels)
            out[key] = (read_text(ctrl) or "").strip() if ctrl is not None else ""
        return out

    def save(self, sku: str, name: str = "", vat_name: str = "",
             price_gross: Optional[Decimal] = None) -> dict[str, str]:
        click(_toolbar_button(self.app, "Save the current contents"), self.app)
        _ack_blocking_popups(self.app)
        try:
            wait_until(lambda: not _tab_exists(self.app, f"*{self.NEW_EDITOR_TITLE}"),
                       "Product editor to lose its unsaved marker", timeout=15)
        except Exception as exc:
            blocker = _visible_modal_title(self.app)
            raise VerificationError(
                "save Product",
                "the editor to lose its unsaved '*' marker",
                (f"still unsaved; a {blocker!r} dialog is blocking the save"
                 if blocker else "still unsaved after clicking Save"),
            ) from exc

        title = _saved_editor_title(self.app, preferred=(name, sku)) or ""
        saved = self.read_back(title)

        if saved.get("Item Number") != sku:
            raise VerificationError("saved Product Item Number", sku,
                                    f"{saved.get('Item Number')!r}")
        if vat_name and saved.get("VAT") != vat_name:
            raise VerificationError(
                "saved Product VAT", vat_name,
                f"{saved.get('VAT')!r} -- the rate did not persist, so every "
                f"Order line using this Product would carry the wrong tax")
        if price_gross is not None and not controls.numeric_match(
                str(price_gross), saved.get("Price", "")):
            raise VerificationError("saved Product Price (gross)", str(price_gross),
                                    f"{saved.get('Price')!r}")
        return saved


# VAT

class VatEditor:
    """The VAT editor (3.4-3.6). Columns: Standard / Name / Description / Value."""

    HEADERS = ["Standard", "Name", "Description", "Value"]

    def __init__(self, app: App):
        self.app = app

    def open_list(self) -> None:
        _data_tab(self.app, "VATs")

    def grid(self) -> auto.Control:
        tab = _data_browser_tabcontrol(self.app)
        return _grid_of(tab)

    def rows(self) -> list[dict]:
        return grid_ocr.read_grid(self.grid(), self.HEADERS, app=self.app)

    NEW_EDITOR_TITLE = "New TAX Rate"
    VAT_CODE_LABEL = "VAT code (E-Invoice)"
    STANDARD_RATE = "S (Standard rate)"

    def create(self, name: str, value_pct: Decimal) -> None:
        click(_create_button(self.app, "VATs"), self.app)
        pane = _editor_pane(self.app, self.NEW_EDITOR_TITLE)

        set_text(fields.field(pane, "Name"), name, app=self.app)
        set_text(fields.field(pane, "Description"), name, app=self.app)
        # Reformatted to e.g. '19.00 %' on focus-out -> compare numerically.
        set_text(fields.field(pane, "Value"), str(value_pct), app=self.app,
                 match=controls.numeric_match)

        try:
            combo = fields.field(pane, self.VAT_CODE_LABEL, timeout=2)
        except Exception:
            combo = None
        if combo is not None:
            current = (read_text(combo) or "").strip()
            if current and not current.startswith("S"):
                if not select_combo_by_walk(combo, self.STANDARD_RATE, app=self.app):
                    raise VerificationError(self.VAT_CODE_LABEL, self.STANDARD_RATE, current)
        # 'Standard' / 'Set as standard' is deliberately left untouched (3.6).

        click(_toolbar_button(self.app, "Save the current contents"), self.app)
        _ack_blocking_popups(self.app)
        wait_until(lambda: (lambda p: p if p.Exists(0, 0) else None)(
            auto.PaneControl(searchFromControl=self.app.window, searchDepth=30, Name=name)),
            f"VAT editor retitled to {name!r}", timeout=15)


# Payment term

class PaymentMethodEditor:
    """The terms-of-payment editor (2.10.1-2.10.6)."""

    def __init__(self, app: App):
        self.app = app

    def open_list(self) -> None:
        _data_tab(self.app, "terms of payment")

    def grid(self) -> auto.Control:
        tab = _data_browser_tabcontrol(self.app)
        return _grid_of(tab)

    HEADERS = ["Standard", "Name", "Description", "Discount"]

    def rows(self) -> list[dict]:
        return grid_ocr.read_grid(self.grid(), self.HEADERS, app=self.app)

    NEW_EDITOR_TITLE = "New Term of Payment"
    PAYMENT_CODE_LABELS = ("!editorPaymentPaymentcode!", "payment-code", "Payment code")

    def create(self, method: str, payment_code: str) -> None:
        click(_create_button(self.app, "terms of payment"), self.app)
        pane = _editor_pane(self.app, self.NEW_EDITOR_TITLE)

        set_text(fields.field(pane, "Name"), method, app=self.app)
        set_text(fields.field(pane, "Description"), method, app=self.app)
        # Account is left blank (2.10.3).

        combo = _first_existing(pane, list(self.PAYMENT_CODE_LABELS))
        if combo is None:
            raise VerificationError("payment-code dropdown", "a combo labelled one of "
                                    f"{self.PAYMENT_CODE_LABELS}", "not found")
        if not select_combo_by_walk(combo, payment_code, app=self.app):
            raise VerificationError("payment code", payment_code,
                                    "could not be selected in the dropdown")

        for label in ("Cash discount", "Discount Days", "Net Days"):
            try:
                set_text(fields.field(pane, label), "0", app=self.app,
                         match=controls.numeric_match)
            except Exception:
                pass

        click(_toolbar_button(self.app, "Save the current contents"), self.app)
        _ack_blocking_popups(self.app)
        wait_until(lambda: (lambda p: p if p.Exists(0, 0) else None)(
            auto.PaneControl(searchFromControl=self.app.window, searchDepth=30, Name=method)),
            f"payment term editor retitled to {method!r}", timeout=15)


# Documents

class DocumentsView:
    HEADERS = [
        "Document",
        "Date",
        "Name",
        "Cust.Ref.",
        "State",
        "Total",
        "Printed",
    ]

    def __init__(self, app: App):
        self.app = app
        self.tab: Optional[auto.Control] = None

    def open(self) -> None:
        self.tab = _data_tab(
            self.app,
            "Documents",
            timeout=10.0,
            attempts=3,
        )

        # Final verification.
        if not _tab_is_selected(self.tab):
            raise VerificationError(
                "Documents Data Browser",
                "Documents tab selected",
                "Documents tab lookup succeeded but the tab is not selected",
            )

    def grid(self) -> auto.Control:
        self.open()

        return _data_browser_tabcontrol(self.app, timeout=10.0)

    def _read_page(self, grid: auto.Control) -> list[dict]:
        img = grid_ocr.capture(grid, app=self.app)
        top, bottom = grid_ocr.find_band(img, self.HEADERS, stop_labels=())
        return grid_ocr.read_rows(img.crop((0, top, img.width, bottom)), self.HEADERS)

    def _scroll_sideways(self, grid: auto.Control, button_name: str,
                         clicks: int = 1) -> bool:
        try:
            bar = find(grid, auto.ScrollBarControl, timeout=2, Name="Horizontal")
            button = find(bar, auto.ButtonControl, timeout=2, Name=button_name)
        except Exception:
            return False
        self.app.ensure_visible()
        for _ in range(clicks):
            r = button.BoundingRectangle
            auto.Click((r.left + r.right) // 2, (r.top + r.bottom) // 2, waitTime=0.1)
        return True

    @staticmethod
    def _merge(left: list[dict], right: list[dict]) -> list[dict]:
        out = []
        for index, row in enumerate(left):
            merged = dict(row)
            if index < len(right):
                for key, value in right[index].items():
                    if not key.startswith("_") and key not in merged:
                        merged[key] = value
            out.append(merged)
        return out

    def rows(self) -> list[dict]:
        grid = self.grid()
        merged = self._read_page(grid)
        if not merged:
            return merged

        wanted = ("Cust.Ref.", "State", "Total")
        passes = 0
        for _ in range(8):
            if all(h in merged[0] for h in wanted):
                break
            if not self._scroll_sideways(grid, "Column right"):
                break
            passes += 1
            merged = self._merge(merged, self._read_page(grid))

        if passes:
            self._scroll_sideways(grid, "Column left", clicks=passes + 2)

        return merged

    def search(self, text: str) -> None:
        self.open()
        edit = fields.field(self.grid(), "Search:")
        type_into_search_box(edit, text, app=self.app)

    def rows_stable(self, timeout: float = 10.0) -> list[dict]:
        """Read Documents only after the grid contents stabilize."""

        return _wait_rows_stable(
            self.rows,
            timeout=timeout,
        )

# Invoice

_DATE_TEXT = re.compile(
    r"(?:[A-Za-z]{3,9}\s+\d{1,2},\s*\d{4})|(?:\d{1,2}[./-]\d{1,2}[./-]\d{2,4})"
    r"|(?:\d{4}-\d{2}-\d{2})")


def _looks_like_a_date(text: Optional[str]) -> bool:
    return bool(_DATE_TEXT.search((text or "").strip()))


class InvoiceEditor(OrderEditor):
    NEW_EDITOR_TITLE = "New Invoice"

    @classmethod
    def open(cls, app: App, timeout: float = 15.0) -> "InvoiceEditor":
        """4.7: wait for the linked New Invoice editor to materialise."""
        return cls(app, _editor_pane(app, cls.NEW_EDITOR_TITLE, timeout=timeout))

    def read_cust_ref(self) -> str:
        self.activate()
        return (read_text(fields.field(self.pane, "Cust.Ref.")) or "").strip()

    def vat_mode(self) -> str:
        self.activate()
        try:
            return (_combo_value(self._combo_holding(self.VAT_MODES)) or "").strip()
        except Exception:
            return ""

    PAID_CHECKBOX = "paid"

    def payment_method_combo(self) -> auto.Control:
        combo = _first_existing(self.pane, ["Payment Method", "payment method"])
        if combo is not None:
            return combo

        chk = fields.field(self.pane, self.PAID_CHECKBOX)
        band = chk.BoundingRectangle
        candidates = []
        for ctrl, _ in auto.WalkControl(self.pane, includeTop=False, maxDepth=32):
            try:
                if ctrl.ControlTypeName != "ComboBoxControl":
                    continue
                r = ctrl.BoundingRectangle
                if r.top < band.bottom and r.bottom > band.top and r.left >= band.left:
                    candidates.append((r.left, ctrl))
            except Exception:
                continue
        if not candidates:
            raise VerificationError(
                "Invoice payment method", "a combo on the 'paid' row", "none found")
        candidates.sort(key=lambda pair: pair[0])
        return candidates[0][1]

    def set_payment_method(self, method: str) -> bool:
        """5.2. False when the method is not offered -> manual review."""
        self.activate()
        return set_combo(self.payment_method_combo(), method,
                         must_exist=True, app=self.app)

    def read_payment_method(self) -> str:
        self.activate()
        try:
            return (_combo_value(self.payment_method_combo()) or "").strip()
        except Exception:
            return ""

    def paid_checkbox(self) -> auto.Control:
        return fields.field(self.pane, self.PAID_CHECKBOX)

    def is_paid(self) -> bool:
        self.activate()
        try:
            return controls.checkbox_checked(self.paid_checkbox())
        except Exception:
            return False

    PAY_DATE_LABELS = ("Pay Until", "Pay Date", "Paid at", "at")
    PAY_VALUE_LABELS = ("Value", "Amount")
    TOTALS_LABELS = ("Total Net", "VAT", "Total", "Discount", "Shipping")

    def _paid_row(self) -> tuple[list[tuple[int, auto.Control]],
                                 list[tuple[int, str]]]:
        band = self.paid_checkbox().BoundingRectangle
        totals = {controls.normalize_name(n) for n in self.TOTALS_LABELS}

        found: list[tuple[int, str, auto.Control]] = []
        for ctrl, _ in auto.WalkControl(self.pane, includeTop=False, maxDepth=32):
            try:
                r = ctrl.BoundingRectangle
                if not (r.top < band.bottom and r.bottom > band.top):
                    continue
                if r.left < band.left:
                    continue              # left of the checkbox: another panel
                kind = ctrl.ControlTypeName
                if kind == "EditControl":
                    found.append((r.left, "edit", ctrl))
                elif kind == "TextControl" and (ctrl.Name or "").strip():
                    found.append((r.left, "label", ctrl))
            except Exception:
                continue

        cutoff = min(
            (left for left, kind, ctrl in found
             if kind == "label" and controls.normalize_name(ctrl.Name) in totals),
            default=None)

        edits = [(left, ctrl) for left, kind, ctrl in found
                 if kind == "edit" and (cutoff is None or left < cutoff)]
        labels = [(left, ctrl.Name.strip()) for left, kind, ctrl in found
                  if kind == "label" and (cutoff is None or left < cutoff)]

        edits.sort(key=lambda pair: pair[0])
        labels.sort(key=lambda pair: pair[0])
        return edits, labels

    def _box_after_label(self, names: tuple[str, ...]) -> Optional[auto.Control]:
        """The first editable box to the right of one of these labels."""
        edits, labels = self._paid_row()
        wanted = {controls.normalize_name(n) for n in names}
        for left, text in labels:
            if controls.normalize_name(text) in wanted:
                following = [ctrl for x, ctrl in edits if x > left]
                if following:
                    return following[0]
        return None

    def pay_date_box(self) -> Optional[auto.Control]:
        """The payment-date box: found by its label, else by the box on the
        row whose contents already look like a date."""
        box = self._box_after_label(self.PAY_DATE_LABELS)
        if box is not None:
            return box
        edits, _ = self._paid_row()
        for _left, ctrl in reversed(edits):
            if _looks_like_a_date(read_text(ctrl)):
                return ctrl
        return None

    def pay_value_box(self) -> Optional[auto.Control]:
        box = self._box_after_label(self.PAY_VALUE_LABELS)
        if box is not None:
            return box

        excluded = []
        for candidate in (self.pay_date_box(), self._box_after_label(("Due Days",))):
            if candidate is not None:
                excluded.append(candidate.BoundingRectangle.left)

        edits, _labels = self._paid_row()
        for left, ctrl in reversed(edits):
            if left in excluded:
                continue
            if _looks_like_a_date(read_text(ctrl)):
                continue
            return ctrl
        return None

    def set_paid(self, payment_date: str, value: str) -> dict[str, str]:
        self.activate()
        if not controls.set_checkbox(self.paid_checkbox(), True, app=self.app):
            raise VerificationError("Invoice 'paid'", "checked", "it did not tick")

        date_box = self.pay_date_box()
        if date_box is None:
            _edits, labels = self._paid_row()
            raise VerificationError(
                "Invoice payment date", payment_date,
                f"no date box on the paid row (labels there: {[t for _, t in labels]})")
        set_text(date_box, payment_date, app=self.app, read_back=False)

        value_box = self.pay_value_box()
        if value_box is not None:
            set_text(value_box, value, app=self.app, match=controls.numeric_match)

        return self.read_paid_state()

    def read_paid_state(self) -> dict[str, str]:
        """5.6: the persisted payment method, paid flag, date and Value."""
        self.activate()
        date_box, value_box = self.pay_date_box(), self.pay_value_box()
        return {
            "paid": "yes" if self.is_paid() else "no",
            "method": self.read_payment_method(),
            "date": (read_text(date_box) or "").strip() if date_box is not None else "",
            "value": (read_text(value_box) or "").strip() if value_box is not None else "",
        }


# helpers

def _first_existing(container: auto.Control, labels: list[str]) -> Optional[auto.Control]:
    for label in labels:
        try:
            return fields.field(container, label, timeout=2)
        except Exception:
            continue
    return None


CREATE_BUTTON_TOOLTIPS = {
    "VATs": "Create a new tax rate",
    "terms of payment": "Create a new term of payment",
    "Products": "Create a new product",
    "Debtors": "Create a new debtor",
    "Documents": "Create: Order",
}


def _create_button(app: App, list_name: str, timeout: float = 8.0) -> auto.Control:
    """The '+' control for a Data browser list, found by its tooltip."""
    tooltip = CREATE_BUTTON_TOOLTIPS.get(list_name)
    if tooltip is None:
        raise VerificationError("create button",
                                f"a known list name {list(CREATE_BUTTON_TOOLTIPS)}", list_name)
    return find(app.window, auto.ButtonControl, timeout=timeout, Name=tooltip)


def _combo_value(combo: auto.Control) -> str:
    try:
        return (combo.GetValuePattern().Value or "").strip()
    except Exception:
        return ""


def combo_entries(combo: auto.Control, app: Optional[App] = None,
                  max_items: int = 400) -> list[str]:
    original = _combo_value(combo)
    seen: list[str] = []
    try:
        if app is not None:
            app.ensure_visible()
        combo.SetFocus()
        combo.SendKeys("{Home}", waitTime=0.12)
        for _ in range(max_items):
            current = _combo_value(combo)
            if seen and current == seen[-1]:
                break
            seen.append(current)
            combo.SendKeys("{Down}", waitTime=0.06)
    except Exception:
        pass
    finally:
        if original and _combo_value(combo) != original:
            _walk_to(combo, original, app)
    return seen


def _walk_to(combo: auto.Control, want: str, app: Optional[App] = None,
             max_items: int = 400) -> bool:
    """Home, then Down until the combo reads `want`. Stops at the end of the list."""
    try:
        if app is not None:
            app.ensure_visible()
        combo.SetFocus()
        combo.SendKeys("{Home}", waitTime=0.12)
        previous = None
        for _ in range(max_items):
            current = _combo_value(combo)
            if current == want:
                return True
            if current == previous:
                return False            # end of the list
            previous = current
            combo.SendKeys("{Down}", waitTime=0.06)
    except Exception:
        return False
    return _combo_value(combo) == want


def select_combo_by_walk(combo: auto.Control, value: str, app: Optional[App] = None,
                         max_items: int = 400) -> bool:
    want = value.strip()
    if _combo_value(combo) == want:
        return True

    original = _combo_value(combo)

    # type-ahead: cheap, and correct for long lists
    try:
        if app is not None:
            app.ensure_visible()
        combo.SetFocus()
        combo.SendKeys("{Home}", waitTime=0.1)
        combo.SendKeys(want, waitTime=0.02)
        if _combo_value(combo) == want:
            return True
    except Exception:
        pass

    # authoritative: walk the list one entry at a time
    if _walk_to(combo, want, app, max_items=max_items):
        return True

    if original and _combo_value(combo) != original:
        _walk_to(combo, original, app, max_items=max_items)
    return False


def _click_data_navigation(app: App, name: str, timeout: float = 10.0) -> None:
    def _find():
        control_types = (
            auto.TreeItemControl,
            auto.ListItemControl,
            auto.TextControl,
            auto.ButtonControl,
        )

        for control_type in control_types:
            try:
                controls_found = control_type(
                    searchFromControl=app.window,
                    searchDepth=30,
                    Name=name,
                )

                if controls_found.Exists(0, 0):
                    return controls_found
            except Exception:
                continue

        return None

    control = wait_until(
        _find,
        f"Data navigation item {name!r}",
        timeout=timeout,
    )

    click(control, app)

def set_combo(combo: auto.Control, value: str, must_exist: bool = False, app: Optional[App] = None) -> bool:
    return select_combo_by_walk(combo, value, app=app)
