"""AMBIG-LATCH-RESUME Phase B: the NO-SEND firewall delta (T42).

Authority: ``docs/plans/backlog/BACKLOG_PLANS_2026-10-03/
AMBIG-LATCH-RESUME_plan_r6.md`` section 2.8.7.

The no-id resolver adds code under ``exec/client.py``. Its safety argument is
that the NO-SEND firewall gains ADDITIONS ONLY and NO new egress callee. This
module is the independent proof: it re-derives the delta against literals
frozen from the tree BEFORE this item (``f45f5a65`` == ``be9b80da`` for these
files), pins what the new code may await, pins ``self._store_set`` to one call
site and one key, and proves each guard non-vacuous by planting.

It imports the firewall module read-only and edits nothing in it.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import textwrap
from pathlib import Path
from typing import Any, Final

import pytest

from tests.unit import test_execution_egress_firewall_guard as firewall
from tests.unit.ambig_latch_rig import PolymarketUSExecutionClient, client_module

CLIENT_PATH: Final[Path] = Path(client_module.__file__)
CLIENT_REL: Final[str] = "src/breezy/adapters/polymarket_us/exec/client.py"
NEW_FUNCTIONS: Final[tuple[str, ...]] = (
    "_resolve_no_id_intent",
    "_no_id_trade_activity",
    "_resolve_no_order",
    "_adopt_no_id_venue_order",
)

#: The 17 additions (plan 2.8.7, #1-#17), each with its reason in the plan.
NO_ID_RESOLVER_ADDITIONS: Final[frozenset[str]] = frozenset(
    {
        "self._resolve_no_id_intent",
        "self._no_id_trade_activity",
        "self._resolve_no_order",
        "self._adopt_no_id_venue_order",
        "no_id_aggressor_legs",
        "classify_no_id_evidence",
        "NoIdTradeJoin",
        "self.client_order_id_for",
        "VenueOrderId",
        "self._cache.order",
        "self._generate_submitted",
        "self.generate_order_rejected",
        "self._store_set",
        "dataclasses.replace",
        "adopted.to_bytes",
        "holding_delta_consistent",
        "manual_leg_net_effect",
    }
)
NO_ID_RESOLVER_COROUTINE_ADDITIONS: Final[frozenset[str]] = frozenset(NEW_FUNCTIONS)
NO_ID_PERMITTED_COROUTINE_ADDITIONS: Final[frozenset[str]] = frozenset(
    {"_resolve_no_id_intent", "_no_id_trade_activity"}
)

#: Frozen from the tree before this item.
PRE_RESOLVER_CALLEES = frozenset(
    {
        # WP-DR (2026-10-10): a pure date function, no I/O, no egress. ONE
        # named row added to the baseline; the delta stays pinned by `==`.
        "utc_day_for_ns",
        # EXEC-PAR WP4 (r5 5.WP4, r5.1 E2): NAMED rows added to the baseline,
        # never relaxed (L-12) -- local-state calls only (the slot table, the
        # exposure registry, a pure leg-magnitude helper). `true_up_booking`
        # (replaced by `settle`) left the resolver and is removed.
        "self._latch.next_open_for_resolution",
        "self._latch.is_open_intent",
        "self._latch.max_slots",
        "self._latch.open_slot_count",
        "self._ledger.settle",
        "self._ledger.abandon_open_exposure",
        "_leg_magnitude_of_signed_net",
        "AmbiguousResolverContext.from_bytes",
        "ClientOrderId",
        "DurableFillRecord",
        "InstrumentId.from_str",
        "Money",
        "StrategyId",
        "TradeJoin",
        "UUID4",
        "_redact_order_id",
        "_resolver_leg_holding_qty",
        "_resolver_long_position_state",
        "_synthetic_get_fill_trade_id",
        "asyncio.sleep",
        "base_slug_of",
        "bool",
        "fill_record_bytes.decode",
        "instrument.make_price",
        "isinstance",
        "leg_of",
        "len",
        "max",
        "order_payload.get",
        "page.get",
        "page_min_create_ts_ns",
        "parse_order_status_report",
        "range",
        "record.to_bytes",
        "report.filled_qty.as_decimal",
        "report.quantity.as_decimal",
        "restore_live_trading_budget",
        "self._ambiguous_bookings.pop",
        "self._budget_was_restored",
        "self._cache.add_instrument",
        "self._cache.instrument",
        "self._clock.timestamp_ns",
        "self._declared_positions",
        "self._durable_net_qty",
        "self._instrument_provider.list_all",
        "self._latch.current_open",
        "self._log.debug",
        "self._log.error",
        "self._log.info",
        "self._log.warning",
        "self._loop.run_in_executor",
        "self._mark_budget_restored",
        "self._note_open_orders_outcome",
        "self._note_resolver_error",
        "self._order_trade_activity",
        "self._private_read",
        "self._read_open_orders",
        "self._refuse",
        "self._resolve_accept_fill",
        "self._resolve_terminal_zero",
        "self._resolver_fill_order_unknown",
        "self._resolver_instrument_loader",
        "self._resolver_poll_interval_secs",
        "self._retire",
        "self._set_resolver_last_failure_kind",
        "self._store_get",
        "self._write_startup_position_evidence",
        "self.generate_order_canceled",
        "self.generate_order_filled",
        "self.record_fill",
        "self.record_venue_order_id",
        "submit_chain.order_by_id_path",
        "submit_chain.venue_order_id",
        "sum",
        "trade_refs.extend",
        "trade_rows_for_order",
        "type",
        "unrestore_live_trading_budget",
    }
)

PRE_RESOLVER_COROUTINES = frozenset(
    {
        "_order_trade_activity",
        "_resolve_accept_fill",
        "_resolve_ambiguous_intents",
        "_resolve_terminal_zero",
    }
)

PRE_PERMITTED_COROUTINES = frozenset(
    {
        "__call__",
        "_batch_cancel_orders",
        "_cancel_all_orders",
        "_cancel_order",
        "_cancel_resolver_task",
        "_confirm_account_registered",
        "_connect",
        "_disconnect",
        "_modify_order",
        "_order_trade_activity",
        "_publish_account_state",
        "_query_account",
        "_query_order",
        "_read_open_orders",
        "_refresh_startup_position_evidence",
        "_resolve_ambiguous_intents",
        "_submit_order",
        "_submit_order_list",
        "_wait_for_instruments",
        "generate_fill_reports",
        "generate_mass_status",
        "generate_order_status_report",
        "generate_order_status_reports",
        "generate_position_status_reports",
    }
)

PRE_ORDER_CALLEES = frozenset(
    {
        "DurableFillRecord",
        "NotImplementedError",
        "PolymarketUSError",
        "_AdapterExitAuthorization",
        "assert_live_order_submission_permitted",
        "authorization.consume",
        "fill_record_bytes.decode",
        "leg_of",
        "record.to_bytes",
        "self._cache.account_for_venue",
        "self._cache.instrument",
        "self._clock.timestamp_ns",
        "self._deny",
        "self._generate_submitted",
        "self._latch.retire",
        "self._ledger.authorize_order_cost",
        "self._ledger.release_booking",
        # EXEC-PAR WP4 (r5 5.WP4, r5.1 E2/E10'/E11): NAMED rows added to the
        # baseline, never relaxed (L-12). `arm`, `is_latched` and
        # `true_up_booking` (replaced by `arm_slot`, `admission_refusal` and
        # `settle`) left the order coroutine and are removed.
        "base_slug_of",
        "self._latch.admission_refusal",
        "self._latch.arm_slot",
        "self._latch.max_slots",
        "self._ledger.exposure_admission_refusal",
        "self._ledger.register_open_exposure",
        "self._ledger.mark_ambiguous",
        "self._ledger.settle",
        "self._ledger.abandon_open_exposure",
        "self._log.error",
        "self._log.warning",
        "self._mark_budget_exhausted",
        "self._note_ambiguous_open",
        "self._order_sender.post_order",
        "self._refuse",
        "self._retire",
        "self._submit_veto",
        "self._unsupported",
        "self._write_signer.sign_headers",
        "self.generate_order_cancel_rejected",
        "self.generate_order_canceled",
        "self.generate_order_denied",
        "self.generate_order_filled",
        "self.generate_order_rejected",
        "self.generate_order_submitted",
        "self.record_fill",
        "self.record_venue_order_id",
        "submit_chain.build_exit_order_body",
        "submit_chain.build_order_body",
        "submit_chain.classify_create_order_outcome",
        "submit_chain.create_fill_evidence",
        "submit_chain.encode_order_body",
        "submit_chain.intent_fingerprint",
        "submit_chain.is_cancelled",
        "submit_chain.is_latch_arm_refusal",
        "submit_chain.latched_refusal_reason",
        "submit_chain.missing_account_reason",
        "submit_chain.order_notional_usd",
        "submit_chain.order_price_decimal",
        "submit_chain.order_quantity_decimal",
        "submit_chain.permit_is_missing",
        "submit_chain.retirement_member",
        "submit_chain.unmappable_exit_order_reason",
        "submit_chain.unmappable_order_reason",
        "submit_chain.venue_order_id",
        "submit_chain.wire_fingerprint_bytes",
    }
)

PRE_ORDER_COROUTINES = frozenset(
    {
        "_batch_cancel_orders",
        "_cancel_all_orders",
        "_cancel_order",
        "_modify_order",
        "_submit_order",
        "_submit_order_list",
    }
)

#: sha256 of ``inspect.getsource`` at the base commit: these are claimed
#: byte-unchanged by this item (plan section 4 "Not touched").
FROZEN_SOURCE_SHA256: Final[dict[str, str]] = {
    "_activity_create_ts_ns": "9b24fabe0bfba9e06cd03397c508eaf49b38f80ef3e43df85bc53510f7f177a5",
    "_order_trade_activity": "466f891618ea2d2a2ce85185d9d8cd22f95f38400c9c3d9c774537b483adf97e",
    "build_exit_order_body": "33a2b7515a2a0029cee73c444749d4992297da7c533bd184d2a63e670b97864b",
    "build_order_body": "34bc594a86dafbc55834024f92c53b9a9229ca2ec5a6e86f652bf51e137a040b",
    "classify_create_order_outcome": (
        "8c06a33a4d0e02f3c91a06a6b0222dec0c72f84d030a9227c7a498e19f640db1"
    ),
    "page_min_create_ts_ns": "f18d729e58e346cfe3d88ab5982f696758bb3854f37f803eba90e6fae2459e17",
}

#: ``ast.dump`` of ``_submit_order`` up to and including the ``arm`` try block.
#: Re-pinned by EXEC-PAR WP4 (reviewer-approved with the exec client's own pin):
#: the per-slug admission, the open-exposure pre-check, the two body pins, the
#: `arm_slot` call and the registration all sit INSIDE this prefix by design.
SUBMIT_PREFIX_SHA256: Final[str] = (
    "4183d5f475c62f6f7ccdea387cc7bce051063935400a83492d21441e52aec6eb"
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _client_tree(source: str | None = None) -> ast.Module:
    return ast.parse(CLIENT_PATH.read_text(encoding="utf-8") if source is None else source)


def _function(tree: ast.AST, name: str) -> ast.AST:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} is not defined in client.py")


def _dotted(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return None if base is None else f"{base}.{node.attr}"
    return None


def _calls(fn: ast.AST) -> list[ast.Call]:
    return [n for n in ast.walk(fn) if isinstance(n, ast.Call)]


def _store_set_sites(tree: ast.AST) -> list[tuple[str, ast.Call]]:
    """``self._store_set`` calls inside the scanned resolver bodies."""
    sites: list[tuple[str, ast.Call]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and (
            node.name in firewall.EXEC_RESOLVER_COROUTINES
        ):
            sites.extend(
                (node.name, call)
                for call in _calls(node)
                if _dotted(call.func) == "self._store_set"
            )
    return sites


def _plant(source: str, function: str, statement: str) -> str:
    tree = ast.parse(source)
    target = _function(tree, function)
    target.body.insert(0, ast.parse(statement).body[0])  # type: ignore[attr-defined]
    return ast.unparse(ast.fix_missing_locations(tree))


# ---------------------------------------------------------------------------
# (i) additions only
# ---------------------------------------------------------------------------


def test_the_resolver_allowlist_gains_exactly_the_seventeen_named_callees() -> None:
    assert len(NO_ID_RESOLVER_ADDITIONS) == 17
    current = firewall.EXEC_RESOLVER_PERMITTED_CALLEES
    assert NO_ID_RESOLVER_ADDITIONS <= current
    assert current - NO_ID_RESOLVER_ADDITIONS == PRE_RESOLVER_CALLEES
    assert PRE_RESOLVER_CALLEES <= current, "additions only: nothing removed"


def test_the_scanned_coroutine_set_gains_exactly_the_four_names() -> None:
    current = firewall.EXEC_RESOLVER_COROUTINES
    assert NO_ID_RESOLVER_COROUTINE_ADDITIONS <= current
    assert current - NO_ID_RESOLVER_COROUTINE_ADDITIONS == PRE_RESOLVER_COROUTINES
    assert len(NO_ID_RESOLVER_COROUTINE_ADDITIONS) == 4


def test_the_inert_coroutine_name_list_gains_exactly_the_two_names() -> None:
    current = firewall.EXEC_PERMITTED_COROUTINE_NAMES
    assert NO_ID_PERMITTED_COROUTINE_ADDITIONS <= current
    assert current - NO_ID_PERMITTED_COROUTINE_ADDITIONS == PRE_PERMITTED_COROUTINES


def test_the_order_coroutine_allowlists_are_unchanged() -> None:
    assert firewall.EXEC_ORDER_COROUTINE_PERMITTED_CALLEES == PRE_ORDER_CALLEES
    assert firewall.ORDER_LIFECYCLE_COROUTINES == PRE_ORDER_COROUTINES


# ---------------------------------------------------------------------------
# (ii) no egress name anywhere
# ---------------------------------------------------------------------------


def test_no_send_name_is_in_any_resolver_set_and_the_new_names_are_not_send_shaped() -> None:
    sets = (
        firewall.EXEC_RESOLVER_PERMITTED_CALLEES,
        firewall.EXEC_RESOLVER_COROUTINES,
        firewall.EXEC_PERMITTED_COROUTINE_NAMES,
    )
    for scoped in sets:
        for banned in (
            "self._order_sender.post_order",
            "self._order_sender",
            "self._write_signer.sign_headers",
        ):
            assert banned not in scoped
    for name in NO_ID_RESOLVER_ADDITIONS | NO_ID_RESOLVER_COROUTINE_ADDITIONS:
        lowered = name.lower()
        assert not any(token in lowered for token in ("post", "send", "cancel")), name


# ---------------------------------------------------------------------------
# (iii) what the new code may await
# ---------------------------------------------------------------------------

ALLOWED_AWAIT_TARGETS: Final[frozenset[str]] = frozenset(
    {
        "self._private_read",
        "self._read_open_orders",
        "self._no_id_trade_activity",
        "self._resolve_no_id_intent",
    }
)
ALLOWED_READ_PATHS: Final[frozenset[str]] = frozenset(
    {"PORTFOLIO_POSITIONS_PATH", "PORTFOLIO_ACTIVITIES_PATH"}
)


def _await_violations(tree: ast.AST) -> list[str]:
    found: list[str] = []
    for name in NEW_FUNCTIONS:
        fn = _function(tree, name)
        for node in ast.walk(fn):
            if isinstance(node, ast.Await):
                value = node.value
                target = _dotted(value.func) if isinstance(value, ast.Call) else None
                if target not in ALLOWED_AWAIT_TARGETS:
                    found.append(f"{name}: await {target or ast.dump(value)[:40]}")
            if isinstance(node, ast.Call) and _dotted(node.func) == "self._private_read":
                arg0 = node.args[0] if node.args else None
                if not (isinstance(arg0, ast.Name) and arg0.id in ALLOWED_READ_PATHS):
                    found.append(f"{name}: _private_read({ast.dump(arg0)[:40] if arg0 else ''})")
    return found


def test_the_new_functions_await_only_the_existing_get_seams() -> None:
    assert _await_violations(_client_tree()) == []


# ---------------------------------------------------------------------------
# (iv) the single local write
# ---------------------------------------------------------------------------


def test_store_set_occurs_exactly_once_in_the_scanned_bodies_with_the_pinned_key() -> None:
    assert "_adopt_no_id_venue_order" in firewall.EXEC_RESOLVER_COROUTINES
    sites = _store_set_sites(_client_tree())
    assert [name for name, _ in sites] == ["_adopt_no_id_venue_order"]
    key = sites[0][1].args[0]
    assert ast.unparse(key) == "f'{RESOLVER_CONTEXT_KEY_PREFIX}{adopted.intent_id}'"


def test_the_real_client_has_no_resolver_violation() -> None:
    source = CLIENT_PATH.read_text(encoding="utf-8")
    assert firewall.find_exec_resolver_violations(CLIENT_REL, source) == []


# ---------------------------------------------------------------------------
# (v) non-vacuity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("function", NEW_FUNCTIONS)
def test_planting_a_post_order_call_into_each_new_function_fires_the_scanner(
    function: str,
) -> None:
    source = CLIENT_PATH.read_text(encoding="utf-8")
    planted = _plant(source, function, "self._order_sender.post_order(None)")
    violations = firewall.find_exec_resolver_violations(CLIENT_REL, planted)
    assert any(function in v.detail for v in violations), violations


def test_planting_a_second_store_set_fails_the_single_site_pin() -> None:
    source = CLIENT_PATH.read_text(encoding="utf-8")
    planted = _plant(source, "_resolve_no_order", "self._store_set('k', b'v')")
    names = [name for name, _ in _store_set_sites(ast.parse(planted))]
    assert names != ["_adopt_no_id_venue_order"]
    assert names.count("_resolve_no_order") == 1


def test_planting_a_foreign_await_fails_the_await_pin() -> None:
    source = CLIENT_PATH.read_text(encoding="utf-8")
    planted = _plant(source, "_resolve_no_id_intent", "await self._order_sender.post_order(None)")
    assert _await_violations(ast.parse(planted))


# ---------------------------------------------------------------------------
# (vi) the pre-POST helpers
# ---------------------------------------------------------------------------


def _names_and_attrs(fn: ast.AST) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Name):
            out.add(node.id)
        elif isinstance(node, ast.Attribute):
            out.add(node.attr)
    return out


def test_note_ambiguous_open_and_holding_baseline_are_await_free_and_egress_free() -> None:
    tree = _client_tree()
    for name in ("_note_ambiguous_open", "_holding_baseline"):
        fn = _function(tree, name)
        assert not any(
            isinstance(n, ast.Await | ast.AsyncFor | ast.AsyncWith | ast.AsyncFunctionDef)
            for n in ast.walk(fn)
        ), name
        assert isinstance(fn, ast.FunctionDef), f"{name} is a plain sync def"
        callees = {_dotted(c.func) for c in _calls(fn)}
        assert "self._private_read" not in callees
        assert "self._read_open_orders" not in callees
        touched = _names_and_attrs(fn)
        assert "_order_sender" not in touched and "_write_signer" not in touched
    note = [
        c
        for c in _calls(_function(tree, "_note_ambiguous_open"))
        if _dotted(c.func) == "self._store_set"
    ]
    base = [
        c
        for c in _calls(_function(tree, "_holding_baseline"))
        if _dotted(c.func) == "self._store_set"
    ]
    assert len(note) == 1 and base == []


def test_submit_order_gains_no_callee_beyond_the_unchanged_order_allowlist() -> None:
    tree = _client_tree()
    fn = _function(tree, "_submit_order")
    unknown = {
        _dotted(c.func) or ast.dump(c.func)[:40] for c in _calls(fn)
    } - firewall.EXEC_ORDER_COROUTINE_PERMITTED_CALLEES
    assert unknown == set(), unknown


def test_submit_order_prefix_through_arm_is_byte_identical_to_the_base() -> None:
    source = textwrap.dedent(inspect.getsource(PolymarketUSExecutionClient._submit_order))
    fn = ast.parse(source).body[0]
    assert isinstance(fn, ast.AsyncFunctionDef)
    index = next(
        i
        for i, st in enumerate(fn.body)
        if isinstance(st, ast.Try) and "self._latch.arm" in ast.unparse(st)
    )
    prefix = "\n".join(ast.dump(s) for s in fn.body[: index + 1])
    assert hashlib.sha256(prefix.encode()).hexdigest() == SUBMIT_PREFIX_SHA256


def _source_of(obj: Any) -> str:
    return inspect.getsource(obj)


def test_the_claimed_byte_unchanged_functions_are_byte_unchanged() -> None:
    import breezy.adapters.polymarket_us.account_activity as activity
    from tests.unit.ambig_latch_rig import submit_chain

    actual = {
        "classify_create_order_outcome": submit_chain.classify_create_order_outcome,
        "build_order_body": submit_chain.build_order_body,
        "build_exit_order_body": submit_chain.build_exit_order_body,
        "_order_trade_activity": PolymarketUSExecutionClient._order_trade_activity,
        "page_min_create_ts_ns": activity.page_min_create_ts_ns,
        "_activity_create_ts_ns": activity._activity_create_ts_ns,
    }
    digests = {
        name: hashlib.sha256(_source_of(obj).encode()).hexdigest() for name, obj in actual.items()
    }
    assert digests == FROZEN_SOURCE_SHA256
