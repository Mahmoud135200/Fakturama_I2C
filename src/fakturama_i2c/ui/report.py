
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


class ManualReviewRequired(Exception):
    def __init__(self, step: str, expected: str, observed: str, screenshot: Optional[str] = None):
        super().__init__(f"[{step}] expected {expected}; observed {observed}")
        self.step = step
        self.expected = expected
        self.observed = observed
        self.screenshot = screenshot


@dataclass
class StepLog:
    step: str
    ok: bool
    detail: str = ""
    screenshot: Optional[str] = None
    t: float = field(default_factory=time.time)


@dataclass
class RunReport:
    out_dir: Path
    image: str = ""
    steps: list[StepLog] = field(default_factory=list)
    created: dict[str, list[str]] = field(default_factory=lambda: {
        "debtor": [], "payment_method": [], "vat": [], "product": []})
    order_no: Optional[str] = None
    invoice_no: Optional[str] = None
    ok: bool = False
    error: Optional[str] = None

    def __post_init__(self):
        self.out_dir = Path(self.out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def log(self, step: str, ok: bool, detail: str = "", screenshot: Optional[str] = None) -> None:
        self.steps.append(StepLog(step, ok, detail, screenshot))

    def note_created(self, kind: str, name: str) -> None:
        self.created.setdefault(kind, []).append(name)

    def to_dict(self) -> dict:
        return {
            "image": self.image,
            "ok": self.ok,
            "error": self.error,
            "order_no": self.order_no,
            "invoice_no": self.invoice_no,
            "created": self.created,
            "steps": [
                {"step": s.step, "ok": s.ok, "detail": s.detail, "screenshot": s.screenshot, "t": s.t}
                for s in self.steps
            ],
        }

    def save(self) -> Path:
        path = self.out_dir / "report.json"
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        return path
