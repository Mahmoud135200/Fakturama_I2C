
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable, Optional

import uiautomation as auto

from .wait import wait_until

APP_WINDOW_CLASS = "SWT_Window0"


# lookup

def find(parent: auto.Control, ctrl_cls, timeout: float = 8.0, depth: int = 32, **search) -> auto.Control:
    """Find one descendant of `parent` by control type + search kwargs (Name=, SubName=, AutomationId=, ...)."""
    def _find():
        c = ctrl_cls(searchFromControl=parent, searchDepth=depth, **search)
        return c if c.Exists(0, 0) else None
    desc = f"{ctrl_cls.__name__} {search} under {_describe(parent)}"
    return wait_until(_find, desc, timeout=timeout)


def find_modal(parent: auto.Control, title: str, timeout: float = 2.0) -> Optional[auto.Control]:
    def _find():
        d = auto.WindowControl(searchFromControl=parent, searchDepth=10, Name=title)
        return d if d.Exists(0, 0) else None
    try:
        return wait_until(_find, f"modal {title!r}", timeout=timeout, interval=0.2)
    except Exception:
        return None


def dismiss_modal(parent: auto.Control, title: str, button: str = "OK", timeout: float = 2.0) -> bool:
    dlg = find_modal(parent, title, timeout=timeout)
    if dlg is None:
        return False
    try:
        btn = find(dlg, auto.ButtonControl, timeout=3, Name=button)
    except Exception:
        return False
    click(btn)

    for _ in range(5):
        again = find_modal(parent, title, timeout=1.0)
        if again is None:
            break
        try:
            click(find(again, auto.ButtonControl, timeout=2, Name=button))
        except Exception:
            break
    return True


def exists(parent: auto.Control, ctrl_cls, timeout: float = 1.0, depth: int = 32, **search) -> bool:
    try:
        find(parent, ctrl_cls, timeout=timeout, depth=depth, **search)
        return True
    except Exception:
        return False


def _describe(c: auto.Control) -> str:
    try:
        return f"{c.ControlTypeName} {c.Name!r}"
    except Exception:
        return "<control>"


def normalize_name(s: Optional[str]) -> str:
    return (s or "").replace("&", "").strip().rstrip(":").strip().casefold()


def accessible_names(ctrl: auto.Control) -> list[str]:
    names: list[str] = []
    for get in (lambda: ctrl.Name,
                lambda: ctrl.GetLegacyIAccessiblePattern().Name):
        try:
            value = get()
        except Exception:
            continue
        if value:
            names.append(value)
    return names


def find_by_name(parent: auto.Control, name: str, timeout: float = 8.0,
                 max_depth: int = 32, control_types: Optional[tuple] = None,
                 app: Optional["object"] = None) -> auto.Control:
    want = normalize_name(name)

    def _find():
        for ctrl, _depth in auto.WalkControl(parent, includeTop=False, maxDepth=max_depth):
            try:
                if control_types and ctrl.ControlTypeName not in control_types:
                    continue
                if any(normalize_name(n) == want for n in accessible_names(ctrl)):
                    return ctrl
            except Exception:
                continue
        return None

    return wait_until(_find, f"control named {name!r} under {_describe(parent)}",
                      timeout=timeout)


def exists_by_name(parent: auto.Control, name: str, timeout: float = 1.0,
                   max_depth: int = 32) -> bool:
    try:
        find_by_name(parent, name, timeout=timeout, max_depth=max_depth)
        return True
    except Exception:
        return False


def label_value_control(parent: auto.Control, label_text: str, timeout: float = 8.0) -> auto.Control:
    def _find():
        lbl = auto.TextControl(searchFromControl=parent, searchDepth=32, Name=label_text)
        if not lbl.Exists(0, 0):
            return None
        sib = lbl.GetNextSiblingControl()
        hops = 0
        while sib and hops < 5:
            if sib.ControlTypeName in ("EditControl", "ComboBoxControl", "ButtonControl", "CheckBoxControl"):
                return sib
            if sib.ControlTypeName == "PaneControl":
                inner = find(sib, auto.EditControl, timeout=0.3) if exists(sib, auto.EditControl, timeout=0.3) \
                    else (find(sib, auto.ComboBoxControl, timeout=0.3) if exists(sib, auto.ComboBoxControl, timeout=0.3) else None)
                if inner is not None:
                    return inner
                return sib
            sib = sib.GetNextSiblingControl()
            hops += 1
        return None
    return wait_until(_find, f"value control following label {label_text!r}", timeout=timeout)


# actions

def click(ctrl: auto.Control, app: Optional["object"] = None) -> None:
    try:
        ctrl.GetInvokePattern().Invoke()
        return
    except Exception:
        pass
    try:
        ctrl.GetSelectionItemPattern().Select()
        return
    except Exception:
        pass
    try:
        leg = ctrl.GetLegacyIAccessiblePattern()
        if leg.DefaultAction:
            leg.DoDefaultAction()
            return
    except Exception:
        pass
    if app is not None:
        app.ensure_visible()
    ctrl.SetFocus()
    ctrl.Click(simulateMove=False)


def checkbox_checked(ctrl: auto.Control) -> bool:
    try:
        return ctrl.GetTogglePattern().ToggleState == auto.ToggleState.On
    except Exception:
        pass
    try:
        return bool(ctrl.GetLegacyIAccessiblePattern().State & 0x10)  # STATE_SYSTEM_CHECKED
    except Exception:
        return False


def set_checkbox(ctrl: auto.Control, checked: bool, app: Optional["object"] = None,
                  timeout: float = 3.0) -> bool:
    if checkbox_checked(ctrl) == checked:
        return True
    click(ctrl, app)
    try:
        wait_until(lambda: checkbox_checked(ctrl) == checked,
                   f"checkbox to become {'checked' if checked else 'unchecked'}",
                   timeout=timeout, interval=0.1)
        return True
    except Exception:
        return False


def _type_value(ctrl: auto.Control, value: str, app: Optional["object"] = None,
                commit_key: str = "{Tab}") -> None:
    if app is not None:
        app.ensure_visible()
    ctrl.SetFocus()
    ctrl.SendKeys("{Ctrl}a", waitTime=0.05)
    if value:
        ctrl.SendKeys(value, waitTime=0.01)
    else:
        ctrl.SendKeys("{Delete}", waitTime=0.05)
    if commit_key:
        ctrl.SendKeys(commit_key, waitTime=0.05)


def type_into_search_box(ctrl: auto.Control, value: str, app: Optional["object"] = None,
                          attempts: int = 3) -> None:
    if app is not None:
        app.ensure_visible()

    for attempt in range(attempts):
        ctrl.SetFocus()

        try:
            wait_until(lambda: ctrl.HasKeyboardFocus, "search box to take focus",
                       timeout=2, interval=0.05)
        except Exception:
            pass

        ctrl.SendKeys("{Ctrl}a", waitTime=0.05)

        if not value:
            ctrl.SendKeys("{Back}", waitTime=0.05)
            return

        # Replaces the selection; the box is never empty in between.
        ctrl.SendKeys(value, waitTime=0.02)

        if not _still_there(ctrl):
            return

        try:
            wait_until(lambda: read_text(ctrl).strip() == value.strip(),
                       f"search box to contain {value!r}", timeout=1.5, interval=0.1)
            return
        except Exception:
            if not _still_there(ctrl):
                return
            if attempt == attempts - 1:
                raise ValueError(
                    f"search box kept the wrong text: wanted {value!r}, "
                    f"got {read_text(ctrl)!r} after {attempts} attempts")


def _still_there(ctrl: auto.Control) -> bool:
    try:
        return bool(ctrl.Exists(0.3, 0.2))
    except Exception:
        return False


def exact_match(written: str, read: str) -> bool:
    return read.strip() == written.strip()


def _as_decimal(text: str) -> Decimal:
    cleaned = re.sub(r"[^0-9,.\-]", "", (text or "").strip())
    if cleaned.count(",") and not cleaned.count("."):
        cleaned = cleaned.replace(",", ".")          # 1,5 -> 1.5
    else:
        cleaned = cleaned.replace(",", "")           # 1,234.50 -> 1234.50
    if cleaned in ("", "-", ".", "-."):
        raise InvalidOperation(f"no number in {text!r}")
    return Decimal(cleaned)


def numeric_match(written: str, read: str) -> bool:
    try:
        return _as_decimal(written) == _as_decimal(read)
    except (InvalidOperation, ArithmeticError, ValueError):
        return False


def _settles_to(ctrl: auto.Control, value: str, timeout: float = 1.5,
                match: Callable[[str, str], bool] = exact_match) -> bool:
    try:
        wait_until(lambda: match(value, read_text(ctrl)),
                   f"field to settle to {value!r}", timeout=timeout, interval=0.1)
        return True
    except Exception:
        return False


def set_text(ctrl: auto.Control, value: str, read_back: bool = True,
             app: Optional["object"] = None,
             match: Callable[[str, str], bool] = exact_match,
             commit: bool = True, commit_key: str = "{Tab}") -> None:
    def _value_pattern() -> bool:
        try:
            ctrl.GetValuePattern().SetValue(value)
            return True
        except Exception:
            return False

    if commit:
        try:
            _type_value(ctrl, value, app, commit_key=commit_key)
        except Exception:
            _value_pattern()
        else:
            if read_back and not _settles_to(ctrl, value, match=match):
                _value_pattern()
    else:
        if not _value_pattern():
            _type_value(ctrl, value, app, commit_key=commit_key)
        elif read_back and not _settles_to(ctrl, value, match=match):
            _type_value(ctrl, value, app, commit_key=commit_key)

    if read_back and not _settles_to(ctrl, value, match=match):
        raise ValueError(f"read-back mismatch: wrote {value!r}, read {read_text(ctrl)!r}")


def read_text(ctrl: auto.Control) -> str:
    try:
        return ctrl.GetValuePattern().Value
    except Exception:
        pass
    try:
        return ctrl.Name
    except Exception:
        return ""


def screenshot(ctrl: auto.Control, out_dir: Path, name: str) -> str:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{name}.png"
    ctrl.CaptureToImage(str(path))
    return str(path)
