
from __future__ import annotations

import ast
import inspect

import pytest

from fakturama_i2c.ui import flow

#: Attributes that are visible in the address box and identify the Debtor.
IDENTITY_FIELDS = {"company", "last_name", "first_name"}

#: Attributes that live below the fold. Asserting on these always fails.
BELOW_THE_FOLD = {"zip", "city", "street", "country"}


def _confirm_calls() -> list[ast.Call]:
    tree = ast.parse(inspect.getsource(flow))
    return [n for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "confirm_addresses_populated"]


def _attr_names(call: ast.Call) -> set[str]:
    """Every attribute name reached through the call's arguments."""
    return {n.attr for arg in call.args for n in ast.walk(arg)
            if isinstance(n, ast.Attribute)}


def test_flow_actually_confirms_addresses():
    """Guard the guard: if these calls vanish, the rest of this file is vacuous."""
    assert len(_confirm_calls()) >= 4


@pytest.mark.parametrize("call", _confirm_calls(),
                         ids=lambda c: f"flow.py:{c.lineno}")
def test_no_call_asserts_on_below_the_fold_address_parts(call):
    offending = _attr_names(call) & BELOW_THE_FOLD
    assert not offending, (
        f"flow.py:{call.lineno} asks confirm_addresses_populated for "
        f"{sorted(offending)}, which the address box does not render without "
        f"scrolling -- this check can only ever fail. Assert on "
        f"{sorted(IDENTITY_FIELDS)} instead."
    )


def test_debtor_selection_steps_still_verify_identity():
    """The two steps that confirm a Debtor landed must name the Debtor.

    An empty-argument call only proves *an* address block exists, which the
    wrong Debtor would satisfy just as well.
    """
    checked = [c for c in _confirm_calls() if _attr_names(c) & IDENTITY_FIELDS]
    assert len(checked) >= 3, (
        "expected the 2.4, 2.13 and 4.1 confirmations to assert on the "
        f"Debtor's identity; only {len(checked)} call(s) do")
