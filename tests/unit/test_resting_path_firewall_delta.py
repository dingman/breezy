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
import hashlib
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
    {
        "_cancel_all_orders",
        "_cancel_order",
        "_cancel_resting_order",
        "_cancel_slug_orders",
        "_sweep_resting_orders_at_boot",
    }
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


# ---------------------------------------------------------------------------
# Rows P4a-e: the coroutine inventory (EXEC_PERMITTED_COROUTINE_NAMES)
# ---------------------------------------------------------------------------

#: Coroutines ADDED to the exact inventory, one named entry per reviewed commit.
INVENTORY_ROWS: Final[frozenset[str]] = frozenset(
    {
        "_cancel_resting_order",
        "_confirm_cancel_terminal",
        "_cancel_slug_orders",
        "_sweep_resting_orders_at_boot",
    }
)


@pytest.mark.parametrize("name", sorted(INVENTORY_ROWS))
def test_each_inventory_row_is_declared_and_defined_and_the_equality_is_sensitive(
    name: str,
) -> None:
    assert name in firewall.EXEC_PERMITTED_COROUTINE_NAMES
    source = CLIENT_PATH.read_text(encoding="utf-8")
    defined = {n.name for n in ast.walk(ast.parse(source)) if isinstance(n, ast.AsyncFunctionDef)}
    assert name in defined, f"{name} is declared but not defined (dead permission)"
    declared = firewall.EXEC_PERMITTED_COROUTINE_NAMES
    # non-vacuity: without the row the inventory EQUALITY would fail on this name
    assert defined | firewall.EXEC_DECLARED_UNIMPLEMENTED_COROUTINES == declared
    assert defined | firewall.EXEC_DECLARED_UNIMPLEMENTED_COROUTINES != declared - {name}


# ---------------------------------------------------------------------------
# Row N1b: the GET-only cancel confirm (exact callee set, scanned)
# ---------------------------------------------------------------------------

#: Everything ``_confirm_cancel_terminal`` may call: reads and a verdict only. No sender,
#: no signer, no store write. (The banned-word loop is not copied: ``self._private_read``
#: contains "read" -- the point of a GET-only helper.)
EXEC_CANCEL_CONFIRM_PERMITTED_CALLEES: Final[frozenset[str]] = frozenset(
    {
        "isinstance",
        "payload.get",
        "self._log.warning",
        "self._private_read",
        "submit_chain.cancel_read_verdict",
        "submit_chain.order_by_id_path",
        "submit_chain.valid_venue_order_id",
    }
)
_CANCEL_CONFIRM: Final[str] = "_confirm_cancel_terminal"


def _cancel_confirm_violations(source: str) -> list[str]:
    fn = _function(source, _CANCEL_CONFIRM)
    found = sorted(_callees(fn) - EXEC_CANCEL_CONFIRM_PERMITTED_CALLEES)
    for node in ast.walk(fn):
        if isinstance(node, ast.Await):
            value = node.value
            target = firewall._dotted_callee(value.func) if isinstance(value, ast.Call) else None
            if target != "self._private_read":
                found.append(f"await {target}")
        if isinstance(node, ast.Attribute) and node.attr in _EGRESS_NAMES:
            found.append(f"attribute {node.attr}")
    return found


def test_the_cancel_confirm_callee_set_is_exact_and_egress_free() -> None:
    source = CLIENT_PATH.read_text(encoding="utf-8")
    assert _cancel_confirm_violations(source) == []
    assert _callees(_function(source, _CANCEL_CONFIRM)) == EXEC_CANCEL_CONFIRM_PERMITTED_CALLEES


@pytest.mark.parametrize(
    "statement",
    [
        "self._order_sender.post_cancel_order(None)",
        "await self._order_sender.post_cancel_all(None)",
        "self._write_signer.sign_headers('POST', '/v1/orders')",
        "self._store_set('k', b'v')",
        "await self._cancel_slug_orders('x')",
    ],
)
def test_planting_a_send_or_write_into_the_cancel_confirm_is_flagged(statement: str) -> None:
    planted = _plant_into(CLIENT_PATH.read_text(encoding="utf-8"), _CANCEL_CONFIRM, statement)
    assert _cancel_confirm_violations(planted) != []


# ---------------------------------------------------------------------------
# Row N2: the cancel loop's exact callee set -- exactly ONE send callee
# ---------------------------------------------------------------------------

_CANCEL_LOOP: Final[str] = "_cancel_resting_order"
#: The single send name the cancel loop may use (the banned-word exception).
_CANCEL_SEND_NAME: Final[str] = "self._order_sender.post_cancel_order"
EXEC_CANCEL_SEND_PERMITTED_CALLEES: Final[frozenset[str]] = frozenset(
    {
        _CANCEL_SEND_NAME,
        "asyncio.sleep",
        "frozenset",
        "list",
        "pending.remove",
        "self._cancel_slug_orders",
        "self._clear_resting_cancel_latch",
        "self._clock.timestamp_ns",
        "self._confirm_cancel_terminal",
        "self._latch_resting_cancel_unconfirmed",
        "self._log.warning",
        "self._note_cancel_refused",
        "self._resting_target_of",
        "self._settle_resting_terminal",
        "self._write_signer.sign_headers",
        "submit_chain.cancel_backoff_s",
        "submit_chain.cancel_order_path",
        "submit_chain.valid_venue_order_id",
    }
)
#: The awaits the loop may make: its own sleep, the GET-only confirm, the one send, and
#: the (disabled-until-verified) escalation helper.
_CANCEL_LOOP_AWAITS: Final[frozenset[str]] = frozenset(
    {
        "asyncio.sleep",
        "self._cancel_slug_orders",
        "self._confirm_cancel_terminal",
        _CANCEL_SEND_NAME,
    }
)
_BANNED_VERB_WORDS: Final[tuple[str, ...]] = ("read", "send", "post", "request")


def _cancel_loop_violations(source: str) -> list[str]:
    fn = _function(source, _CANCEL_LOOP)
    callees = _callees(fn)
    found = sorted(callees - EXEC_CANCEL_SEND_PERMITTED_CALLEES)
    # the banned-word loop of the order allowlist, with the ONE send name excepted
    found += [
        f"banned word in {c}"
        for c in sorted(callees - {_CANCEL_SEND_NAME})
        if any(w in c.replace("_order_sender", "") for w in _BANNED_VERB_WORDS)
    ]
    for node in ast.walk(fn):
        if isinstance(node, ast.Await):
            value = node.value
            target = firewall._dotted_callee(value.func) if isinstance(value, ast.Call) else None
            if target not in _CANCEL_LOOP_AWAITS:
                found.append(f"await {target}")
    return found


def test_the_cancel_loop_callee_set_is_exact_with_exactly_one_send_name() -> None:
    source = CLIENT_PATH.read_text(encoding="utf-8")
    assert _cancel_loop_violations(source) == []
    assert _callees(_function(source, _CANCEL_LOOP)) == EXEC_CANCEL_SEND_PERMITTED_CALLEES
    sends = [c for c in EXEC_CANCEL_SEND_PERMITTED_CALLEES if "_order_sender" in c]
    assert sends == [_CANCEL_SEND_NAME]


@pytest.mark.parametrize(
    "statement",
    [
        "await self._order_sender.post_order(None)",
        "await self._order_sender.post_cancel_all(None)",
        "await self._private_read('/x')",
        "self.create_task(self._cancel_slug_orders('x'))",
        "self._store_set('k', b'v')",
        "await self._read_open_orders()",
    ],
)
def test_planting_any_other_send_or_read_into_the_cancel_loop_is_flagged(statement: str) -> None:
    planted = _plant_into(CLIENT_PATH.read_text(encoding="utf-8"), _CANCEL_LOOP, statement)
    assert _cancel_loop_violations(planted) != []


def test_the_loop_is_referenced_only_by_the_cancel_coroutines() -> None:
    """Row P1b's usage side for the non-order callers: the sweep (later row) and the two
    order coroutines are the only places that name the loop; ``_submit_order`` never does."""
    source = CLIENT_PATH.read_text(encoding="utf-8")
    assert _order_references(source, f"self.{_CANCEL_LOOP}") == {
        "_cancel_order",
        "_cancel_all_orders",
    }
    planted = _plant_into(source, "_submit_order", f"self.{_CANCEL_LOOP}([])")
    assert "_submit_order" in _order_references(planted, f"self.{_CANCEL_LOOP}")


# ---------------------------------------------------------------------------
# Row N3: the slug cancel-all choke point
# ---------------------------------------------------------------------------

_SLUG_HELPER: Final[str] = "_cancel_slug_orders"
_CANCEL_ALL_NAME: Final[str] = "self._order_sender.post_cancel_all"
EXEC_SLUG_CANCEL_PERMITTED_CALLEES: Final[frozenset[str]] = frozenset(
    {
        _CANCEL_ALL_NAME,
        "self._log.warning",
        "self._resting_ledger",
        "self._write_signer.sign_headers",
    }
)


def _functions_naming(source: str, needle: str) -> set[str]:
    """Names of functions whose body contains a Call/Attribute reference to ``needle``."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
            continue
        for inner in ast.walk(node):
            if (isinstance(inner, ast.Attribute) and inner.attr == needle) or (
                isinstance(inner, ast.Name) and inner.id == needle
            ):
                found.add(node.name)
    return found


def test_the_slug_helper_callee_set_is_exact_with_the_one_cancel_all_name() -> None:
    source = CLIENT_PATH.read_text(encoding="utf-8")
    callees = _callees(_function(source, _SLUG_HELPER))
    assert callees == EXEC_SLUG_CANCEL_PERMITTED_CALLEES
    assert [c for c in callees if "_order_sender" in c] == [_CANCEL_ALL_NAME]


def test_post_cancel_all_is_named_only_in_the_slug_helper() -> None:
    source = CLIENT_PATH.read_text(encoding="utf-8")
    assert _functions_naming(source, "post_cancel_all") == {_SLUG_HELPER}
    for host in ("_cancel_order", "_cancel_resting_order", "_retire_resting_row"):
        planted = _plant_any(source, host, "self._order_sender.post_cancel_all(None)")
        assert _functions_naming(planted, "post_cancel_all") == {_SLUG_HELPER, host}, host


def test_the_slug_helper_is_reached_only_from_the_cancel_loop_the_sweep_and_never_submit() -> None:
    source = CLIENT_PATH.read_text(encoding="utf-8")
    assert _functions_naming(source, _SLUG_HELPER) == {
        "_cancel_resting_order",
        "_sweep_resting_orders_at_boot",
    }
    assert _order_references(source, f"self.{_SLUG_HELPER}") == set()
    planted = _plant_into(source, "_submit_order", f"self.{_SLUG_HELPER}('x')")
    assert "_submit_order" in _order_references(planted, f"self.{_SLUG_HELPER}")
    assert "_submit_order" in _functions_naming(planted, _SLUG_HELPER)


def test_the_slug_helper_refuses_to_send_before_the_pin_is_verified() -> None:
    """The first statement is the disabled-until-proven return (a plant that moves the
    send above it would change the first statement)."""
    fn = _function(CLIENT_PATH.read_text(encoding="utf-8"), _SLUG_HELPER)
    body = [
        s for s in fn.body if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))
    ]
    first = body[0]
    assert isinstance(first, ast.If)
    assert "SLUG_SCOPED_CANCEL_ALL_VERIFIED" in ast.unparse(first.test)
    assert "UNSCOPED_UNVERIFIED" in ast.unparse(first.body[0])


# ---------------------------------------------------------------------------
# Row N5: the tree scan for the cancel-all path (src AND scripts)
# ---------------------------------------------------------------------------

_REPO: Final[Path] = CLIENT_PATH.parents[5]
_CANCEL_ALL_SUBSTRINGS: Final[tuple[str, ...]] = (
    "post_cancel_all",
    "CANCEL_ALL_PATH",
    "/v1/orders/open/cancel",
)
_OWNER_REL: Final[str] = "src/breezy/adapters/polymarket_us/write_transport.py"
_PROBE_REL: Final[str] = "scripts/venue/polymarket_us_write_signing_probe.py"


def _tree_hits(extra: dict[str, str] | None = None) -> list[tuple[str, str]]:
    """(file, token) for every src/scripts file naming a cancel-all token, except the
    owner, the client (checked by AST below) and the sha-pinned legacy probe."""
    hits: list[tuple[str, str]] = []
    files = {
        p.relative_to(_REPO).as_posix(): p.read_text(encoding="utf-8")
        for root in ("src", "scripts")
        for p in sorted((_REPO / root).rglob("*.py"))
    }
    files.update(extra or {})
    for rel, text in files.items():
        if rel in {_OWNER_REL, CLIENT_REL, _PROBE_REL}:
            continue
        hits.extend((rel, tok) for tok in _CANCEL_ALL_SUBSTRINGS if tok in text)
    return hits


def test_no_other_src_or_scripts_file_names_the_cancel_all_path() -> None:
    assert _tree_hits() == []


@pytest.mark.parametrize("token", _CANCEL_ALL_SUBSTRINGS)
def test_the_tree_scan_sees_a_planted_script_naming_the_path(token: str) -> None:
    hits = _tree_hits({"scripts/venue/_planted.py": f"x = '{token}'\n"})
    assert ("scripts/venue/_planted.py", token) in hits


def test_the_legacy_probe_exemption_is_the_one_sha_pinned_constant() -> None:
    from tests.unit import test_polymarket_us_cancel_transport as b1

    assert b1._LEGACY_PROBE == _PROBE_REL
    assert hashlib.sha256((_REPO / _PROBE_REL).read_bytes()).hexdigest() == b1._LEGACY_PROBE_SHA256


def test_the_cancel_all_tokens_appear_only_in_the_choke_point() -> None:
    """Inside the client the tokens live in ``_cancel_slug_orders`` alone."""
    source = CLIENT_PATH.read_text(encoding="utf-8")
    for token in _CANCEL_ALL_SUBSTRINGS:
        assert _functions_containing(source, token) <= {_SLUG_HELPER}, token
    planted = _plant_any(source, "_cancel_resting_order", "x = write_transport.CANCEL_ALL_PATH")
    assert "_cancel_resting_order" in _functions_containing(planted, "CANCEL_ALL_PATH")


def _functions_containing(source: str, token: str) -> set[str]:
    """Functions whose unparsed body text contains ``token`` (docstrings excluded)."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
            continue
        body = node.body
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            body = body[1:]
        if any(token in ast.unparse(stmt) for stmt in body):
            found.add(node.name)
    return found


# ---------------------------------------------------------------------------
# Row N4: the boot sweep's exact callee set -- reads and the two cancel helpers only
# ---------------------------------------------------------------------------

_SWEEP: Final[str] = "_sweep_resting_orders_at_boot"
EXEC_BOOT_SWEEP_PERMITTED_CALLEES: Final[frozenset[str]] = frozenset(
    {
        "ExecutionReportMappingError",
        "_redact_order_id",
        "frozenset",
        "len",
        "parse_open_orders",
        "self._cancel_resting_order",
        "self._cancel_slug_orders",
        "self._latch_resting_cancel_unconfirmed",
        "self._log.error",
        "self._log.warning",
        "self._private_read",
        "self._resting_ledger",
        "self._resting_noid_contexts",
        "submit_chain.open_orders_envelope_is_known",
    }
)
_SWEEP_AWAITS: Final[frozenset[str]] = frozenset(
    {"self._cancel_resting_order", "self._cancel_slug_orders", "self._private_read"}
)


def _sweep_violations(source: str) -> list[str]:
    fn = _function(source, _SWEEP)
    found = sorted(_callees(fn) - EXEC_BOOT_SWEEP_PERMITTED_CALLEES)
    for node in ast.walk(fn):
        if isinstance(node, ast.Await):
            value = node.value
            target = firewall._dotted_callee(value.func) if isinstance(value, ast.Call) else None
            if target not in _SWEEP_AWAITS:
                found.append(f"await {target}")
        if isinstance(node, ast.Attribute) and node.attr == "_write_signer":
            found.append(f"attribute {node.attr}")
    # the ONLY mention of the sender is the `is None` guard (row FW-7/FW-8); every other
    # reference (a call through it, a bare alias) is a violation
    if "_order_sender" in ast.unparse(fn).replace("self._order_sender is None", ""):
        found.append("attribute _order_sender beyond the is-None guard")
    return found


def test_the_boot_sweep_callee_set_is_exact_and_never_names_the_sender() -> None:
    source = CLIENT_PATH.read_text(encoding="utf-8")
    assert _sweep_violations(source) == []
    assert _callees(_function(source, _SWEEP)) == EXEC_BOOT_SWEEP_PERMITTED_CALLEES
    # it reaches the venue only through the two cancel helpers (rows N2/N3) and reads;
    # it never names post_order, post_cancel_order or post_cancel_all itself
    text = ast.unparse(_function(source, _SWEEP))
    for banned in ("post_order", "post_cancel_order", "post_cancel_all"):
        assert banned not in text


@pytest.mark.parametrize(
    "statement",
    [
        "await self._order_sender.post_order(None)",
        "await self._order_sender.post_cancel_order(None)",
        "await self._order_sender.post_cancel_all(None)",
        "self._write_signer.sign_headers('POST', '/x')",
        "self._store_set('k', b'v')",
        "await self._read_open_orders()",
    ],
)
def test_planting_a_send_or_write_into_the_boot_sweep_is_flagged(statement: str) -> None:
    planted = _plant_into(CLIENT_PATH.read_text(encoding="utf-8"), _SWEEP, statement)
    assert _sweep_violations(planted) != []


def test_the_sweep_is_called_from_connect_before_the_startup_evidence_refresh() -> None:
    fn = _function(CLIENT_PATH.read_text(encoding="utf-8"), "_connect")
    awaited = [
        firewall._dotted_callee(n.value.func)
        for n in ast.walk(fn)
        if isinstance(n, ast.Await) and isinstance(n.value, ast.Call)
    ]
    assert awaited.index(f"self.{_SWEEP}") < awaited.index(
        "self._refresh_startup_position_evidence"
    )


def test_planting_a_sender_call_beside_the_is_none_guard_in_the_sweep_is_flagged() -> None:
    source = CLIENT_PATH.read_text(encoding="utf-8")
    assert "self._order_sender is None" in ast.unparse(_function(source, _SWEEP))
    planted = _plant_into(source, _SWEEP, "x = self._order_sender")
    assert _sweep_violations(planted) != []
