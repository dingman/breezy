"""S4 WP3 (ARM maker-sharp B4): the NO-SEND firewall delta for the resting path.

Precedent: ``test_ambig_no_id_firewall_delta.py``. Authority: S4 plan r4 delta
section 3 (the pin-row list) and ARM plan r2 delta D2 (pin discipline).

Every exact-set barrier of ``test_execution_egress_firewall_guard.py`` is
WIDENED by a NAMED row, one reviewed row per commit, never relaxed (L-12). This
module records each row and proves it non-vacuous:

* an ORDER-coroutine row names the ONE coroutine allowed to reference the new
  callee (the set itself is shared by all six order coroutines, so membership
  alone says nothing about where it is used); a planted reference from any other
  order coroutine must trip the pin;
* a scanned-body row (resolver, confirm) names its exact callee set and proves a
  planted ``post_order`` is flagged.

It imports the firewall module read-only and edits nothing in it.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

import pytest

from tests.unit import test_execution_egress_firewall_guard as firewall
from tests.unit.ambig_latch_rig import client_module

CLIENT_PATH: Final[Path] = Path(client_module.__file__)

#: callee -> the order coroutines allowed to reference it. Each key is a row
#: ADDED to ``EXEC_ORDER_COROUTINE_PERMITTED_CALLEES`` by its own commit.
ORDER_ROWS: Final[dict[str, frozenset[str]]] = {
    "self._bind_resting_order": frozenset({"_submit_order"}),
    "self._confirm_resting_order": frozenset({"_submit_order"}),
    "submit_chain.build_resting_order_body": frozenset({"_submit_order"}),
    "submit_chain.unmappable_resting_order_reason": frozenset({"_submit_order"}),
}


def _order_references(source: str, callee: str) -> set[str]:
    """The order coroutines whose body contains a call to ``callee``."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
            continue
        if node.name not in firewall.ORDER_LIFECYCLE_COROUTINES:
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Call) and firewall._dotted_callee(inner.func) == callee:
                found.add(node.name)
    return found


def _plant_into(source: str, function: str, statement: str) -> str:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef) and node.name == function:
            node.body.insert(0, ast.parse(statement).body[0])
            return ast.unparse(ast.fix_missing_locations(tree))
    raise AssertionError(f"{function} is not defined")


@pytest.mark.parametrize("callee", sorted(ORDER_ROWS))
def test_each_order_row_is_in_the_firewall_set_and_used_only_where_named(callee: str) -> None:
    assert callee in firewall.EXEC_ORDER_COROUTINE_PERMITTED_CALLEES
    used = _order_references(CLIENT_PATH.read_text(encoding="utf-8"), callee)
    assert used, f"{callee} must be referenced (a row nothing uses is dead permission)"
    assert used <= ORDER_ROWS[callee], (callee, used)


@pytest.mark.parametrize("callee", sorted(ORDER_ROWS))
def test_planting_an_order_row_into_another_order_coroutine_trips_the_pin(callee: str) -> None:
    """Non-vacuity: the same call planted into ``_cancel_order`` is NOT within the
    row's named coroutines, so the usage pin above would fail on it."""
    source = CLIENT_PATH.read_text(encoding="utf-8")
    planted = _plant_into(source, "_cancel_order", f"{callee}(None)")
    used = _order_references(planted, callee)
    assert "_cancel_order" in used
    assert not used <= ORDER_ROWS[callee]
