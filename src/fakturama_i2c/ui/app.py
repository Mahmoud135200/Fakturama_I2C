from __future__ import annotations

import ctypes
import time
from pathlib import Path

import uiautomation as auto
import win32gui
import win32process

from .wait import wait_until

SW_RESTORE = 9
_user32 = ctypes.windll.user32


def _enum_fakturama_hwnds() -> list[int]:
    found: list[int] = []

    def cb(hwnd, _):
        if win32gui.GetClassName(hwnd) == "SWT_Window0" and win32gui.IsWindowVisible(hwnd) \
                and "Fakturama" in win32gui.GetWindowText(hwnd):
            found.append(hwnd)

    win32gui.EnumWindows(cb, None)
    return found


class App:
    """Owns the connection to one running Fakturama window."""

    def __init__(self, hwnd: int):
        self.hwnd = hwnd
        self.window = auto.ControlFromHandle(hwnd)

    @classmethod
    def attach(cls, timeout: float = 30.0) -> "App":
        """Attach to an already-running Fakturama instance (it must already
        have an open workspace)."""
        def _find():
            hwnds = _enum_fakturama_hwnds()
            return hwnds[0] if hwnds else None
        hwnd = wait_until(_find, "a running Fakturama window", timeout=timeout)
        return cls(hwnd)

    def ensure_visible(self, retries: int = 5) -> None:
        if win32gui.IsIconic(self.hwnd):
            _user32.ShowWindow(self.hwnd, SW_RESTORE)
            time.sleep(0.5)
        for _ in range(retries):
            _user32.SetForegroundWindow(self.hwnd)
            time.sleep(0.25)
            if win32gui.GetForegroundWindow() == self.hwnd:
                return
        raise RuntimeError(
            "could not bring Fakturama to the foreground (another window keeps stealing focus); "
            "avoid interacting with the desktop while the automation is running")

    def pid(self) -> int:
        _, pid = win32process.GetWindowThreadProcessId(self.hwnd)
        return pid

    def screenshot(self, out_dir: Path, name: str) -> str:
        self.ensure_visible()
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{name}.png"
        self.window.CaptureToImage(str(path))
        return str(path)
