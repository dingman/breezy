"""EXEC-PAR WP5b: the supervisor-side breaker watch (dead watcher, trip, unreadable slot).

The supervisor cannot read the node's in-memory counters; it sees what the node
persists. ``probe_breaker_record`` is a read-only WAL read of the breaker record
and the slot table, run from the existing per-iteration permit-watch tick. At
K=1 (the configured constant) every check is inert: no alert, and no port is
touched beyond the two inert probe ports.
"""

from __future__ import annotations

import datetime as dt
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from breezy.runtime import trade_supervisor as ts
from breezy.runtime.breaker_supervisor_watch import (
    ABSENT_RECORD_GRACE_NS,
    BreakerAlertDetail,
    BreakerProbe,
    BreakerWatchState,
    decide_breaker_alerts,
)
from breezy.runtime.health import AlertPayload
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import BREAKER_KEY, CURRENT_INTENT_KEY
from breezy.runtime.submit_intent_slots import BreakerRecord, encode_breaker
from breezy.runtime.trade_supervisor import SupervisorPorts, probe_breaker_record
from breezy.runtime.trade_supervisor_core import AlertDetail

SEC = 1_000_000_000
NOW = 1_700_000_000 * SEC
FRESH = BreakerProbe(
    readable=True,
    present=True,
    halted=False,
    hb_ns=NOW - 5 * SEC,
    resolver_pass_ns=NOW - 5 * SEC,
    unreadable_slots=0,
)


class _Sink:
    def __init__(self) -> None:
        self.payloads: list[AlertPayload] = []

    def emit(self, payload: AlertPayload) -> None:
        self.payloads.append(payload)


def _no_spawn(*_a: object, **_kw: object) -> subprocess.Popen[bytes]:
    raise AssertionError("the breaker watch never spawns")


def _ports(sink: _Sink, **overrides: Any) -> SupervisorPorts:
    base = SupervisorPorts(
        find_node_pid=lambda: None,
        resolve_intent_lock_holder=lambda _p: None,
        intent_lock_free=lambda _p: True,
        count_intent_lock_holders=lambda _p: 0,
        terminate_after_recheck=lambda pid, **kw: None,
        process_alive=lambda _pid: True,
        probe_open_intent_state=lambda *a, **kw: False,
        spawn=_no_spawn,
        read_log_new=lambda _p: "",
        alert_sink=sink,
    )
    return replace(base, **overrides)


def _now() -> dt.datetime:
    return dt.datetime.fromtimestamp(NOW / SEC, tz=dt.UTC)


def _run(ports: SupervisorPorts, watch: BreakerWatchState, tracked_pid: int | None = 42) -> None:
    ts._dispatch_breaker_watch(
        ports=ports, watch=watch, now=_now(), tracked_pid=tracked_pid, store_path=Path("/nowhere")
    )


def _k(value: int) -> Any:
    return lambda: value


# ---------------------------------------------------------------------------
# probe_breaker_record: read-only WAL read
# ---------------------------------------------------------------------------


def test_probe_breaker_record_reads_the_record_without_writing(tmp_path: Path) -> None:
    path = tmp_path / "store.sqlite3"
    with SqliteStateStore(path) as store:
        store.set(
            BREAKER_KEY,
            encode_breaker(BreakerRecord("contradiction", 7, hb_ns=11, resolver_pass_ns=12)),
        )
        before = store.get(BREAKER_KEY)
    probe = probe_breaker_record(path)
    assert probe == BreakerProbe(
        readable=True, present=True, halted=True, hb_ns=11, resolver_pass_ns=12, unreadable_slots=0
    )
    with SqliteStateStore(path) as store:
        assert store.get(BREAKER_KEY) == before


def test_probe_breaker_record_absent_garbled_and_missing_store(tmp_path: Path) -> None:
    path = tmp_path / "store.sqlite3"
    with SqliteStateStore(path) as store:
        store.set(CURRENT_INTENT_KEY, b"not json")
    absent = probe_breaker_record(path)
    assert absent.readable and not absent.present
    with SqliteStateStore(path) as store:
        store.set(BREAKER_KEY, b"garbage")
    garbled = probe_breaker_record(path)
    assert not garbled.readable
    assert not probe_breaker_record(tmp_path).readable  # a directory is not a store


# ---------------------------------------------------------------------------
# decide_breaker_alerts
# ---------------------------------------------------------------------------


def test_dead_watcher_denies_entries_and_supervisor_alerts() -> None:
    stale = replace(FRESH, hb_ns=NOW - 61 * SEC)
    state = BreakerWatchState()
    specs = decide_breaker_alerts(
        probe=stale, k_configured=2, node_live=True, now_ns=NOW, state=state
    )
    assert [s.detail for s in specs] == [BreakerAlertDetail.BREAKER_WATCHER_DEAD]
    assert specs[0].severity == "CRITICAL"
    # the same episode does not re-alert on the next tick
    assert (
        decide_breaker_alerts(probe=stale, k_configured=2, node_live=True, now_ns=NOW, state=state)
        == []
    )
    # a recovery then a new episode alerts again
    assert (
        decide_breaker_alerts(probe=FRESH, k_configured=2, node_live=True, now_ns=NOW, state=state)
        == []
    )
    again = decide_breaker_alerts(
        probe=stale, k_configured=2, node_live=True, now_ns=NOW, state=state
    )
    assert [s.detail for s in again] == [BreakerAlertDetail.BREAKER_WATCHER_DEAD]


def test_dead_resolver_pass_alerts_and_the_backoff_cap_does_not() -> None:
    state = BreakerWatchState()
    capped = replace(FRESH, resolver_pass_ns=NOW - 300 * SEC)
    assert (
        decide_breaker_alerts(probe=capped, k_configured=2, node_live=True, now_ns=NOW, state=state)
        == []
    )
    dead = replace(FRESH, resolver_pass_ns=NOW - 601 * SEC)
    specs = decide_breaker_alerts(
        probe=dead, k_configured=2, node_live=True, now_ns=NOW, state=state
    )
    assert [s.detail for s in specs] == [BreakerAlertDetail.BREAKER_RESOLVER_PASS_STALE]


def test_absent_record_alerts_only_after_the_grace_with_a_live_node() -> None:
    absent = BreakerProbe(
        readable=True, present=False, halted=False, hb_ns=0, resolver_pass_ns=0, unreadable_slots=0
    )
    state = BreakerWatchState()
    assert (
        decide_breaker_alerts(probe=absent, k_configured=2, node_live=True, now_ns=NOW, state=state)
        == []
    )
    later = NOW + ABSENT_RECORD_GRACE_NS + 1
    specs = decide_breaker_alerts(
        probe=absent, k_configured=2, node_live=True, now_ns=later, state=state
    )
    assert [s.detail for s in specs] == [BreakerAlertDetail.BREAKER_WATCHER_DEAD]


def test_an_unreadable_record_with_a_live_node_alerts_dead_watcher() -> None:
    garbled = BreakerProbe(
        readable=False, present=False, halted=False, hb_ns=0, resolver_pass_ns=0, unreadable_slots=0
    )
    specs = decide_breaker_alerts(
        probe=garbled, k_configured=2, node_live=True, now_ns=NOW, state=BreakerWatchState()
    )
    assert [s.detail for s in specs] == [BreakerAlertDetail.BREAKER_WATCHER_DEAD]


def test_no_dead_watcher_alert_when_the_node_is_not_live() -> None:
    stale = replace(FRESH, hb_ns=NOW - 3600 * SEC, resolver_pass_ns=NOW - 3600 * SEC)
    assert (
        decide_breaker_alerts(
            probe=stale, k_configured=2, node_live=False, now_ns=NOW, state=BreakerWatchState()
        )
        == []
    )


def test_breaker_trip_alerts_once_and_unreadable_slot_alerts_at_any_k() -> None:
    state = BreakerWatchState()
    halted = replace(FRESH, halted=True, unreadable_slots=1)
    specs = decide_breaker_alerts(
        probe=halted, k_configured=1, node_live=True, now_ns=NOW, state=state
    )
    assert sorted(s.detail.value for s in specs) == sorted(
        [
            BreakerAlertDetail.BREAKER_ENTRY_HALT_LATCHED.value,
            BreakerAlertDetail.SLOT_TABLE_UNREADABLE_SLOT.value,
        ]
    )
    assert (
        decide_breaker_alerts(probe=halted, k_configured=1, node_live=True, now_ns=NOW, state=state)
        == []
    )


def test_k1_stale_record_never_raises_a_dead_watcher_alert() -> None:
    stale = replace(FRESH, hb_ns=0, resolver_pass_ns=0)
    assert (
        decide_breaker_alerts(
            probe=stale, k_configured=1, node_live=True, now_ns=NOW, state=BreakerWatchState()
        )
        == []
    )


# ---------------------------------------------------------------------------
# The dispatch inside the supervisor tick
# ---------------------------------------------------------------------------


def test_dispatch_emits_the_alert_through_the_existing_sink() -> None:
    sink = _Sink()
    stale = replace(FRESH, hb_ns=NOW - 120 * SEC)
    ports = _ports(sink, probe_breaker_record=lambda _p: stale, configured_exec_par_k=_k(2))
    _run(ports, BreakerWatchState())
    (payload,) = sink.payloads
    assert payload.detail == BreakerAlertDetail.BREAKER_WATCHER_DEAD.value
    assert payload.event == "TRADE_SUPERVISOR_BREAKER_WATCHER_DEAD"


def test_dispatch_is_contained_when_the_probe_raises() -> None:
    sink = _Sink()

    def boom(_p: Path) -> BreakerProbe:
        raise RuntimeError("wal read blew up")

    _run(_ports(sink, probe_breaker_record=boom, configured_exec_par_k=_k(2)), BreakerWatchState())
    assert sink.payloads == []


def test_k1_dispatch_touches_no_process_port_and_emits_nothing() -> None:
    sink = _Sink()
    touched: list[str] = []

    def alive(_pid: int) -> bool:
        touched.append("process_alive")
        return True

    def find() -> int | None:
        touched.append("find_node_pid")
        return 1

    ports = _ports(sink, process_alive=alive, find_node_pid=find)  # inert default probe ports
    _run(ports, BreakerWatchState(), tracked_pid=None)
    _run(ports, BreakerWatchState(), tracked_pid=42)
    assert touched == []
    assert sink.payloads == []


def test_default_ports_wire_the_real_probe_and_the_configured_k() -> None:
    ports = ts.default_ports(alert_sink=_Sink())
    assert ports.probe_breaker_record is probe_breaker_record
    assert ports.configured_exec_par_k() == 1


def test_default_fake_port_sets_are_inert() -> None:
    ports = _ports(_Sink())
    assert ports.configured_exec_par_k() == 1
    assert ports.probe_breaker_record(Path("/nowhere")).present is False


def test_alert_detail_enum_pin_green() -> None:
    new = (
        BreakerAlertDetail.BREAKER_WATCHER_DEAD,
        BreakerAlertDetail.BREAKER_RESOLVER_PASS_STALE,
        BreakerAlertDetail.BREAKER_ENTRY_HALT_LATCHED,
        BreakerAlertDetail.SLOT_TABLE_UNREADABLE_SLOT,
    )
    for member in new:
        assert member.value == member.value.lower()
        assert len(member.value) < 80
        assert "operator" not in member.value
    # The supervisor-core enum is untouched (it sits inside the autonomy
    # code-identity closure), so its own exhaustive pins stay green unchanged.
    assert not {m.value for m in new} & {m.value for m in AlertDetail}
    for core_member in AlertDetail:
        assert core_member.value == core_member.value.lower()
        assert len(core_member.value) < 80


@pytest.mark.parametrize("name", ["probe_breaker_record", "configured_exec_par_k"])
def test_supervisor_ports_carry_the_new_ports(name: str) -> None:
    assert name in SupervisorPorts.__dataclass_fields__
