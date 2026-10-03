from __future__ import annotations

import uiautomation as auto

from .controls import find_by_name, label_value_control
from .wait import wait_until

_VALUE_TYPES = (auto.EditControl, auto.ComboBoxControl, auto.CheckBoxControl)

#: Which ControlTypes can hold a value, for the lenient name pass below.
_VALUE_TYPE_NAMES = ("EditControl", "ComboBoxControl", "CheckBoxControl")


def field(container: auto.Control, label: str, timeout: float = 8.0) -> auto.Control:
    def _find():
        for ct in _VALUE_TYPES:
            c = ct(searchFromControl=container, searchDepth=32, Name=label)
            if c.Exists(0, 0):
                return c
        try:
            return label_value_control(container, label, timeout=0.5)
        except Exception:
            pass
        try:
            return find_by_name(container, label, timeout=0.5,
                                control_types=_VALUE_TYPE_NAMES)
        except Exception:
            return None
    return wait_until(_find, f"field {label!r}", timeout=timeout)


def dual_field(container: auto.Control, label: str, timeout: float = 8.0) -> tuple[auto.Control, auto.Control]:
    """Resolve a label that covers two side-by-side controls, left then right
    (e.g. 'First Name Last Name' -> (first_name_edit, last_name_edit))."""
    def _find():
        lbl = auto.TextControl(searchFromControl=container, searchDepth=32, Name=label)
        if not lbl.Exists(0, 0):
            return None
        sib = lbl.GetNextSiblingControl()
        if not sib:
            return None
        kids = [c for c in sib.GetChildren() if c.ControlTypeName in ("EditControl", "ComboBoxControl")]
        if len(kids) < 2:
            return None
        kids.sort(key=lambda c: c.BoundingRectangle.left)
        return (kids[0], kids[1])
    return wait_until(_find, f"dual field {label!r}", timeout=timeout)


def icon_group(container: auto.Control, under_label: str, count: int,
               timeout: float = 8.0, exact: bool = True) -> list[auto.Control]:
    def _find():
        lbl = auto.TextControl(searchFromControl=container, searchDepth=32, Name=under_label)
        if not lbl.Exists(0, 0):
            return None
        parent = lbl.GetParentControl()
        imgs = [c for c in parent.GetChildren() if c.ControlTypeName == "ImageControl"]
        if (len(imgs) != count) if exact else (len(imgs) < count):
            return None
        imgs.sort(key=lambda c: c.BoundingRectangle.top)
        return imgs[:count]

    how = "exactly" if exact else "at least"
    return wait_until(_find, f"{how} {count} icon(s) under {under_label!r}", timeout=timeout)


ADDRESS_ICON_COUNT = 2
EXISTING_CONTACT_INDEX = 0


def existing_contact_icon(order_pane: auto.Control, timeout: float = 8.0) -> auto.Control:
    icons = icon_group(order_pane, "Addresses", ADDRESS_ICON_COUNT,
                       timeout=timeout, exact=True)
    return icons[EXISTING_CONTACT_INDEX]
