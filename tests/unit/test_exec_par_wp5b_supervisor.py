"""EXEC-PAR WP5b: the supervisor-side breaker watch (dead watcher, trip, unreadable slot).

The supervisor cannot read the node's in-memory counters; it sees what the node
persists. ``probe_breaker_record`` is a read-only (``mode=ro``) read of the
breaker record and the slot table, run from the existing per-iteration tick.
K is read first: at the configured K=1 the tick returns before any store is
opened, because a K=1 node writes v1 bytes and never a breaker record.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from breezy.runtime import trade_supervisor as ts
from breezy.runtime.breaker_supervisor_watch import (
    ABSENT_RECORD_GRACE_NS,
    BOOT_GRACE_NS,
    REALERT_INTERVAL_NS,
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
STALE_HB = replace(FRESH, hb_ns=NOW - 120 * SEC)
_REPO = Path(__file__).resolve().parents[2]


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


def _seasoned(pid: int = 42) -> BreakerWatchState:
    """A state that has watched ``pid`` for an hour (past the boot grace)."""
    return BreakerWatchState(node_pid=pid, node_first_seen_ns=NOW - 3600 * SEC)


def _decide(
    probe: BreakerProbe,
    state: BreakerWatchState,
    *,
    k: int = 2,
    live: bool = True,
    now_ns: int = NOW,
    pid: int | None = 42,
) -> list[Any]:
    return decide_breaker_alerts(
        probe=probe, k_configured=k, node_live=live, now_ns=now_ns, state=state, node_pid=pid
    )


def _deliver(state: BreakerWatchState, specs: list[Any]) -> None:
    for spec in specs:
        state.delivered(spec, NOW)


def _run(ports: SupervisorPorts, watch: BreakerWatchState, tracked_pid: int | None = 42) -> None:
    ts._dispatch_breaker_watch(
        ports=ports, watch=watch, now=_now(), tracked_pid=tracked_pid, store_path=Path("/nowhere")
    )


def _k(value: int) -> Any:
    return lambda: value


# ---------------------------------------------------------------------------
# probe_breaker_record: read-only read
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


def test_probe_opens_the_store_read_only_and_never_creates_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "store.sqlite3"
    with SqliteStateStore(path) as store:
        store.set(
            BREAKER_KEY, encode_breaker(BreakerRecord(None, None, hb_ns=1, resolver_pass_ns=2))
        )
    uris: list[str] = []
    real_connect = sqlite3.connect

    def spy(database: str, timeout: float = 5.0, uri: bool = False) -> sqlite3.Connection:
        uris.append(database)
        return real_connect(database, timeout=timeout, uri=uri)

    monkeypatch.setattr(sqlite3, "connect", spy)

    def forbidden(*_a: object, **_kw: object) -> None:
        raise AssertionError("the probe must not use the SqliteStateStore constructor")

    monkeypatch.setattr(ts, "SqliteStateStore", forbidden)
    assert probe_breaker_record(path).present
    assert len(uris) == 1 and uris[0].startswith("file:") and uris[0].endswith("?mode=ro")
    missing = tmp_path / "absent.sqlite3"
    absent = probe_breaker_record(missing)
    assert absent.readable and not absent.present, "a store not created yet is absent, not a fault"
    assert not missing.exists()


# ---------------------------------------------------------------------------
# decide_breaker_alerts
# ---------------------------------------------------------------------------


def test_dead_watcher_denies_entries_and_supervisor_alerts() -> None:
    state = _seasoned()
    specs = _decide(STALE_HB, state)
    assert [s.detail for s in specs] == [BreakerAlertDetail.BREAKER_WATCHER_DEAD]
    assert specs[0].severity == "CRITICAL"
    _deliver(state, specs)
    # a delivered episode does not re-alert on the next tick
    assert _decide(STALE_HB, state) == []
    # a recovery then a new episode alerts again
    assert _decide(FRESH, state) == []
    assert [s.detail for s in _decide(STALE_HB, state)] == [BreakerAlertDetail.BREAKER_WATCHER_DEAD]


def test_an_undelivered_alert_is_due_again_on_the_next_tick() -> None:
    state = _seasoned()
    assert _decide(STALE_HB, state) != []
    assert _decide(STALE_HB, state) != []  # never marked delivered


def test_dead_resolver_pass_alerts_and_the_backoff_cap_does_not() -> None:
    state = _seasoned()
    capped = replace(FRESH, resolver_pass_ns=NOW - 300 * SEC)
    assert _decide(capped, state) == []
    dead = replace(FRESH, resolver_pass_ns=NOW - 601 * SEC)
    assert [s.detail for s in _decide(dead, state)] == [
        BreakerAlertDetail.BREAKER_RESOLVER_PASS_STALE
    ]


def test_absent_record_alerts_only_after_the_grace_with_a_live_node() -> None:
    absent = BreakerProbe.absent()
    state = BreakerWatchState()
    assert _decide(absent, state, pid=None) == []
    later = NOW + ABSENT_RECORD_GRACE_NS + 1
    specs = _decide(absent, state, pid=None, now_ns=later)
    assert [s.detail for s in specs] == [BreakerAlertDetail.BREAKER_WATCHER_DEAD]


def test_an_unreadable_record_with_a_live_node_alerts_dead_watcher() -> None:
    garbled = replace(BreakerProbe.absent(), readable=False)
    specs = _decide(garbled, BreakerWatchState(), pid=None)
    assert [s.detail for s in specs] == [BreakerAlertDetail.BREAKER_WATCHER_DEAD]


def test_no_dead_watcher_alert_when_the_node_is_not_live() -> None:
    stale = replace(FRESH, hb_ns=NOW - 3600 * SEC, resolver_pass_ns=NOW - 3600 * SEC)
    assert _decide(stale, _seasoned(), live=False) == []


def test_breaker_trip_alerts_once_and_unreadable_slot_alerts_at_any_k() -> None:
    state = BreakerWatchState()
    halted = replace(FRESH, halted=True, unreadable_slots=1)
    specs = _decide(halted, state, k=1)
    assert sorted(s.detail.value for s in specs) == sorted(
        [
            BreakerAlertDetail.BREAKER_ENTRY_HALT_LATCHED.value,
            BreakerAlertDetail.SLOT_TABLE_UNREADABLE_SLOT.value,
        ]
    )
    _deliver(state, specs)
    assert _decide(halted, state, k=1) == []


def test_k1_stale_record_never_raises_a_dead_watcher_alert() -> None:
    stale = replace(FRESH, hb_ns=0, resolver_pass_ns=0)
    assert _decide(stale, _seasoned(), k=1) == []


# ---------------------------------------------------------------------------
# R6: boot grace
# ---------------------------------------------------------------------------


def test_a_freshly_seen_node_pid_gets_a_boot_grace_for_stale_stamps() -> None:
    state = BreakerWatchState()
    previous_nodes_record = replace(
        FRESH, hb_ns=NOW - 7200 * SEC, resolver_pass_ns=NOW - 7200 * SEC
    )
    assert _decide(previous_nodes_record, state, pid=7) == []  # first sighting of pid 7
    assert _decide(previous_nodes_record, state, pid=7, now_ns=NOW + BOOT_GRACE_NS) == []
    after = _decide(previous_nodes_record, state, pid=7, now_ns=NOW + BOOT_GRACE_NS + 1)
    assert {s.detail for s in after} == {
        BreakerAlertDetail.BREAKER_WATCHER_DEAD,
        BreakerAlertDetail.BREAKER_RESOLVER_PASS_STALE,
    }, "a watcher that never heartbeats is still caught once the grace ends"


def test_a_new_pid_restarts_the_grace() -> None:
    state = _seasoned(pid=7)
    stale = replace(FRESH, hb_ns=NOW - 7200 * SEC)
    assert _decide(stale, state, pid=7) != []
    assert _decide(stale, state, pid=8) == []  # relaunched: new grace


# ---------------------------------------------------------------------------
# The dispatch inside the supervisor tick
# ---------------------------------------------------------------------------


def test_dispatch_emits_the_alert_through_the_existing_sink() -> None:
    sink = _Sink()
    ports = _ports(sink, probe_breaker_record=lambda _p: STALE_HB, configured_exec_par_k=_k(2))
    _run(ports, _seasoned())
    (payload,) = sink.payloads
    assert payload.detail == BreakerAlertDetail.BREAKER_WATCHER_DEAD.value
    assert payload.event == "TRADE_SUPERVISOR_BREAKER_WATCHER_DEAD"


def test_dispatch_marks_delivered_only_after_the_durable_send_confirms() -> None:
    sink = _Sink()
    outcomes = iter([False, True])
    sent: list[AlertPayload] = []

    def durable(_sink: object, payload: AlertPayload) -> bool:
        sent.append(payload)
        return next(outcomes)

    ports = _ports(
        sink,
        probe_breaker_record=lambda _p: STALE_HB,
        configured_exec_par_k=_k(2),
        send_alert_durable=durable,
    )
    watch = _seasoned()
    _run(ports, watch)  # outbox refused: not delivered
    assert watch.active == {}
    _run(ports, watch)  # retried, confirmed
    assert set(watch.active) == {"heartbeat_stale"}
    _run(ports, watch)  # now deduped: no third send
    assert len(sent) == 2


def test_dispatch_is_contained_when_the_probe_raises() -> None:
    sink = _Sink()

    def boom(_p: Path) -> BreakerProbe:
        raise RuntimeError("wal read blew up")

    _run(_ports(sink, probe_breaker_record=boom, configured_exec_par_k=_k(2)), _seasoned())
    assert sink.payloads == []


def test_k1_dispatch_opens_no_store_and_touches_no_process_port(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sink = _Sink()
    touched: list[str] = []

    def alive(_pid: int) -> bool:
        touched.append("process_alive")
        return True

    def find() -> int | None:
        touched.append("find_node_pid")
        return 1

    def opened(*_a: object, **_kw: object) -> None:
        touched.append("store_opened")
        raise AssertionError("K=1 must not open a store")

    monkeypatch.setattr(sqlite3, "connect", opened)
    monkeypatch.setattr(ts, "SqliteStateStore", opened)
    # the REAL probe port and the REAL (K=1) constant: nothing may be opened
    ports = _ports(
        sink,
        process_alive=alive,
        find_node_pid=find,
        probe_breaker_record=probe_breaker_record,
        configured_exec_par_k=ts.configured_exec_par_k,
    )
    store = tmp_path / "state.sqlite3"
    for pid in (None, 42):
        ts._dispatch_breaker_watch(
            ports=ports, watch=BreakerWatchState(), now=_now(), tracked_pid=pid, store_path=store
        )
    assert touched == []
    assert sink.payloads == []
    assert not store.exists()


def test_k_gt_1_dispatch_probes_read_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "state.sqlite3"
    with SqliteStateStore(path) as store:
        store.set(
            BREAKER_KEY, encode_breaker(BreakerRecord(None, None, hb_ns=1, resolver_pass_ns=1))
        )
    uris: list[str] = []
    real_connect = sqlite3.connect

    def spy(database: str, timeout: float = 5.0, uri: bool = False) -> sqlite3.Connection:
        uris.append(database)
        return real_connect(database, timeout=timeout, uri=uri)

    monkeypatch.setattr(sqlite3, "connect", spy)
    sink = _Sink()
    ports = _ports(sink, probe_breaker_record=probe_breaker_record, configured_exec_par_k=_k(2))
    ts._dispatch_breaker_watch(
        ports=ports, watch=_seasoned(), now=_now(), tracked_pid=42, store_path=path
    )
    assert uris and all(u.endswith("?mode=ro") for u in uris)
    assert sink.payloads, "a 1970 heartbeat with a live node is a dead watcher"


def test_supervisor_import_does_not_pull_in_node_config_or_the_watcher() -> None:
    """R5 finding: the supervisor ALREADY imports ``nautilus_trader`` (and pandas)
    before this WP, via ``breezy.domain.exec_intent`` ->
    ``breezy.domain.archived_climate_day`` (``RESOLVER_CONTEXT_KEY_PREFIX``), so
    "no Nautilus" cannot be asserted. What WP5b must not add is ``node_config``
    (the heavy config module) or the watcher Actor module."""
    code = (
        "import sys\n"
        "import breezy.runtime.trade_supervisor\n"
        "ours = sorted(m for m in ('breezy.runtime.node_config', 'breezy.runtime.breaker_watcher')"
        " if m in sys.modules)\n"
        "print('OURS=' + ','.join(ours))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
        env={"PYTHONPATH": str(_REPO / "src"), "PATH": "/usr/bin"},
        cwd=_REPO,
    )
    assert result.stdout.strip().rsplit("OURS=", 1)[1] == ""


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


def test_probe_reads_a_store_whose_path_has_uri_metacharacters(tmp_path: Path) -> None:
    odd = tmp_path / "a%b#c?d"
    odd.mkdir()
    path = odd / "store.sqlite3"
    with SqliteStateStore(path) as store:
        store.set(
            BREAKER_KEY, encode_breaker(BreakerRecord(None, None, hb_ns=3, resolver_pass_ns=4))
        )
    assert probe_breaker_record(path).hb_ns == 3


def test_a_missing_store_at_k_gt_1_does_not_page_as_unreadable(tmp_path: Path) -> None:
    sink = _Sink()
    ports = _ports(sink, probe_breaker_record=probe_breaker_record, configured_exec_par_k=_k(2))
    ts._dispatch_breaker_watch(
        ports=ports,
        watch=BreakerWatchState(),
        now=_now(),
        tracked_pid=42,
        store_path=tmp_path / "not-yet.sqlite3",
    )
    assert sink.payloads == []


def test_corruption_still_pages_immediately(tmp_path: Path) -> None:
    path = tmp_path / "store.sqlite3"
    with SqliteStateStore(path) as store:
        store.set(BREAKER_KEY, b"garbage")
    sink = _Sink()
    ports = _ports(sink, probe_breaker_record=probe_breaker_record, configured_exec_par_k=_k(2))
    ts._dispatch_breaker_watch(
        ports=ports, watch=BreakerWatchState(), now=_now(), tracked_pid=42, store_path=path
    )
    assert [p.detail for p in sink.payloads] == [BreakerAlertDetail.BREAKER_WATCHER_DEAD.value]


def test_the_probe_connection_timeout_is_one_second(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "store.sqlite3"
    with SqliteStateStore(path) as store:
        store.set(
            BREAKER_KEY, encode_breaker(BreakerRecord(None, None, hb_ns=1, resolver_pass_ns=1))
        )
    seen: list[float] = []
    real_connect = sqlite3.connect

    def spy(database: str, timeout: float = 5.0, uri: bool = False) -> sqlite3.Connection:
        seen.append(timeout)
        return real_connect(database, timeout=timeout, uri=uri)

    monkeypatch.setattr(sqlite3, "connect", spy)
    probe_breaker_record(path)
    assert seen == [1.0]


def test_one_raising_send_does_not_starve_the_other_alerts() -> None:
    sink = _Sink()
    calls: list[str] = []

    def durable(_sink: object, payload: AlertPayload) -> bool:
        calls.append(payload.event)
        if len(calls) == 1:
            raise OSError("outbox exploded")
        return True

    probe = replace(FRESH, halted=True, unreadable_slots=1)
    ports = _ports(
        sink,
        probe_breaker_record=lambda _p: probe,
        configured_exec_par_k=_k(2),
        send_alert_durable=durable,
    )
    watch = _seasoned()
    _run(ports, watch)
    assert len(calls) == 2, "the second spec was still attempted"
    assert len(watch.active) == 1, "and delivered; the raising one is retried next tick"


def test_a_delivered_page_is_repeated_hourly_while_the_condition_holds() -> None:
    state = _seasoned()
    _deliver(state, _decide(STALE_HB, state))

    def stale_at(now_ns: int) -> BreakerProbe:
        return replace(FRESH, hb_ns=now_ns - 120 * SEC, resolver_pass_ns=now_ns - SEC)

    just_before = NOW + REALERT_INTERVAL_NS - 1
    assert _decide(stale_at(just_before), state, now_ns=just_before) == []
    due = NOW + REALERT_INTERVAL_NS
    again = _decide(stale_at(due), state, now_ns=due)
    assert [s.detail for s in again] == [BreakerAlertDetail.BREAKER_WATCHER_DEAD]
