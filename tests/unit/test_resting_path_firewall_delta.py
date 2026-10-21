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
CLIENT_REL: Final[str] = "src/breezy/adapters/polymarket_us/exec/client.py"

#: callee -> the order coroutines allowed to reference it. Each key is a row
#: ADDED to ``EXEC_ORDER_COROUTINE_PERMITTED_CALLEES`` by its own commit.
ORDER_ROWS: Final[dict[str, frozenset[str]]] = {
    "self._resting_cancel_target": frozenset({"_cancel_order", "_cancel_all_orders"}),
    "self._cancel_resting_order": frozenset({"_cancel_order", "_cancel_all_orders"}),
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
    """Non-vacuity: the same call planted into an order coroutine OUTSIDE the row's
    named set (``_cancel_order``, or ``_modify_order`` for a row that names it) is not
    within the row's coroutines, so the usage pin above would fail on it."""
    source = CLIENT_PATH.read_text(encoding="utf-8")
    host = "_cancel_order" if "_cancel_order" not in ORDER_ROWS[callee] else "_modify_order"
    planted = _plant_into(source, host, f"{callee}(None)")
    used = _order_references(planted, callee)
    assert host in used
    assert not used <= ORDER_ROWS[callee]


# ---------------------------------------------------------------------------
# Row N1: the GET-confirm coroutine's exact callee set (new, scanned)
# ---------------------------------------------------------------------------

#: Everything ``_confirm_resting_order`` may call. NO ``self._order_sender.*``, no
#: signer, no store write. (The banned-word loop of the order allowlist is NOT
#: copied here: ``self._private_read`` contains "read" -- the whole point of a
#: GET-only helper.)
EXEC_RESTING_CONFIRM_PERMITTED_CALLEES: Final[frozenset[str]] = frozenset(
    {
        "asyncio.sleep",
        "UUID4",
        "isinstance",
        "parse_order_status_report",
        "payload.get",
        "self._clock.timestamp_ns",
        "self._log.debug",
        "self._log.error",
        "self._log.warning",
        "self._private_read",
        "submit_chain.order_by_id_path",
        "submit_chain.resting_echo_matches",
        "submit_chain.valid_venue_order_id",
    }
)
_CONFIRM: Final[str] = "_confirm_resting_order"
_EGRESS_NAMES: Final[tuple[str, ...]] = ("_order_sender", "_write_signer", "post_order")


def _function(source: str, name: str) -> ast.AsyncFunctionDef:
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} is not defined as a coroutine")


def _callees(fn: ast.AST) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            out.add(firewall._dotted_callee(node.func) or ast.dump(node.func)[:40])
    return out


def _confirm_violations(source: str) -> list[str]:
    fn = _function(source, _CONFIRM)
    found = sorted(_callees(fn) - EXEC_RESTING_CONFIRM_PERMITTED_CALLEES)
    for node in ast.walk(fn):
        if isinstance(node, ast.Await):
            value = node.value
            target = firewall._dotted_callee(value.func) if isinstance(value, ast.Call) else None
            if target not in {"self._private_read", "asyncio.sleep"}:
                found.append(f"await {target}")
        if isinstance(node, ast.Attribute) and node.attr in _EGRESS_NAMES:
            found.append(f"attribute {node.attr}")
    return found


def test_the_confirm_coroutine_callee_set_is_exact_and_egress_free() -> None:
    source = CLIENT_PATH.read_text(encoding="utf-8")
    assert _confirm_violations(source) == []
    # Set EQUALITY (not membership): a permitted name nothing uses is dead permission.
    assert _callees(_function(source, _CONFIRM)) == EXEC_RESTING_CONFIRM_PERMITTED_CALLEES


def test_the_confirm_coroutine_is_a_declared_inventory_member() -> None:
    assert _CONFIRM in firewall.EXEC_PERMITTED_COROUTINE_NAMES


@pytest.mark.parametrize(
    "statement",
    [
        "self._order_sender.post_order(None)",
        "await self._order_sender.post_order(None)",
        "self._write_signer.sign_headers('POST', '/v1/orders')",
        "self._store_set('k', b'v')",
    ],
)
def test_planting_a_send_or_write_into_the_confirm_coroutine_is_flagged(statement: str) -> None:
    source = CLIENT_PATH.read_text(encoding="utf-8")
    planted = _plant_into(source, _CONFIRM, statement)
    assert _confirm_violations(planted) != []


# ---------------------------------------------------------------------------
# Resolver-scan rows (P6a/P6b and the binder's own callees)
# ---------------------------------------------------------------------------

#: callee -> the scanned resolver bodies allowed to call it. Each key is a row
#: ADDED to ``EXEC_RESOLVER_PERMITTED_CALLEES`` by its own commit; none is a send.
RESOLVER_ROWS: Final[dict[str, frozenset[str]]] = {
    "submit_chain.resting_index_bytes": frozenset({"_bind_resting_order"}),
    "submit_chain.resting_binding_bytes": frozenset({"_bind_resting_order"}),
    "self._read_fill_index": frozenset({"_bind_resting_order"}),
    "submit_chain.valid_venue_order_id": frozenset({"_bind_resting_order"}),
    "submit_chain.resting_echo_matches": frozenset({"_resolve_ambiguous_intents"}),
    "self.generate_order_accepted": frozenset({"_bind_resting_order"}),
    "self._bind_resting_order": frozenset({"_resolve_ambiguous_intents"}),
}
#: The scanned resolver helper this item adds (row P6a): the ONE binder.
BINDER: Final[str] = "_bind_resting_order"


def _resolver_references(source: str, callee: str) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
            continue
        if node.name not in firewall.EXEC_RESOLVER_COROUTINES:
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Call) and firewall._dotted_callee(inner.func) == callee:
                found.add(node.name)
    return found


def _plant_any(source: str, function: str, statement: str) -> str:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef) and node.name == function:
            node.body.insert(0, ast.parse(statement).body[0])
            return ast.unparse(ast.fix_missing_locations(tree))
    raise AssertionError(f"{function} is not defined")


@pytest.mark.parametrize("callee", sorted(RESOLVER_ROWS))
def test_each_resolver_row_is_in_the_firewall_set_and_used_only_where_named(callee: str) -> None:
    assert callee in firewall.EXEC_RESOLVER_PERMITTED_CALLEES
    used = _resolver_references(CLIENT_PATH.read_text(encoding="utf-8"), callee)
    assert used, f"{callee} must be referenced (a row nothing uses is dead permission)"
    assert used <= RESOLVER_ROWS[callee], (callee, used)


@pytest.mark.parametrize("callee", sorted(RESOLVER_ROWS))
def test_planting_a_resolver_row_into_another_scanned_body_trips_the_pin(callee: str) -> None:
    source = CLIENT_PATH.read_text(encoding="utf-8")
    planted = _plant_any(source, "_resolve_terminal_zero", f"{callee}(None)")
    used = _resolver_references(planted, callee)
    assert "_resolve_terminal_zero" in used
    assert not used <= RESOLVER_ROWS[callee]


def test_the_binder_is_a_scanned_resolver_helper_and_a_planted_send_is_flagged() -> None:
    """Row P6a-1 (r3 R1): ``_bind_resting_order`` is scanned like the resolver, so a
    ``post_order`` laundered through it would be a violation."""
    assert BINDER in firewall.EXEC_RESOLVER_COROUTINES
    source = CLIENT_PATH.read_text(encoding="utf-8")
    assert firewall.find_exec_resolver_violations(CLIENT_REL, source) == []
    planted = _plant_any(source, BINDER, "self._order_sender.post_order(None)")
    violations = firewall.find_exec_resolver_violations(CLIENT_REL, planted)
    assert any(BINDER in v.detail for v in violations), violations


# ---------------------------------------------------------------------------
# Row P22: the _submit_order prefix pin is sensitive (non-vacuity of the re-pin)
# ---------------------------------------------------------------------------


def _prefix_digest(source: str) -> str:
    import hashlib

    fn = ast.parse(source).body[0]
    assert isinstance(fn, ast.AsyncFunctionDef)
    index = next(
        i
        for i, st in enumerate(fn.body)
        if isinstance(st, ast.Try) and "self._latch.arm" in ast.unparse(st)
    )
    prefix = "\n".join(ast.dump(s) for s in fn.body[: index + 1])
    return hashlib.sha256(prefix.encode()).hexdigest()


def test_the_submit_prefix_pin_moves_when_a_statement_is_planted_into_the_prefix() -> None:
    import inspect
    import textwrap

    real = textwrap.dedent(
        inspect.getsource(client_module.PolymarketUSExecutionClient._submit_order)
    )
    planted = _plant_into(real, "_submit_order", "self._log.warning('planted')")
    assert _prefix_digest(real) != _prefix_digest(planted)


# ---------------------------------------------------------------------------
# Rows FW-1..FW-4: functions allowed to reference ``self._order_sender``
# ---------------------------------------------------------------------------

#: Functions ADDED to ``ORDER_SENDER_REFERENCE_PERMITTED_SCOPES`` (rows FW-1, FW-2),
#: one named term per reviewed commit.
SENDER_SCOPE_ROWS: Final[frozenset[str]] = frozenset(
    {"_cancel_resting_order", "_cancel_slug_orders"}
)
#: Functions ADDED to ``ORDER_SENDER_REFERENCE_FUNCTIONS_AT_HEAD`` (rows FW-3, FW-4).
SENDER_HEAD_ROWS: Final[frozenset[str]] = frozenset(
    {"_cancel_all_orders", "_cancel_order", "_cancel_resting_order", "_cancel_slug_orders"}
)


@pytest.mark.parametrize("name", sorted(SENDER_SCOPE_ROWS))
def test_each_sender_scope_row_is_permitted_and_actually_references_the_sender(name: str) -> None:
    assert name in firewall.ORDER_SENDER_REFERENCE_PERMITTED_SCOPES
    referencing = firewall._functions_referencing_order_sender(
        CLIENT_REL, CLIENT_PATH.read_text(encoding="utf-8")
    )
    assert name in referencing, f"{name} permits a reference nothing makes (dead permission)"


@pytest.mark.parametrize("name", sorted(SENDER_HEAD_ROWS))
def test_each_sender_head_row_is_pinned_in_the_exact_at_head_set(name: str) -> None:
    assert name in firewall.ORDER_SENDER_REFERENCE_FUNCTIONS_AT_HEAD


@pytest.mark.parametrize("name", sorted(SENDER_SCOPE_ROWS | SENDER_HEAD_ROWS))
def test_planting_a_sender_reference_into_any_other_helper_is_still_flagged(name: str) -> None:
    """Non-vacuity: the permission is BY NAME. The same reference planted into a
    helper that is not a row trips the scan, and the shipped tree is clean."""
    source = CLIENT_PATH.read_text(encoding="utf-8")
    before = {v.detail for v in firewall.find_order_sender_reference_violations(CLIENT_REL, source)}
    planted = _plant_any(
        source, "_retire_resting_row", "self._order_sender.post_cancel_order(None)"
    )
    after = {v.detail for v in firewall.find_order_sender_reference_violations(CLIENT_REL, planted)}
    assert [d for d in after - before if "_retire_resting_row" in d], after
    assert name != "_retire_resting_row"


# ---------------------------------------------------------------------------
# Row P2: the order-coroutine await ban, exempting exactly two cancel coroutines
# ---------------------------------------------------------------------------


def _send_path_violations(source: str) -> list[str]:
    return [v.detail for v in firewall.find_exec_send_path_violations(CLIENT_REL, source)]


def test_the_shipped_cancel_coroutines_await_only_the_pinned_callee() -> None:
    source = CLIENT_PATH.read_text(encoding="utf-8")
    assert [d for d in _send_path_violations(source) if "awaits" in d] == []
    for name in sorted(firewall.EXEC_CANCEL_AWAIT_EXEMPT_COROUTINES):
        awaited = {
            firewall._dotted_callee(n.value.func)
            for n in ast.walk(_function(source, name))
            if isinstance(n, ast.Await) and isinstance(n.value, ast.Call)
        }
        assert awaited == set(firewall.EXEC_CANCEL_QUERY_AWAITED_CALLEES), (name, awaited)


def test_the_exempt_set_and_the_awaited_set_are_exact() -> None:
    assert firewall.EXEC_CANCEL_AWAIT_EXEMPT_COROUTINES == {"_cancel_order", "_cancel_all_orders"}
    assert firewall.EXEC_CANCEL_QUERY_AWAITED_CALLEES == {"self._cancel_resting_order"}


@pytest.mark.parametrize(
    ("function", "statement"),
    [
        ("_cancel_order", "await self._private_read('/x')"),
        ("_cancel_order", "await self._order_sender.post_order(None)"),
        ("_cancel_all_orders", "await self._cancel_slug_orders('x')"),
        # the pinned callee awaited by an order coroutine that is NOT exempt
        ("_modify_order", "await self._cancel_resting_order(['x'])"),
        ("_submit_order_list", "await self._cancel_resting_order(['x'])"),
    ],
)
def test_planting_any_other_await_into_an_order_coroutine_is_flagged(
    function: str, statement: str
) -> None:
    source = CLIENT_PATH.read_text(encoding="utf-8")
    before = set(_send_path_violations(source))
    planted = _plant_any(source, function, statement)
    new = [d for d in set(_send_path_violations(planted)) - before if "awaits" in d]
    assert any(function in d for d in new), new
