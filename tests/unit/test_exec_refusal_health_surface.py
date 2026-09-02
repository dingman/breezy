"""R-6c: a refusal becomes a component state an operator can observe.

Authority: ``docs/plans/EXEC_SPINE_R5_R6_2026-09-02.md`` section R-6c
(Revision 3).

WHAT THIS INCREMENT ADDS, AND WHAT IT DELIBERATELY DOES NOT
------------------------------------------------------------
``PolymarketUSExecutionClient._refuse`` already logged at ERROR and already
exposed :attr:`~breezy.adapters.polymarket_us.exec.client.
PolymarketUSExecutionClient.trading_refusals`. What did not exist was a
MACHINE-READABLE signal: nothing turned a refusal into a component-state
change. R-6c drives the native FSM to ``DEGRADED`` on the FIRST refusal
(``Component.degrade``, ``$NT/common/component.pyx:2098-2127``, which
publishes ``ComponentStateChanged`` on ``events.system.<component_id>`` at
``:2210-2225``) and subscribes ONE operator-facing listener at the wiring
layer that turns that transition into exactly one alert through the existing
``AlertSink`` seam.

**DEGRADED is a health INDICATOR, not a kill switch, and R-6c does not wire
it to process exit.** The triage table below is why: seven of the twenty-five
refusal producers are ROUTINE -- they are true of a correctly-built Breezy
running against a healthy venue on an account the operator has ALSO traded by
hand. Stopping the process on any of them would turn an ordinary foreign
position into an outage. ``test_degrading_the_exec_client_does_not_stop_the_
node`` and
``test_neither_the_refusal_path_nor_the_watch_module_can_stop_the_process``
are the pins that keep it that way; their failure mode, from here on, is "a
later increment wired DEGRADED to exit".

THE TRIAGE (L-6), DERIVED FROM THE SCAN AND NOT INHERITED
----------------------------------------------------------
Revision 0 of the plan hand-enumerated these producers and listed 21 of 25 --
the misses included the non-long-position refusal, arguably the most
safety-relevant reason in the file. So the table below is keyed by the ids
:data:`REFUSAL_PRODUCERS` pins, ``test_every_pinned_refusal_producer_is_
triaged_here`` asserts the two sets are EQUAL, and the ids come out of the AST
scan rather than out of a reading.

Classification axis:

* **ROUTINE** -- can be true of a healthy, correctly-built Breezy against a
  healthy venue. It means the operator has state this bot did not create.
  It needs an operator, never an engineer, and never a process stop.
* **EXCEPTIONAL** -- something is genuinely broken: the venue, the host, the
  durable store, or Breezy itself. Still not a stop: the node must keep
  running and refusing so the operator can see it.

==================================  ============  ================================================
Producer id                         Triage        Why
==================================  ============  ================================================
_wait_for_instruments#1             EXCEPTIONAL   instrument load timed out; venue or host fault
_wait_for_instruments#2             EXCEPTIONAL   instrument load raised; venue or host fault
_wait_for_instruments#3             EXCEPTIONAL   zero instruments loaded; discovery is broken
_confirm_account_registered#1       EXCEPTIONAL   account never cached; every risk cap stays inert
generate_mass_status#1              EXCEPTIONAL   report generation raised; reconciliation is blind
generate_mass_status#2              EXCEPTIONAL   mass-status assembly rejected a report
generate_position_status_reports#1  EXCEPTIONAL   the venue position read failed
_map_position#1                     ROUTINE       a position in a market Breezy never loaded
_map_position#2                     EXCEPTIONAL   mapping a loadable position raised
_map_position#3                     ROUTINE       a NON-LONG venue position; Breezy is long-only
_find_instrument#1                  ROUTINE       a slug our symbology rejects; a foreign market
_entry_price#1                      ROUTINE       priced from the VENUE basis, not a Breezy fill
_entry_price#2                      EXCEPTIONAL   neither a fill record nor a basis can price it
_entry_price_from_records#1         ROUTINE       no durable fill record; the position is foreign
_entry_price_from_records#2         EXCEPTIONAL   our own fill record carries an unknown side
_entry_price_from_records#3         ROUTINE       venue size != our records; mixed hand/bot book
_entry_price_from_records#4         EXCEPTIONAL   our records net to a degenerate qty or cost
_entry_price_from_venue#1           EXCEPTIONAL   the venue cost-basis read failed
fill_records_for#1                  EXCEPTIONAL   the index names a record that does not exist
fill_records_for#2                  EXCEPTIONAL   a durable fill record is unreadable
_read_fill_index#1                  EXCEPTIONAL   the durable fill index is not valid JSON
_read_fill_index#2                  EXCEPTIONAL   the durable fill index is not a list of ids
calculate_commission#1              ROUTINE       a MAKER fill; Breezy is taker-only, so not ours
calculate_commission#2              EXCEPTIONAL   the fee schedule is UNKNOWN for this instrument
calculate_commission#3              EXCEPTIONAL   a reconciliation fill could not be priced
==================================  ============  ================================================

Seven ROUTINE, eighteen EXCEPTIONAL. Every one of the seven is reachable on
an account in perfectly good order, which is the whole argument for INDICATOR
over kill switch -- and one of them, ``_map_position#3``, is the non-long
position refusal Revision 0's hand count missed entirely.

NO ORDER PATH, NO EGRESS
-------------------------
Nothing here submits, cancels or sends anything. The exec client is driven
through the same rig ``tests/unit/test_polymarket_us_exec_client.py`` uses --
a real ``MessageBus``, ``Cache``, ``LiveClock`` and ``InstrumentProvider``
with an injected private read that opens no socket. ``_refuse`` is a local
latch, so every ``_connect`` refusal below is reachable with no network at
all. No test here assigns a value to either operator-reserved control.
"""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import pytest
from nautilus_trader.common.enums import ComponentState
from nautilus_trader.common.messages import ComponentStateChanged

from breezy.adapters.polymarket_us.exec.endpoints import PORTFOLIO_POSITIONS_PATH
from breezy.adapters.polymarket_us.exec_fault import fatal_exec_fault
from breezy.runtime.component_health_watch import (
    COMPONENT_STATE_TOPIC,
    DEGRADED_ALERT_EVENT,
    install_component_degraded_alert,
)
from breezy.runtime.health import AlertPayload
from tests.unit.test_polymarket_us_exec_client import _build_rig

if TYPE_CHECKING:  # pragma: no cover - typing only
    from tests.unit.test_polymarket_us_exec_client import _Rig

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
EXEC_CLIENT_PATH: Final[Path] = (
    REPO_ROOT / "src" / "breezy" / "adapters" / "polymarket_us" / "exec" / "client.py"
)
WATCH_MODULE_PATH: Final[Path] = (
    REPO_ROOT / "src" / "breezy" / "runtime" / "component_health_watch.py"
)

#: The EXACT set of ``self._refuse(...)`` producers in the execution client,
#: as ``"<enclosing function>#<ordinal within that function>"``.
#:
#: Keyed by function and ordinal rather than by LINE, deliberately. A line
#: pin fires on every unrelated edit above it -- noise that trains a reader to
#: re-bless the constant without looking, which is the exact failure L-6
#: exists to prevent. This shape fires on precisely the three changes that
#: demand a re-triage: a producer ADDED, a producer REMOVED, or a producer
#: MOVED between methods. Non-vacuity is proven mechanically by
#: ``test_planting_a_twenty_sixth_refusal_breaks_the_pin`` and
#: ``test_removing_a_refusal_breaks_the_pin``.
REFUSAL_PRODUCERS: Final[frozenset[str]] = frozenset(
    {
        "_wait_for_instruments#1",
        "_wait_for_instruments#2",
        "_wait_for_instruments#3",
        "_confirm_account_registered#1",
        "generate_mass_status#1",
        "generate_mass_status#2",
        "generate_position_status_reports#1",
        "_map_position#1",
        "_map_position#2",
        "_map_position#3",
        "_find_instrument#1",
        "_entry_price#1",
        "_entry_price#2",
        "_entry_price_from_records#1",
        "_entry_price_from_records#2",
        "_entry_price_from_records#3",
        "_entry_price_from_records#4",
        "_entry_price_from_venue#1",
        "fill_records_for#1",
        "fill_records_for#2",
        "_read_fill_index#1",
        "_read_fill_index#2",
        "calculate_commission#1",
        "calculate_commission#2",
        "calculate_commission#3",
    }
)

#: Anything that would turn DEGRADED into a stopped process. Banned outright
#: from the refusal path and from the watch module.
PROCESS_STOPPING_CALLEES: Final[frozenset[str]] = frozenset(
    {
        "self.shutdown_system",
        "self.stop",
        "self.fault",
        "sys.exit",
        "os._exit",
        "os.abort",
        "exit",
        "quit",
    }
)


# ---------------------------------------------------------------------------
# The AST scan
# ---------------------------------------------------------------------------


def _refusal_producers(source: str) -> set[str]:
    """Every ``self._refuse(...)`` site, as ``<function>#<ordinal>``."""
    tree = ast.parse(source)
    counts: Counter[str] = Counter()
    found: set[str] = set()

    def _walk(node: ast.AST, enclosing: str | None) -> None:
        for child in ast.iter_child_nodes(node):
            inner = enclosing
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                inner = child.name
            if isinstance(child, ast.Call):
                func = child.func
                if (
                    isinstance(func, ast.Attribute)
                    and func.attr == "_refuse"
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "self"
                ):
                    owner = enclosing or "<module>"
                    counts[owner] += 1
                    found.add(f"{owner}#{counts[owner]}")
            _walk(child, inner)

    _walk(tree, None)
    return found


def _triaged_producers() -> dict[str, str]:
    """The triage table in this module's docstring, parsed back out."""
    assert __doc__ is not None
    rows: dict[str, str] = {}
    for line in __doc__.splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        if parts[1] not in {"ROUTINE", "EXCEPTIONAL"}:
            continue
        rows[parts[0]] = parts[1]
    return rows


def test_the_refusal_producer_set_is_exactly_pinned() -> None:
    """L-6: the triage is made over the WHOLE producer set, mechanically.

    A new producer turns this red, forcing a triage rather than an
    inheritance of the previous one.
    """
    scanned = _refusal_producers(EXEC_CLIENT_PATH.read_text(encoding="utf-8"))
    assert scanned == set(REFUSAL_PRODUCERS), {
        "added": sorted(scanned - REFUSAL_PRODUCERS),
        "removed": sorted(REFUSAL_PRODUCERS - scanned),
    }
    assert len(scanned) == 25


def test_planting_a_twenty_sixth_refusal_breaks_the_pin() -> None:
    """Non-vacuity, half one: an ADDED producer must fire the pin."""
    source = EXEC_CLIENT_PATH.read_text(encoding="utf-8")
    planted = source.replace(
        '            self._refuse(f"the durable fill index at {key!r} is not valid JSON")',
        '            self._refuse(f"the durable fill index at {key!r} is not valid JSON")\n'
        '            self._refuse("planted 26th producer")',
        1,
    )
    assert planted != source, "the plant site moved; update this test's anchor"
    scanned = _refusal_producers(planted)
    assert scanned != set(REFUSAL_PRODUCERS)
    assert len(scanned) == 26


def test_removing_a_refusal_breaks_the_pin() -> None:
    """Non-vacuity, half two: a REMOVED producer must fire the pin too.

    A subset assertion would pass just as happily when the non-long-position
    refusal is deleted, which is the single most safety-relevant producer in
    the file.
    """
    source = EXEC_CLIENT_PATH.read_text(encoding="utf-8")
    removed = source.replace(
        "            self._refuse(\n"
        '                f"the venue reports a non-long position in {report.instrument_id}; "\n'
        '                "Breezy is long-only and cannot attribute it"\n'
        "            )\n",
        "            pass\n",
        1,
    )
    assert removed != source, "the removal site moved; update this test's anchor"
    scanned = _refusal_producers(removed)
    assert scanned != set(REFUSAL_PRODUCERS)
    assert "_map_position#3" not in scanned


def test_every_pinned_refusal_producer_is_triaged_here() -> None:
    """The table and the scan are the SAME set, or the triage is partial."""
    triaged = _triaged_producers()
    assert set(triaged) == set(REFUSAL_PRODUCERS), {
        "untriaged": sorted(REFUSAL_PRODUCERS - set(triaged)),
        "stale_rows": sorted(set(triaged) - REFUSAL_PRODUCERS),
    }
    counts = Counter(triaged.values())
    assert counts == {"EXCEPTIONAL": 18, "ROUTINE": 7}, counts


# ---------------------------------------------------------------------------
# The alert
# ---------------------------------------------------------------------------


def _install_watch(rig: _Rig, sink: Any) -> None:
    install_component_degraded_alert(
        rig.msgbus,
        component_id=str(rig.client.id),
        reasons=lambda: rig.client.trading_refusals,
        sink=sink,
    )


class _RecordingSink:
    """An `AlertSink` that keeps every payload it is handed."""

    def __init__(self) -> None:
        self.payloads: list[AlertPayload] = []

    def emit(self, payload: AlertPayload) -> None:
        self.payloads.append(payload)


@pytest.mark.asyncio
async def test_a_refusal_during_connect_emits_exactly_one_operator_alert(
    tmp_path: Path,
) -> None:
    """The subscriber ACTUALLY alerts -- the test Revision 0 lacked.

    Driven through the real client on a real ``MessageBus``: no instrument is
    loaded, so ``_wait_for_instruments`` refuses locally and ``_connect``
    reaches no network at all.
    """
    rig = _build_rig(tmp_path, instrument_loaded=False)
    sink = _RecordingSink()
    _install_watch(rig, sink)
    rig.client.start()
    assert rig.client.is_running

    await rig.client._connect()

    assert rig.client.trading_refusals != ()
    assert rig.client.is_degraded, "the first refusal must drive the native FSM to DEGRADED"
    assert len(sink.payloads) == 1, sink.payloads
    payload = sink.payloads[0]
    assert payload.event == DEGRADED_ALERT_EVENT
    assert payload.severity == "CRITICAL"
    assert str(rig.client.id) in payload.detail
    assert "instrument" in payload.detail, payload.detail

    await rig.client._disconnect()


@pytest.mark.asyncio
async def test_a_second_refusal_does_not_re_alert(tmp_path: Path) -> None:
    """The alert dedupes exactly as the ERROR log in `_refuse` already does.

    A per-reconcile loop that re-alerted would bury the operator under the
    same message, which is the failure the ERROR-log dedupe already prevents.
    """
    rig = _build_rig(tmp_path, instrument_loaded=False)
    sink = _RecordingSink()
    _install_watch(rig, sink)
    rig.client.start()

    await rig.client._connect()
    assert len(sink.payloads) == 1

    rig.read.raises[PORTFOLIO_POSITIONS_PATH] = RuntimeError("venue read failed")
    await rig.client.generate_position_status_reports()
    await rig.client.generate_position_status_reports()

    assert len(rig.client.trading_refusals) >= 2, rig.client.trading_refusals
    assert len(sink.payloads) == 1, sink.payloads

    await rig.client._disconnect()


@pytest.mark.asyncio
async def test_degrading_the_exec_client_does_not_stop_the_node(tmp_path: Path) -> None:
    """L-6: DEGRADED is an INDICATOR. Nothing about it ends the run.

    Three things are asserted together, and the FIRST is what makes the other
    two non-vacuous: without it this test would pass on a tree where
    ``degrade()`` is never called at all.

    1. the client really did reach DEGRADED;
    2. no ``ShutdownSystem`` command was published (``component.pyx:2170-2184``
       is the only native route from a component to a kernel stop);
    3. the process-exit latch ``breezy-trade`` reads in
       ``_exit_code_for_completed_run`` is still clear, so the run would still
       exit ``EXIT_OK``.
    """
    rig = _build_rig(tmp_path, instrument_loaded=False)
    shutdowns: list[Any] = []
    rig.msgbus.subscribe(topic="commands.system.*", handler=shutdowns.append)
    _install_watch(rig, _RecordingSink())
    rig.client.start()

    await rig.client._connect()

    assert rig.client.is_degraded
    assert shutdowns == []
    assert fatal_exec_fault() is None
    assert rig.client.trading_refusals != ()

    await rig.client._disconnect()


def test_neither_the_refusal_path_nor_the_watch_module_can_stop_the_process() -> None:
    """The structural half of L-6: no stop verb exists on either surface.

    The runtime test above proves this run did not stop. This proves no
    future edit can make the NEXT one stop without a reviewer seeing it.
    """
    offenders: list[str] = []
    for path in (EXEC_CLIENT_PATH, WATCH_MODULE_PATH):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        scopes = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        ]
        for scope in scopes:
            if path == EXEC_CLIENT_PATH and scope.name != "_refuse":
                continue
            for inner in ast.walk(scope):
                if not isinstance(inner, ast.Call):
                    continue
                callee = _dotted(inner.func)
                if callee in PROCESS_STOPPING_CALLEES:
                    offenders.append(f"{path.name}:{inner.lineno} {scope.name}() calls {callee}")
    assert offenders == [], offenders


def _imported_dotted_names(source: str) -> set[str]:
    """Every dotted name an import statement binds, module and member alike."""
    tree = ast.parse(source)
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
    return found


def _dotted(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return None if base is None else f"{base}.{node.attr}"
    return None


# ---------------------------------------------------------------------------
# The subscriber itself
# ---------------------------------------------------------------------------


def test_the_watch_subscribes_the_native_system_event_topic() -> None:
    """`degrade()` publishes to ``events.system.<component_id>``; the glob
    ``*`` is a ``MessageBus`` wildcard covering every component in the run."""
    assert COMPONENT_STATE_TOPIC == "events.system.*"


def test_a_degraded_transition_from_another_component_is_ignored() -> None:
    """One alert about the exec client is not an alert about everything."""
    from nautilus_trader.common.component import LiveClock, MessageBus
    from nautilus_trader.core.uuid import UUID4
    from nautilus_trader.model.identifiers import ClientId, TraderId

    trader_id = TraderId("BREEZY-R6C-001")
    msgbus = MessageBus(trader_id=trader_id, clock=LiveClock())
    sink = _RecordingSink()
    install_component_degraded_alert(
        msgbus,
        component_id="POLYMARKET_US",
        reasons=lambda: ("a reason",),
        sink=sink,
    )

    msgbus.publish(
        topic="events.system.SOMETHING_ELSE",
        msg=ComponentStateChanged(
            trader_id=trader_id,
            component_id=ClientId("SOMETHING_ELSE"),
            component_type="OtherClient",
            state=ComponentState.DEGRADED,
            config={},
            event_id=UUID4(),
            ts_event=0,
            ts_init=0,
        ),
    )
    assert sink.payloads == []


def test_a_non_degraded_transition_does_not_alert() -> None:
    """`degrade()` publishes DEGRADING first, then DEGRADED. Only the second
    is the operator's signal; alerting on both would double every alert."""
    from nautilus_trader.common.component import LiveClock, MessageBus
    from nautilus_trader.core.uuid import UUID4
    from nautilus_trader.model.identifiers import ClientId, TraderId

    trader_id = TraderId("BREEZY-R6C-001")
    msgbus = MessageBus(trader_id=trader_id, clock=LiveClock())
    sink = _RecordingSink()
    install_component_degraded_alert(
        msgbus,
        component_id="POLYMARKET_US",
        reasons=lambda: ("a reason",),
        sink=sink,
    )

    for state in (ComponentState.DEGRADING, ComponentState.RUNNING):
        msgbus.publish(
            topic="events.system.POLYMARKET_US",
            msg=ComponentStateChanged(
                trader_id=trader_id,
                component_id=ClientId("POLYMARKET_US"),
                component_type="PolymarketUSExecutionClient",
                state=state,
                config={},
                event_id=UUID4(),
                ts_event=0,
                ts_init=0,
            ),
        )
    assert sink.payloads == []


def test_a_broken_reasons_reader_still_alerts() -> None:
    """The alert is the point; the reasons are decoration on it.

    A reader that raises must not swallow the operator's only machine-readable
    notice that the client has stopped trusting itself.
    """
    from nautilus_trader.common.component import LiveClock, MessageBus
    from nautilus_trader.core.uuid import UUID4
    from nautilus_trader.model.identifiers import ClientId, TraderId

    def _boom() -> tuple[str, ...]:
        raise RuntimeError("reader failed")

    trader_id = TraderId("BREEZY-R6C-001")
    msgbus = MessageBus(trader_id=trader_id, clock=LiveClock())
    sink = _RecordingSink()
    install_component_degraded_alert(
        msgbus,
        component_id="POLYMARKET_US",
        reasons=_boom,
        sink=sink,
    )
    msgbus.publish(
        topic="events.system.POLYMARKET_US",
        msg=ComponentStateChanged(
            trader_id=trader_id,
            component_id=ClientId("POLYMARKET_US"),
            component_type="PolymarketUSExecutionClient",
            state=ComponentState.DEGRADED,
            config={},
            event_id=UUID4(),
            ts_event=0,
            ts_init=0,
        ),
    )
    assert len(sink.payloads) == 1
    assert "unavailable" in sink.payloads[0].detail


def test_a_failing_sink_never_unwinds_into_the_message_bus() -> None:
    """`emit_alert` contains ANY sink failure (`health.py:514-535`); this is
    the proof that the watch actually routes through it rather than calling
    `sink.emit` bare, which would abort the publishing component."""
    from nautilus_trader.common.component import LiveClock, MessageBus
    from nautilus_trader.core.uuid import UUID4
    from nautilus_trader.model.identifiers import ClientId, TraderId

    class _BrokenSink:
        def emit(self, payload: AlertPayload) -> None:
            raise RuntimeError("sink down")

    trader_id = TraderId("BREEZY-R6C-001")
    msgbus = MessageBus(trader_id=trader_id, clock=LiveClock())
    install_component_degraded_alert(
        msgbus,
        component_id="POLYMARKET_US",
        reasons=lambda: ("a reason",),
        sink=_BrokenSink(),
    )
    msgbus.publish(
        topic="events.system.POLYMARKET_US",
        msg=ComponentStateChanged(
            trader_id=trader_id,
            component_id=ClientId("POLYMARKET_US"),
            component_type="PolymarketUSExecutionClient",
            state=ComponentState.DEGRADED,
            config={},
            event_id=UUID4(),
            ts_event=0,
            ts_init=0,
        ),
    )


def test_the_wiring_installs_the_watch_at_the_same_point_as_the_order_guard() -> None:
    """R-6c's subscriber is a plain `msgbus.subscribe` in `trade_cli`, NOT an
    `Actor`: `actors=[]` in `build_trade_node_config` stays an untouched empty
    literal, and one wiring idiom is kept instead of two."""
    source = (REPO_ROOT / "src" / "breezy" / "runtime" / "trade_cli.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    run_node = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_run_node"
    )
    callees = [_dotted(inner.func) for inner in ast.walk(run_node) if isinstance(inner, ast.Call)]
    assert "node.build" in callees
    assert "install_live_order_guard" in callees
    assert "install_component_degraded_alert" in callees
    assert callees.index("install_component_degraded_alert") > callees.index("node.build")


def test_the_watch_module_is_outside_the_exec_package() -> None:
    """The barrier reason, restated as a test rather than as a comment.

    ``breezy.runtime.health`` is in
    ``test_execution_egress_firewall_guard.BANNED_EXEC_TRANSPORT_MODULES``:
    nothing under ``src/breezy/adapters/polymarket_us/exec/`` may import it,
    because it owns an `httpx` client. That constraint -- not taste -- is why
    the subscriber lives under ``runtime/``.
    """
    assert WATCH_MODULE_PATH.is_file()
    assert "adapters" not in WATCH_MODULE_PATH.parts
    # Over IMPORTS, not over text: the client's `_refuse` docstring CITES the
    # barrier by name, and a substring check would call that citation a
    # violation. The barrier itself scans imports for exactly this reason.
    imported = _imported_dotted_names(EXEC_CLIENT_PATH.read_text(encoding="utf-8"))
    assert not any(name.startswith("breezy.runtime.health") for name in imported), imported
    assert not any("component_health_watch" in name for name in imported), imported


def test_the_watch_module_reaches_no_venue_and_no_socket() -> None:
    """PORTABLE, as the plan labels R-6c: the subscriber names no venue and
    imports nothing that owns a socket, so Kalshi reuses it unchanged.

    ``polymarket`` specifically, because that string is also what barrier B4's
    C5 rule (``test_polymarket_us_readonly_guard._VENUE_NAME_RE``) classifies
    a module as venue-touching by. This module is not, and must not become,
    venue-touching. (The word "Kalshi" DOES appear -- in the portability claim
    at the top -- and is not a venue coupling.)
    """
    source = WATCH_MODULE_PATH.read_text(encoding="utf-8")
    assert "polymarket" not in source.lower()
    imported = _imported_dotted_names(source)
    for banned in ("httpx", "socket", "requests", "urllib.request", "aiohttp"):
        assert banned not in imported, banned
    assert "breezy.runtime.health.WebhookAlertSink" not in imported
