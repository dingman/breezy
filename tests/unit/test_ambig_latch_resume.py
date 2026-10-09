"""AMBIG-LATCH-RESUME Phase B: the client leaves DEGRADED after a clear (T1-T8b,
T13-T16, T20-T25).

Authority: ``docs/plans/backlog/BACKLOG_PLANS_2026-10-03/
AMBIG-LATCH-RESUME_plan_r6.md`` sections 2.1-2.6 and 3.2.

The rig is ``tests/unit/ambig_latch_rig.py`` (no ``exec`` import here: barrier
X1 pins the importers by set equality). The client's ``_log`` and ``_clock``
are shadowed by the rig's :class:`TimedClient`, so a log line and a clock jump
are observable at run time.

No test here assigns a value to either operator-reserved control except
through the single whitelisted helper, exactly as the sibling exec suites do.
"""

from __future__ import annotations

import ast
import inspect
import sqlite3
import textwrap
from pathlib import Path
from typing import Any

import pytest
from nautilus_trader.common.enums import ComponentState
from nautilus_trader.common.messages import ComponentStateChanged
from nautilus_trader.model.events import OrderDenied

from breezy.adapters.polymarket_us.safety import live_trading_budget_remaining
from breezy.runtime.component_health_watch import (
    DEGRADED_ALERT_EVENT,
    install_component_degraded_alert,
)
from breezy.runtime.health import AlertPayload
from tests.unit import test_execution_egress_firewall_guard as firewall
from tests.unit.ambig_latch_rig import (
    PORTFOLIO_ACTIVITIES_PATH,
    PORTFOLIO_POSITIONS_PATH,
    PolymarketUSExecutionClient,
    RetirementReason,
    SubmitIntentState,
    TimedClient,
    boot_second_process,
    build_client,
    client_module,
    gate_env,  # noqa: F401 -- fixture
    make_command,
    prior_process,
    response_sender,
    rig_slug,
    run_passes,
    submit_chain,
    wire_payloads,
    write_canonical_verified,  # noqa: F401 -- fixture
)
from tests.unit.test_current_rung_hold_ambiguous_resolver import (
    _ambiguous_create_body,
    _backdate_resolver_context,
    _order_get_body,
)

ORDER_ID = "ord-amb-1"
AMBIGUOUS = submit_chain.AMBIGUOUS_REASON
RESUME_METHOD = "resume_if_refusals_cleared"


# ---------------------------------------------------------------------------
# Rig helpers
# ---------------------------------------------------------------------------


class _Sink:
    def __init__(self) -> None:
        self.payloads: list[AlertPayload] = []

    def emit(self, payload: AlertPayload) -> None:
        self.payloads.append(payload)


class _StateSpy:
    """Records every ``events.system.<id>`` publication of one component."""

    def __init__(self, client: Any) -> None:
        self.states: list[ComponentState] = []
        self.topics: list[str] = []
        self._component_id = str(client.id)
        client._msgbus.subscribe(topic="events.system.*", handler=self._on_event)

    def _on_event(self, event: object) -> None:
        if isinstance(event, ComponentStateChanged) and str(event.component_id) == (
            self._component_id
        ):
            self.states.append(event.state)


async def _armed_with_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, start: bool = True
) -> tuple[TimedClient, Any, Any, str]:
    """One with-id AMBIGUOUS intent on a started client; context aged past the
    zero-fill floor. Returns (client, sender, latch_cm, intent_id)."""
    sender = response_sender(200, _ambiguous_create_body(ORDER_ID))
    client, _events, _permit, latch_cm = await build_client(
        tmp_path, monkeypatch, sender=sender, start=start
    )
    await client._submit_order(make_command(client))
    current = client._latch.current_open()
    assert current is not None
    _backdate_resolver_context(client, current.intent_id)
    return client, sender, latch_cm, current.intent_id


def _terminal_zero_evidence(client: Any) -> None:
    payloads = wire_payloads(client)
    payloads[f"/v1/order/{ORDER_ID}"] = _order_get_body(
        ORDER_ID, slug=rig_slug(), state="ORDER_STATE_CANCELED", cum_quantity=0
    )
    payloads[PORTFOLIO_POSITIONS_PATH] = {"positions": {}, "eof": True}


def _fill_evidence(client: Any) -> None:
    payloads = wire_payloads(client)
    payloads[f"/v1/order/{ORDER_ID}"] = _order_get_body(
        ORDER_ID, slug=rig_slug(), state="ORDER_STATE_FILLED", cum_quantity=1, avg_px="0.40"
    )
    payloads[PORTFOLIO_POSITIONS_PATH] = {
        "positions": {rig_slug(): {"netPosition": "1"}},
        "eof": True,
    }


def _clear_like_the_resolver(client: Any) -> None:
    """What the inline clear block does to the client's own state (used where
    the test needs a clear without running a whole resolver pass)."""
    client._trading_refusals = [r for r in client._trading_refusals if r.reason != AMBIGUOUS]
    client._ambiguous_refusal_clears += 1


def _store_snapshot(client: Any, tmp_path: Path) -> list[tuple[str, bytes]]:
    path = tmp_path / "exec_state.db"
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return [(k, bytes(v)) for k, v in conn.execute("SELECT key, value FROM state ORDER BY key")]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# T1-T8b: the resume method
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_terminal_zero_clear_then_resume_returns_the_client_to_running(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate_env: None,  # noqa: F811
) -> None:
    client, _sender, _cm, _intent = await _armed_with_id(tmp_path, monkeypatch)
    assert client.is_degraded, "the AMBIGUOUS refusal degrades a RUNNING client"
    _terminal_zero_evidence(client)

    await run_passes(client, 1)

    assert client.resume_if_refusals_cleared() is True
    assert client.is_running
    assert not client.is_degraded
    assert client.ambiguous_refusal_clears == 1
    await client._disconnect()


@pytest.mark.asyncio
async def test_resume_refused_while_the_submit_intent_is_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate_env: None,  # noqa: F811
) -> None:
    client, _sender, _cm, _intent = await _armed_with_id(tmp_path, monkeypatch)
    client._trading_refusals = []  # the F6 shape: list empty, latch still OPEN
    assert client._latch.is_latched() is True

    assert client.resume_if_refusals_cleared() is False
    assert client.is_degraded
    await client._disconnect()


@pytest.mark.asyncio
async def test_resume_refused_when_the_latch_read_is_corrupt_or_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate_env: None,  # noqa: F811
) -> None:
    client, _sender, _cm, _intent = await _armed_with_id(tmp_path, monkeypatch)
    client._trading_refusals = []

    class _CorruptLatch:
        def is_latched(self) -> bool:
            return True  # a corrupt singleton reads as latched (fail closed)

    class _RaisingLatch:
        def is_latched(self) -> bool:
            raise RuntimeError("secret-looking detail must not be logged")

    real_latch = client._latch
    client._latch = _CorruptLatch()
    assert client.resume_if_refusals_cleared() is False
    assert client.is_degraded

    client._latch = _RaisingLatch()
    assert client.resume_if_refusals_cleared() is False
    assert client.is_degraded
    warnings = client.log_lines("warning", "RuntimeError")
    assert len(warnings) == 1
    assert "secret-looking detail" not in warnings[0], "the type name only"
    client._latch = real_latch
    await client._disconnect()


@pytest.mark.asyncio
async def test_resume_is_a_no_op_unless_degraded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate_env: None,  # noqa: F811
) -> None:
    sender = response_sender(200, _ambiguous_create_body(ORDER_ID))
    client, _events, _permit, _cm = await build_client(
        tmp_path, monkeypatch, sender=sender, start=True
    )
    spy = _StateSpy(client)

    # (i) RUNNING: False, and nothing is published.
    assert client.is_running
    assert client.resume_if_refusals_cleared() is False
    assert spy.states == []
    assert client.is_running

    # (iii) DEGRADING: the handler (re-entrant on the synchronous publish)
    # empties the list and calls the method; the STATE guard alone refuses.
    seen: list[tuple[bool, ComponentState]] = []

    def _on_degrading(event: object) -> None:
        if (
            isinstance(event, ComponentStateChanged)
            and str(event.component_id) == str(client.id)
            and event.state == ComponentState.DEGRADING
        ):
            client._trading_refusals = []
            seen.append((client.resume_if_refusals_cleared(), client.state))

    client._msgbus.subscribe(topic="events.system.*", handler=_on_degrading)
    client._refuse("unrelated reason A")
    assert seen == [(False, ComponentState.DEGRADING)]
    assert client.is_degraded

    # (iv) a remaining unrelated refusal -> False.
    client._trading_refusals = []
    client._refuse("unrelated reason B")
    assert client.resume_if_refusals_cleared() is False

    # (v) no latch bound -> fail closed.
    client._trading_refusals = []
    real_latch = client._latch
    client._latch = None
    assert client.resume_if_refusals_cleared() is False
    client._latch = real_latch

    # (ii) STOPPED stays STOPPED: (STOPPED, RESUME) is a legal native edge, so
    # only the is_degraded guard prevents it.
    client.resume()
    assert client.is_running
    client.stop()
    assert client.state == ComponentState.STOPPED
    assert client.resume_if_refusals_cleared() is False
    assert client.state == ComponentState.STOPPED
    await client._disconnect()


def _callees(fn_node: ast.AST) -> set[str]:
    out: set[str] = set()

    def _dotted(node: ast.expr) -> str | None:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            base = _dotted(node.value)
            return None if base is None else f"{base}.{node.attr}"
        return None

    for node in ast.walk(fn_node):
        if isinstance(node, ast.Call):
            name = _dotted(node.func)
            out.add(name if name is not None else ast.dump(node.func)[:40])
    return out


def _method_ast(name: str) -> ast.AST:
    member = inspect.getattr_static(PolymarketUSExecutionClient, name)
    function = member.fget if isinstance(member, property) else member
    return ast.parse(textwrap.dedent(inspect.getsource(function))).body[0]


def test_resume_method_callee_set_is_exactly_pinned() -> None:
    method = _method_ast(RESUME_METHOD)
    assert _callees(method) == {
        "self._latch.is_latched",
        "self.resume",
        "self.degrade",
        "self._log.info",
        "self._log.warning",
    }
    assert isinstance(method, ast.FunctionDef), "a sync def"
    assert not any(
        isinstance(n, ast.Await | ast.AsyncFor | ast.AsyncWith) for n in ast.walk(method)
    )
    prop = _method_ast("ambiguous_refusal_clears")
    assert _callees(prop) == set(), "the counter property has no callee"
    # non-vacuity: a planted send path changes the set
    planted = ast.parse(
        textwrap.dedent(inspect.getsource(getattr(PolymarketUSExecutionClient, RESUME_METHOD)))
        + "\n"
    )
    planted.body[0].body.append(  # type: ignore[attr-defined]
        ast.parse("self._order_sender.post_order()").body[0]
    )
    assert "self._order_sender.post_order" in _callees(planted)
    assert _callees(planted) != _callees(method)


def test_resume_and_degrade_actions_are_the_native_no_ops() -> None:
    for name in ("_resume", "_degrade"):
        owners = [c.__name__ for c in PolymarketUSExecutionClient.__mro__ if name in vars(c)]
        assert owners == ["Component"], (name, owners)


@pytest.mark.asyncio
async def test_resume_publishes_only_the_component_state_topic_and_never_reaches_the_sender(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate_env: None,  # noqa: F811
) -> None:
    client, sender, _cm, _intent = await _armed_with_id(tmp_path, monkeypatch)
    _terminal_zero_evidence(client)
    await run_passes(client, 1)
    calls_before = len(sender.calls)
    topics: list[str] = []
    states: list[ComponentState] = []

    def _any(event: object) -> None:
        topics.append(type(event).__name__)
        if isinstance(event, ComponentStateChanged):
            states.append(event.state)

    client._msgbus.subscribe(topic="*", handler=_any)
    assert client.resume_if_refusals_cleared() is True

    assert set(topics) == {"ComponentStateChanged"}
    assert states == [ComponentState.RESUMING, ComponentState.RUNNING]
    assert len(sender.calls) == calls_before
    await client._disconnect()


def test_the_resume_method_name_is_outside_every_firewall_scope() -> None:
    names = {RESUME_METHOD, "ambiguous_refusal_clears"}
    for scoped in (
        firewall.ORDER_LIFECYCLE_COROUTINES,
        firewall.EXEC_RESOLVER_COROUTINES,
        firewall.EXEC_PERMITTED_COROUTINE_NAMES,
    ):
        assert not (names & set(scoped))
    for allowlist in (
        firewall.EXEC_ORDER_COROUTINE_PERMITTED_CALLEES,
        firewall.EXEC_RESOLVER_PERMITTED_CALLEES,
    ):
        for banned in ("self.resume", "self.degrade", f"self.{RESUME_METHOD}"):
            assert banned not in allowlist


def test_the_resume_method_exists_as_a_sync_method_on_the_client() -> None:
    source = Path(client_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    cls = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.ClassDef) and n.name == "PolymarketUSExecutionClient"
    )
    order = [n.name for n in cls.body if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)]
    assert RESUME_METHOD in order
    assert isinstance(
        next(n for n in cls.body if getattr(n, "name", "") == RESUME_METHOD), ast.FunctionDef
    )
    assert order.index(RESUME_METHOD) > order.index("_refuse")


# ---------------------------------------------------------------------------
# T13-T16: accept-fill clears the AMBIGUOUS refusal (A3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_accept_fill_retirement_clears_the_ambiguous_refusal_and_the_client_resumes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate_env: None,  # noqa: F811
) -> None:
    client, _sender, _cm, intent_id = await _armed_with_id(tmp_path, monkeypatch)
    _fill_evidence(client)

    await run_passes(client, 1)

    current = client._latch.current()
    assert current is not None
    assert current.state is SubmitIntentState.RETIRED
    assert current.retirement_reason is not None
    assert current.retirement_reason.value == "STATUS_REPORT_ACCEPT_FILL_TERMINAL"
    assert AMBIGUOUS not in client.trading_refusals
    assert client.log_lines("info", "cleared the AMBIGUOUS trading refusal"), "INFO line"
    assert any("fill retirement" in line for line in client.log_lines("info", "cleared"))
    assert client.ambiguous_refusal_clears == 1
    assert client.resume_if_refusals_cleared() is True
    del intent_id
    await client._disconnect()


@pytest.mark.asyncio
async def test_accept_fill_clear_keeps_every_other_refusal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate_env: None,  # noqa: F811
) -> None:
    # (i) the venue-id map write raises -> its own refusal stays, resume False.
    client, _sender, _cm, _intent = await _armed_with_id(tmp_path, monkeypatch)
    _fill_evidence(client)

    def _boom(*_a: Any, **_k: Any) -> None:
        raise OSError("map write failed (rig)")

    monkeypatch.setattr(PolymarketUSExecutionClient, "record_venue_order_id", _boom)
    await run_passes(client, 1)
    assert client_module._VENUE_ID_MAP_WRITE_FAILED in client.trading_refusals
    assert client.resume_if_refusals_cleared() is False
    await client._disconnect()


@pytest.mark.asyncio
async def test_a_cross_process_unbudgeted_fill_refusal_survives_the_ambiguous_clear(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate_env: None,  # noqa: F811
) -> None:
    """ISOLATION test (not a reachable AMBIGUOUS state): both reasons present;
    the fill retirement removes ONLY the AMBIGUOUS one and counts one clear."""
    client, _sender, _cm, _intent = await _armed_with_id(tmp_path, monkeypatch)
    client._refuse(client_module._RESOLVER_FILL_UNBUDGETED)
    clears_before = client.ambiguous_refusal_clears
    _fill_evidence(client)

    await run_passes(client, 1)

    assert AMBIGUOUS not in client.trading_refusals
    assert client_module._RESOLVER_FILL_UNBUDGETED in client.trading_refusals
    assert client.ambiguous_refusal_clears == clears_before + 1
    await client._disconnect()


@pytest.mark.asyncio
async def test_a_raise_above_the_clear_keeps_the_ambiguous_refusal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate_env: None,  # noqa: F811
) -> None:
    # (i) record_fill raises -> AMBIGUOUS stays.
    client, _sender, _cm, _intent = await _armed_with_id(tmp_path, monkeypatch)
    _fill_evidence(client)

    def _boom(*_a: Any, **_k: Any) -> None:
        raise OSError("record_fill failed (rig)")

    monkeypatch.setattr(PolymarketUSExecutionClient, "record_fill", _boom)
    await run_passes(client, 1)
    assert AMBIGUOUS in client.trading_refusals
    await client._disconnect()


@pytest.mark.asyncio
async def test_generate_order_filled_raising_keeps_the_ambiguous_refusal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate_env: None,  # noqa: F811
) -> None:
    client, _sender, _cm, _intent = await _armed_with_id(tmp_path, monkeypatch)
    _fill_evidence(client)

    def _boom(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("generate_order_filled failed (rig)")

    monkeypatch.setattr(PolymarketUSExecutionClient, "generate_order_filled", _boom)
    await run_passes(client, 1)
    assert AMBIGUOUS in client.trading_refusals
    await client._disconnect()


def test_ambiguous_refusal_producers_are_only_in_submit_order_and_the_count_is_unchanged() -> None:
    source = Path(client_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    owners: list[str] = []
    total = 0

    class _V(ast.NodeVisitor):
        def __init__(self) -> None:
            self.stack: list[str] = []

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

        def visit_Call(self, node: ast.Call) -> None:
            nonlocal total
            if (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "_refuse"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "self"
            ):
                total += 1
                arg = node.args[0] if node.args else None
                if isinstance(arg, ast.Attribute) and arg.attr == "AMBIGUOUS_REASON":
                    owners.append(self.stack[-1])
            self.generic_visit(node)

    _V().visit(tree)
    assert owners and set(owners) == {"_submit_order"}
    assert total == 35, "r4/r6 adds no _refuse call site anywhere (the 25-producer pin)"


@pytest.mark.asyncio
async def test_after_an_accept_fill_clear_a_take_reaches_the_sender(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate_env: None,  # noqa: F811
) -> None:
    client, sender, _cm, _intent = await _armed_with_id(tmp_path, monkeypatch)
    _fill_evidence(client)
    await run_passes(client, 1)
    assert AMBIGUOUS not in client.trading_refusals
    _remaining_notional, remaining_count = live_trading_budget_remaining(client._permit)
    assert remaining_count == 1, "the fill keeps its permit slot spent"
    calls_before = len(sender.calls)
    sender.response = type(sender.response)(
        status=200, headers={}, body=_ambiguous_create_body("ord-2")
    )
    denied: list[Any] = []
    client._msgbus.subscribe(topic="*", handler=lambda e: denied.append(e))

    await client._submit_order(make_command(client))

    assert len(sender.calls) == calls_before + 1, "the second take is admitted and POSTs once"
    assert not [e for e in denied if isinstance(e, OrderDenied)]
    await client._disconnect()


# ---------------------------------------------------------------------------
# T20-T24: admission, races, F6
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resume_leaves_order_admission_unchanged_while_the_permit_is_invalid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate_env: None,  # noqa: F811
) -> None:
    client, sender, _cm, _intent = await _armed_with_id(tmp_path, monkeypatch)
    _terminal_zero_evidence(client)
    await run_passes(client, 1)
    assert client.trading_refusals == ()
    assert client.is_degraded
    client._permit = None
    calls = len(sender.calls)
    events: list[Any] = []
    client._msgbus.subscribe(topic="*", handler=events.append)

    await client._submit_order(make_command(client))
    before = [e.reason for e in events if isinstance(e, OrderDenied)]
    assert client.resume_if_refusals_cleared() is True
    await client._submit_order(make_command(client))
    after = [e.reason for e in events if isinstance(e, OrderDenied)]

    assert before == [submit_chain.PERMIT_ABSENT_REASON]
    assert after == [submit_chain.PERMIT_ABSENT_REASON] * 2, "identical deny reason after resume"
    assert len(sender.calls) == calls, "0 post_order"
    await client._disconnect()


@pytest.mark.asyncio
async def test_resume_writes_nothing_durable_and_leaves_a_set_family_halt_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate_env: None,  # noqa: F811
) -> None:
    client, _sender, _cm, _intent = await _armed_with_id(tmp_path, monkeypatch)
    _terminal_zero_evidence(client)
    await run_passes(client, 1)
    client._store_set("continuous_rung_hold/family_halt/test-family", b"halted")
    permit = client._permit
    before = _store_snapshot(client, tmp_path)

    assert client.resume_if_refusals_cleared() is True

    assert _store_snapshot(client, tmp_path) == before, "byte-identical store"
    assert client._permit is permit
    assert client._store_get("continuous_rung_hold/family_halt/test-family") == b"halted"
    await client._disconnect()


@pytest.mark.asyncio
async def test_a_refusal_during_resuming_ends_degraded_and_re_alerts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate_env: None,  # noqa: F811
) -> None:
    client, _sender, _cm, _intent = await _armed_with_id(tmp_path, monkeypatch)
    sink = _Sink()
    install_component_degraded_alert(
        client._msgbus,
        component_id=str(client.id),
        reasons=lambda: client.trading_refusals,
        sink=sink,
        ambiguous_reason=AMBIGUOUS,
        ambiguous_clears=lambda: client.ambiguous_refusal_clears,
    )
    _terminal_zero_evidence(client)
    await run_passes(client, 1)
    spy = _StateSpy(client)
    fired: list[bool] = []

    def _refuse_while_resuming(event: object) -> None:
        if (
            isinstance(event, ComponentStateChanged)
            and str(event.component_id) == str(client.id)
            and event.state == ComponentState.RESUMING
            and not fired
        ):
            fired.append(True)
            client._refuse("a refusal landing mid-resume (rig)")

    client._msgbus.subscribe(topic="events.system.*", handler=_refuse_while_resuming)

    assert client.resume_if_refusals_cleared() is False

    assert spy.states == [
        ComponentState.RESUMING,
        ComponentState.RUNNING,
        ComponentState.DEGRADING,
        ComponentState.DEGRADED,
    ]
    assert client.is_degraded
    assert len(client.log_lines("warning", "a refusal landed during RESUMING")) == 1
    assert len(sink.payloads) == 2, "the first episode, then the re-degrade"
    await client._disconnect()


@pytest.mark.asyncio
async def test_a_refusal_after_resume_re_degrades_and_re_alerts_subject_to_the_throttle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    gate_env: None,  # noqa: F811
) -> None:
    client, _sender, _cm, _intent = await _armed_with_id(tmp_path, monkeypatch)
    sink = _Sink()
    install_component_degraded_alert(
        client._msgbus,
        component_id=str(client.id),
        reasons=lambda: client.trading_refusals,
        sink=sink,
        ambiguous_reason=AMBIGUOUS,
        ambiguous_clears=lambda: client.ambiguous_refusal_clears,
    )
    assert len(sink.payloads) == 1  # episode 1 (AMBIGUOUS, a transition)
    caplog.set_level("WARNING")

    # (i) throttle and window, with a non-AMBIGUOUS reason.
    _clear_like_the_resolver(client)
    assert client.resume_if_refusals_cleared() is True
    client._refuse("reason B")
    assert len(sink.payloads) == 2, "a new reason set always alerts"
    client._trading_refusals = []
    assert client.resume_if_refusals_cleared() is True
    client._refuse("reason B")
    assert len(sink.payloads) == 2, "the same set inside 1 h is throttled"
    assert any("throttled" in r.message for r in caplog.records)

    # (ii) AMBIGUOUS twice inside the hour: both alert, no throttle WARNING.
    caplog.clear()
    client._trading_refusals = []
    assert client.resume_if_refusals_cleared() is True
    client._refuse(AMBIGUOUS)
    client._trading_refusals = []
    client._ambiguous_refusal_clears += 1
    assert client.resume_if_refusals_cleared() is True
    client._refuse(AMBIGUOUS)
    ambiguous_alerts = [p for p in sink.payloads if AMBIGUOUS in p.detail]
    assert len(ambiguous_alerts) == 3, "episode 1 plus the two later AMBIGUOUS episodes"
    assert not any("throttled" in r.message for r in caplog.records)
    await client._disconnect()


@pytest.mark.asyncio
async def test_a_second_ambiguous_inside_the_resume_window_refuses_resume_and_alerts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate_env: None,  # noqa: F811
) -> None:
    def _watch(client: Any, sink: _Sink) -> Any:
        return install_component_degraded_alert(
            client._msgbus,
            component_id=str(client.id),
            reasons=lambda: client.trading_refusals,
            sink=sink,
            ambiguous_reason=AMBIGUOUS,
            ambiguous_clears=lambda: client.ambiguous_refusal_clears,
        )

    # (a) the second AMBIGUOUS lands while still DEGRADED (clear done, no resume):
    (tmp_path / "a").mkdir()
    client, _s, _cm, _i = await _armed_with_id(tmp_path / "a", monkeypatch)
    sink_a = _Sink()
    handler_a = _watch(client, sink_a)
    assert len(sink_a.payloads) == 1
    _clear_like_the_resolver(client)
    client._refuse(AMBIGUOUS)  # no transition: already DEGRADED
    assert len(sink_a.payloads) == 1
    handler_a(object())  # the re-poll tick
    assert len(sink_a.payloads) == 2
    handler_a(object())
    assert len(sink_a.payloads) == 2, "exactly once per episode"
    assert client.resume_if_refusals_cleared() is False
    await client._disconnect()


@pytest.mark.asyncio
async def test_a_second_ambiguous_after_resume_alerts_by_transition_and_then_resumes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate_env: None,  # noqa: F811
) -> None:
    client, _s, _cm, _i = await _armed_with_id(tmp_path, monkeypatch)
    sink = _Sink()
    handler = install_component_degraded_alert(
        client._msgbus,
        component_id=str(client.id),
        reasons=lambda: client.trading_refusals,
        sink=sink,
        ambiguous_reason=AMBIGUOUS,
        ambiguous_clears=lambda: client.ambiguous_refusal_clears,
    )
    _clear_like_the_resolver(client)
    assert client.resume_if_refusals_cleared() is True
    client._refuse(AMBIGUOUS)  # a transition this time
    assert len(sink.payloads) == 2
    handler(object())
    assert len(sink.payloads) == 2, "the tick adds nothing: the transition already alerted"
    assert client.resume_if_refusals_cleared() is False
    _clear_like_the_resolver(client)
    assert client.resume_if_refusals_cleared() is True
    await client._disconnect()


@pytest.mark.asyncio
async def test_two_ambiguous_episodes_added_and_cleared_between_ticks_each_alert(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate_env: None,  # noqa: F811
) -> None:
    client, _s, _cm, _i = await _armed_with_id(tmp_path, monkeypatch)
    sink = _Sink()
    handler = install_component_degraded_alert(
        client._msgbus,
        component_id=str(client.id),
        reasons=lambda: client.trading_refusals,
        sink=sink,
        ambiguous_reason=AMBIGUOUS,
        ambiguous_clears=lambda: client.ambiguous_refusal_clears,
    )
    assert len(sink.payloads) == 1
    _clear_like_the_resolver(client)  # episode 1 cleared (counter 1)
    client._refuse(AMBIGUOUS)  # episode 2 added while DEGRADED ...
    _clear_like_the_resolver(client)  # ... and cleared before any tick (counter 2)
    client._refuse(AMBIGUOUS)  # episode 3, still present
    handler(object())
    assert len(sink.payloads) == 3, "one CRITICAL per owed episode"
    handler(object())
    assert len(sink.payloads) == 3
    assert all(p.event == DEGRADED_ALERT_EVENT for p in sink.payloads)
    assert client.resume_if_refusals_cleared() is False
    _clear_like_the_resolver(client)
    assert client.resume_if_refusals_cleared() is True
    await client._disconnect()


# ---------------------------------------------------------------------------
# T25: a node booted over a prior process's OPEN intent retires every shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_node_booted_over_prior_process_open_intents_retires_every_shape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate_env: None,  # noqa: F811
) -> None:
    slug = rig_slug()

    # (i) with-id + FILLED + LONG: the immediate pass retires, nothing refused.
    first, cm, _iid, _created = await prior_process(
        tmp_path / "i", monkeypatch, with_context="with_id", age_s=300
    )
    second, _cm2 = await boot_second_process(tmp_path / "i", monkeypatch, first, cm, admitted=True)
    payloads = wire_payloads(second)
    payloads[f"/v1/order/{ORDER_ID}"] = _order_get_body(
        ORDER_ID, slug=slug, state="ORDER_STATE_FILLED", cum_quantity=1, avg_px="0.40"
    )
    payloads[PORTFOLIO_POSITIONS_PATH] = {"positions": {slug: {"netPosition": "1"}}, "eof": True}
    await second._connect()
    current = second._latch.current()
    assert current is not None and current.state is SubmitIntentState.RETIRED
    assert current.retirement_reason is not None
    assert current.retirement_reason.value == "STATUS_REPORT_ACCEPT_FILL_TERMINAL"
    assert second.trading_refusals == ()
    await second._disconnect()

    # (ii) with-id terminal zero created 10 s before boot: not at the immediate
    # pass; retired by a periodic pass once 120 s old.
    first, cm, _iid, _created = await prior_process(
        tmp_path / "ii", monkeypatch, with_context="with_id", age_s=10
    )
    second, _cm2 = await boot_second_process(tmp_path / "ii", monkeypatch, first, cm, admitted=True)
    payloads = wire_payloads(second)
    payloads[f"/v1/order/{ORDER_ID}"] = _order_get_body(
        ORDER_ID, slug=slug, state="ORDER_STATE_CANCELED", cum_quantity=0
    )
    payloads[PORTFOLIO_POSITIONS_PATH] = {"positions": {}, "eof": True}
    await second._connect()
    assert second._latch.current_open() is not None
    second.advance(115)
    await run_passes(second, 1)
    assert second._latch.current_open() is None
    await second._disconnect()

    # (iii) INVERTED (CL1): a no-id r4 context created 10 s before boot. The
    # immediate pass makes no activities read; after created + 300 s a periodic
    # pass retires RESOLVER_NO_ID_NO_FILL with no restore (cross-process).
    first, cm, _iid, _created = await prior_process(
        tmp_path / "iii", monkeypatch, with_context="no_id", age_s=10
    )
    second, _cm2 = await boot_second_process(
        tmp_path / "iii", monkeypatch, first, cm, admitted=True
    )
    payloads = wire_payloads(second)
    payloads[PORTFOLIO_POSITIONS_PATH] = {"positions": {}, "eof": True}
    payloads[PORTFOLIO_ACTIVITIES_PATH] = {"activities": [], "eof": True}
    await second._connect()
    assert PORTFOLIO_ACTIVITIES_PATH not in second._private_read.paths
    assert second._latch.current_open() is not None
    second.advance(295)
    await run_passes(second, 1)
    assert second._latch.current_open() is None
    current = second._latch.current()
    assert current is not None and current.retirement_reason is not None
    assert current.retirement_reason.value == "RESOLVER_NO_ID_NO_FILL"
    assert second.log_lines("info", "cross-process")
    await second._disconnect()

    # (iv) INVERTED: OPEN with NO context key -- window-only mode retires it.
    first, cm, _iid, _created = await prior_process(
        tmp_path / "iv", monkeypatch, with_context=None, age_s=10
    )
    second, _cm2 = await boot_second_process(tmp_path / "iv", monkeypatch, first, cm, admitted=True)
    payloads = wire_payloads(second)
    payloads[PORTFOLIO_POSITIONS_PATH] = {"positions": {}, "eof": True}
    payloads[PORTFOLIO_ACTIVITIES_PATH] = {"activities": [], "eof": True}
    await second._connect()
    assert second._latch.current_open() is not None
    second.advance(295)
    await run_passes(second, 1)
    assert second._latch.current_open() is None
    await second._disconnect()
    assert RetirementReason.RESOLVER_NO_ID_NO_FILL.value == "RESOLVER_NO_ID_NO_FILL"
