
from __future__ import annotations
from typing import Any, Optional


class FakturamaAutomationError(Exception):
    
    transient: bool = False


# extraction

class ExtractionError(FakturamaAutomationError):

    def __init__(self, problems: list[str]):
        super().__init__("Extraction failed:\n  - " + "\n  - ".join(problems))
        self.problems = problems


class ValidationError(FakturamaAutomationError):
    
    def __init__(self, problems: list[str]):
        super().__init__("Validation failed:\n  - " + "\n  - ".join(problems))
        self.problems = problems


# ui automation

class UIAutomationError(FakturamaAutomationError):
   
    transient = True


class ElementNotFoundError(UIAutomationError):

    def __init__(self, what: str, where: str = "", strategy: str = "", timeout: Optional[float] = None):
        msg = f"element not found: {what}"
        if where:
            msg += f" in {where}"
        if strategy:
            msg += f" (searched by {strategy})"
        if timeout is not None:
            msg += f" after {timeout}s"
        super().__init__(msg)
        self.what, self.where, self.strategy, self.timeout = what, where, strategy, timeout


class WaitTimeoutError(UIAutomationError):
   
    def __init__(self, description: str, timeout: Optional[float] = None,
                 last_error: Optional[BaseException] = None):
        msg = f"timed out waiting for: {description}"
        if timeout is not None:
            msg += f" ({timeout}s)"
        if last_error:
            msg += f" [last error: {last_error}]"
        super().__init__(msg)
        self.description, self.timeout, self.last_error = description, timeout, last_error


class ForegroundRequiredError(UIAutomationError):
    
    transient = False

    def __init__(self, step: str, reason: str):
        super().__init__(f"step {step!r} requires foreground: {reason}")
        self.step, self.reason = step, reason


#matching

class AmbiguousMatchError(FakturamaAutomationError):
    

    def __init__(self, entity: str, criteria: str, candidates: list[Any]):
        super().__init__(
            f"{len(candidates)} {entity} records match {criteria}; refusing to guess")
        self.entity, self.criteria, self.candidates = entity, criteria, candidates


class VerificationError(FakturamaAutomationError):
    

    def __init__(self, what: str, expected: Any, actual: Any):
        super().__init__(f"verification failed for {what}: expected {expected!r}, got {actual!r}")
        self.what, self.expected, self.actual = what, expected, actual


#manual review

class ManualReviewRequired(FakturamaAutomationError):
   

    def __init__(self, step: str, reason: str, expected: Any = None, actual: Any = None,
                 entity: Optional[str] = None, candidates: Optional[list] = None,
                 screenshot: Optional[str] = None, can_retry: bool = False):
        super().__init__(f"[{step}] {reason}")
        self.step = step
        self.reason = reason
        self.expected = expected
        self.actual = actual
        self.entity = entity
        self.candidates = candidates or []
        self.screenshot = screenshot
        self.can_retry = can_retry

    def as_dict(self) -> dict:
        return {
            "step": self.step,
            "reason": self.reason,
            "entity": self.entity,
            "expected": self.expected,
            "actual": self.actual,
            "candidates": self.candidates,
            "screenshot": self.screenshot,
            "can_retry": self.can_retry,
        }
