
import pytest

from fakturama_i2c.errors import (
    AmbiguousMatchError,
    ElementNotFoundError,
    ExtractionError,
    FakturamaAutomationError,
    ForegroundRequiredError,
    ManualReviewRequired,
    UIAutomationError,
    ValidationError,
    VerificationError,
    WaitTimeoutError,
)


@pytest.mark.parametrize("exc", [
    ExtractionError(["bad"]),
    ValidationError(["bad"]),
    UIAutomationError("x"),
    AmbiguousMatchError("Debtor", "name", [1, 2]),
    VerificationError("total", "1.00", "2.00"),
    ManualReviewRequired(step="s", reason="r"),
])
def test_everything_shares_one_root(exc):
    """One `except FakturamaAutomationError` must catch every deliberate error."""
    assert isinstance(exc, FakturamaAutomationError)


def test_only_ui_errors_are_transient():
    """Retry policy: UI glitches may be
    retried; wrong data and ambiguous matches may not."""
    assert UIAutomationError("x").transient is True
    assert ElementNotFoundError("Save").transient is True
    assert WaitTimeoutError("dialog").transient is True

    assert ValidationError(["x"]).transient is False
    assert ExtractionError(["x"]).transient is False
    assert AmbiguousMatchError("Debtor", "c", [1, 2]).transient is False
    assert VerificationError("total", 1, 2).transient is False
    assert ManualReviewRequired(step="s", reason="r").transient is False


def test_foreground_required_is_not_retryable():
    """Background mode hitting a click-only control is a hard limitation,
    not a transient glitch -- retrying cannot help."""
    err = ForegroundRequiredError("3.2 product selector", "icon exposes no invocable pattern")
    assert err.transient is False
    assert "3.2 product selector" in str(err)


def test_element_not_found_reports_its_search_strategy():
    """A failure must be diagnosable without attaching a debugger."""
    err = ElementNotFoundError("Cust.Ref.", where="New Order", strategy="Name+ControlType", timeout=8.0)
    text = str(err)
    assert "Cust.Ref." in text and "New Order" in text and "Name+ControlType" in text and "8.0" in text


def test_ambiguous_match_keeps_the_candidates():
    """The manual-review popup lists them, so they must survive the raise."""
    err = AmbiguousMatchError("Debtor", "company=ABC", ["ABC GmbH Berlin", "ABC GmbH Munich"])
    assert len(err.candidates) == 2
    assert "2" in str(err)


def test_validation_error_lists_every_problem():
    err = ValidationError(["line 1 total wrong", "VAT total wrong"])
    assert err.problems == ["line 1 total wrong", "VAT total wrong"]
    assert "line 1 total wrong" in str(err)


# ------------------------------------------------------- manual review payload

def test_manual_review_carries_full_evidence():
    err = ManualReviewRequired(
        step="2.3 Debtor match", reason="two equally good matches",
        entity="Northstar Office GmbH", expected="exactly 1", actual="2",
        candidates=["a", "b"], screenshot="runs/x.png", can_retry=True)
    data = err.as_dict()
    assert data["step"] == "2.3 Debtor match"
    assert data["entity"] == "Northstar Office GmbH"
    assert data["candidates"] == ["a", "b"]
    assert data["screenshot"] == "runs/x.png"
    assert data["can_retry"] is True


def test_manual_review_defaults_to_not_retryable():
    """Retry is only offered when re-running the step could legitimately
    succeed; the safe default is abort-only."""
    assert ManualReviewRequired(step="s", reason="r").can_retry is False
