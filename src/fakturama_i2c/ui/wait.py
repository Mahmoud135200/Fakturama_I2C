
from __future__ import annotations

import time
from typing import Callable, TypeVar

T = TypeVar("T")


class WaitTimeout(Exception):
    def __init__(self, description: str, last_error: Exception | None = None):
        msg = f"timed out waiting for: {description}"
        if last_error:
            msg += f" (last error: {last_error})"
        super().__init__(msg)
        self.description = description


def wait_until(predicate: Callable[[], T], description: str, timeout: float = 10.0,
                interval: float = 0.25) -> T:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            result = predicate()
            if result:
                return result
        except Exception as e:
            last_error = e
        time.sleep(interval)
    raise WaitTimeout(description, last_error)


def wait_stable(get_snapshot: Callable[[], T], description: str, timeout: float = 10.0,
                 interval: float = 0.3, stable_polls: int = 2) -> T:
    deadline = time.monotonic() + timeout
    last = object()
    streak = 0
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            cur = get_snapshot()
        except Exception as e:  # noqa: BLE001
            last_error = e
            time.sleep(interval)
            continue
        if cur == last:
            streak += 1
            if streak >= stable_polls:
                return cur
        else:
            streak = 1
            last = cur
        time.sleep(interval)
    raise WaitTimeout(description, last_error)
