"""EXEC-PAR BG-8: supervisor probes at any K, and the stage-stamp probe at K>1.

Spec: EXEC-PAR-D-PREREG section 1a (supervisor / stamp stale after 26 h) and
section 14 steps 8 and 10 (no-respawn pin).
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from breezy.runtime import trade_supervisor as ts
from breezy.runtime.breaker_supervisor_watch import (
    PROBE_INTERVAL_NS,
    STAGE_STAMP_MAX_AGE_NS,
    BreakerAlertDetail,
    BreakerProbe,
    BreakerWatchState,
    decide_breaker_alerts,
)
from breezy.runtime.exec_par_records import StageEvalStamp, encode_record
from breezy.runtime.health import AlertPayload
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import BREAKER_KEY
from breezy.runtime.submit_intent_slots import BreakerRecord, encode_breaker
from breezy.runtime.trade_supervisor import SupervisorPorts, probe_breaker_record

SEC = 1_000_000_000
NOW = 1_700_000_000 * SEC
STAMP_KEY = "exec/polymarket_us/exec_par/stage_eval/stamp"
STAMP_EVENT = "TRADE_SUPERVISOR_EXEC_PAR_STAGE_STAMP_STALE"
HALT_EVENT = "TRADE_SUPERVISOR_BREAKER_ENTRY_HALT_LATCHED"
FRESH = BreakerProbe(
    readable=True,
    present=True,
    halted=False,
    hb_ns=NOW - 5 * SEC,
    resolver_pass_ns=NOW - 5 * SEC,
    unreadable_slots=0,
    stamp_ts_ns=NOW - 3600 * SEC,
)


class _Sink:
    def __init__(self) -> None:
        self.payloads: list[AlertPayload] = []

    def emit(self, payload: AlertPayload) -> None:
        self.payloads.append(payload)


def _forbidden(*_a: object, **_kw: object) -> Any:
    raise AssertionError("the breaker watch never spawns or kills the node")


def _ports(sink: _Sink, **overrides: Any) -> SupervisorPorts:
    base = SupervisorPorts(
        find_node_pid=lambda: None,
        resolve_intent_lock_holder=lambda _p: None,
        intent_lock_free=lambda _p: True,
        count_intent_lock_holders=lambda _p: 0,
        terminate_after_recheck=_forbidden,
        process_alive=lambda _pid: True,
        probe_open_intent_state=lambda *a, **kw: False,
        spawn=_forbidden,
        read_log_new=lambda _p: "",
        alert_sink=sink,
    )
    return replace(base, **overrides)


def _at(now_ns: int) -> dt.datetime:
    return dt.datetime.fromtimestamp(now_ns / SEC, tz=dt.UTC)


def _tick(ports: SupervisorPorts, watch: BreakerWatchState, path: Path, now_ns: int = NOW) -> None:
    ts._dispatch_breaker_watch(
        ports=ports, watch=watch, now=_at(now_ns), tracked_pid=None, store_path=path
    )


def _decide(
    probe: BreakerProbe, state: BreakerWatchState, *, k: int, live: bool, now_ns: int = NOW
) -> list[Any]:
    return decide_breaker_alerts(
        probe=probe, k_configured=k, node_live=live, now_ns=now_ns, state=state, node_pid=42
    )


def _make_store(path: Path, *, halted: bool = False, stamp_ts: int | None = None) -> None:
    with SqliteStateStore(path) as store:
        reason = "contradiction" if halted else None
        store.set(
            BREAKER_KEY,
            encode_breaker(
                BreakerRecord(reason, 7 if halted else None, hb_ns=1, resolver_pass_ns=1)
            ),
        )
        if stamp_ts is not None:
            store.set(STAMP_KEY, encode_record(StageEvalStamp(ts_ns=stamp_ts, boot_ns=stamp_ts)))


def _k(value: int) -> Any:
    return lambda: value


# -- stamp probe: pure decision ------------------------------------------------


def test_stamp_bound_is_the_spec_26_hours() -> None:
    assert STAGE_STAMP_MAX_AGE_NS == 26 * 3600 * SEC
    assert PROBE_INTERVAL_NS == 600 * SEC


def test_stale_stamp_alerts_at_k2_even_with_the_node_down() -> None:
    old = replace(FRESH, stamp_ts_ns=NOW - STAGE_STAMP_MAX_AGE_NS - SEC)
    specs = _decide(old, BreakerWatchState(), k=2, live=False)
    assert [s.event for s in specs] == [STAMP_EVENT]
    assert specs[0].detail is BreakerAlertDetail.STAGE_STAMP_STALE


def test_fresh_stamp_does_not_alert_at_k2() -> None:
    assert _decide(FRESH, BreakerWatchState(), k=2, live=False) == []


def test_stamp_in_the_future_beyond_skew_is_stale() -> None:
    future = replace(FRESH, stamp_ts_ns=NOW + 6 * SEC)
    assert [s.event for s in _decide(future, BreakerWatchState(), k=2, live=False)] == [STAMP_EVENT]


def test_never_written_stamp_alerts_only_after_the_bound_from_first_sighting() -> None:
    never = replace(FRESH, stamp_ts_ns=None)
    state = BreakerWatchState()
    assert _decide(never, state, k=2, live=False) == []
    later = NOW + STAGE_STAMP_MAX_AGE_NS
    assert [s.event for s in _decide(never, state, k=2, live=False, now_ns=later)] == [STAMP_EVENT]


def test_garbled_stamp_alerts_immediately() -> None:
    garbled = replace(FRESH, stamp_readable=False)
    assert [s.event for s in _decide(garbled, BreakerWatchState(), k=2, live=False)] == [
        STAMP_EVENT
    ]


def test_stamp_probe_is_silent_at_k1() -> None:
    old = replace(FRESH, stamp_ts_ns=None, stamp_readable=False)
    assert _decide(old, BreakerWatchState(), k=1, live=False) == []


def test_stamp_alert_dedups_per_episode_and_rearms_after_recovery() -> None:
    old = replace(FRESH, stamp_ts_ns=NOW - STAGE_STAMP_MAX_AGE_NS - SEC)
    state = BreakerWatchState()
    specs = _decide(old, state, k=2, live=False)
    for spec in specs:
        state.delivered(spec, NOW)
    assert _decide(old, state, k=2, live=False, now_ns=NOW + 60 * SEC) == []
    assert _decide(FRESH, state, k=2, live=False, now_ns=NOW + 120 * SEC) == []
    again = _decide(old, state, k=2, live=False, now_ns=NOW + 180 * SEC)
    assert [s.event for s in again] == [STAMP_EVENT]


# -- K=1 dedup / unreadable ------------------------------------------------------


def test_k1_halted_breaker_alerts_exactly_once_over_many_ticks() -> None:
    state = BreakerWatchState()
    halted = replace(FRESH, halted=True)
    sent = 0
    for i in range(30):
        now = NOW + i * 3 * 3600 * SEC  # far beyond the hourly K>1 re-alert
        specs = _decide(halted, state, k=1, live=False, now_ns=now)
        sent += len(specs)
        for spec in specs:
            state.delivered(spec, now)
    assert sent == 1


def test_k1_unreadable_probe_alerts_once_and_not_as_dead_watcher() -> None:
    state = BreakerWatchState()
    bad = replace(BreakerProbe.absent(), readable=False)
    specs = _decide(bad, state, k=1, live=True)
    assert [s.detail for s in specs] == [BreakerAlertDetail.PROBE_UNREADABLE]
    for spec in specs:
        state.delivered(spec, NOW)
    assert _decide(bad, state, k=1, live=True, now_ns=NOW + 7200 * SEC) == []


# -- supervisor dispatch ---------------------------------------------------------


def test_k1_dispatch_with_halted_breaker_alerts_once_and_never_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "state.sqlite3"
    _make_store(path, halted=True)
    before = path.read_bytes()
    uris: list[str] = []
    real = sqlite3.connect

    def spy(database: str, timeout: float = 5.0, uri: bool = False) -> sqlite3.Connection:
        uris.append(database)
        return real(database, timeout=timeout, uri=uri)

    monkeypatch.setattr(sqlite3, "connect", spy)
    monkeypatch.setattr(
        ts, "SqliteStateStore", lambda *a, **k: pytest.fail("write-capable store opened")
    )
    sink = _Sink()
    ports = _ports(
        sink,
        probe_breaker_record=probe_breaker_record,
        configured_exec_par_k=ts.configured_exec_par_k,
    )
    assert ports.configured_exec_par_k() == 1
    watch = BreakerWatchState()
    for i in range(12):  # 12 ticks, 10 min apart: two hours
        _tick(ports, watch, path, NOW + i * PROBE_INTERVAL_NS)
    assert [p.event for p in sink.payloads] == [HALT_EVENT]
    assert uris and all(u.endswith("?mode=ro") for u in uris)
    assert path.read_bytes() == before


def test_k1_missing_store_neither_alerts_nor_creates_it(tmp_path: Path) -> None:
    path = tmp_path / "absent.sqlite3"
    sink = _Sink()
    ports = _ports(sink, probe_breaker_record=probe_breaker_record, configured_exec_par_k=_k(1))
    _tick(ports, BreakerWatchState(), path)
    assert sink.payloads == []
    assert not path.exists()


def test_k1_locked_or_unreadable_store_logs_alerts_once_and_does_not_raise(
    tmp_path: Path,
) -> None:
    path = tmp_path / "state.sqlite3"
    path.write_bytes(b"this is not a sqlite database" * 50)
    sink = _Sink()
    ports = _ports(sink, probe_breaker_record=probe_breaker_record, configured_exec_par_k=_k(1))
    watch = BreakerWatchState()
    for i in range(6):
        _tick(ports, watch, path, NOW + i * PROBE_INTERVAL_NS)
    assert len(sink.payloads) == 1
    assert sink.payloads[0].event == "TRADE_SUPERVISOR_BREAKER_PROBE_UNREADABLE"


def test_probe_runs_at_most_once_per_ten_minutes(tmp_path: Path) -> None:
    calls: list[int] = []

    def probe(_p: Path) -> BreakerProbe:
        calls.append(1)
        return BreakerProbe.absent()

    ports = _ports(_Sink(), probe_breaker_record=probe, configured_exec_par_k=_k(1))
    watch = BreakerWatchState()
    for sec in (0, 60, 300, 599):
        _tick(ports, watch, tmp_path / "s", NOW + sec * SEC)
    assert len(calls) == 1
    _tick(ports, watch, tmp_path / "s", NOW + 600 * SEC)
    assert len(calls) == 2


def test_k2_stamp_probe_fires_through_dispatch_with_the_node_down(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite3"
    _make_store(path, stamp_ts=NOW - STAGE_STAMP_MAX_AGE_NS - 60 * SEC)
    sink = _Sink()
    ports = _ports(
        sink,
        probe_breaker_record=probe_breaker_record,
        configured_exec_par_k=_k(2),
        find_node_pid=lambda: None,
    )
    _tick(ports, BreakerWatchState(), path)
    assert STAMP_EVENT in [p.event for p in sink.payloads]


def test_k2_missing_store_with_node_down_never_written_stamp_waits_for_the_bound(
    tmp_path: Path,
) -> None:
    path = tmp_path / "absent.sqlite3"
    sink = _Sink()
    ports = _ports(sink, probe_breaker_record=probe_breaker_record, configured_exec_par_k=_k(2))
    watch = BreakerWatchState()
    _tick(ports, watch, path)
    assert sink.payloads == []
    _tick(ports, watch, path, NOW + STAGE_STAMP_MAX_AGE_NS)
    assert [p.event for p in sink.payloads] == [STAMP_EVENT]
    assert not path.exists()


def test_probe_reads_the_stamp_read_only(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite3"
    _make_store(path, stamp_ts=123)
    probe = probe_breaker_record(path)
    assert probe.stamp_ts_ns == 123 and probe.stamp_readable
    with SqliteStateStore(path) as store:
        store.set(STAMP_KEY, b"garbage")
    bad = probe_breaker_record(path)
    assert bad.readable and not bad.stamp_readable


# -- no-respawn pin --------------------------------------------------------------


@pytest.mark.parametrize(
    "probe",
    [
        replace(FRESH, hb_ns=NOW - 3600 * SEC),  # WATCHER_DEAD
        replace(FRESH, resolver_pass_ns=NOW - 3600 * SEC),  # RESOLVER_PASS_STALE
        replace(FRESH, halted=True),  # ENTRY_HALT_LATCHED
        replace(FRESH, unreadable_slots=1),  # UNREADABLE_SLOT
        replace(FRESH, stamp_ts_ns=None, stamp_readable=False),  # STAMP_STALE
        replace(BreakerProbe.absent(), readable=False),  # PROBE_UNREADABLE / dead
    ],
)
@pytest.mark.parametrize("live", [True, False])
def test_every_breaker_alert_only_alerts_and_never_respawns_or_kills(
    probe: BreakerProbe, live: bool
) -> None:
    watcher_only = probe.hb_ns < NOW - 600 * SEC or probe.resolver_pass_ns < NOW - 600 * SEC
    if watcher_only and not live:
        pytest.skip("dead-watcher and resolver alerts need a live node")
    sink = _Sink()
    ports = _ports(
        sink,
        probe_breaker_record=lambda _p: probe,
        configured_exec_par_k=_k(2),
        find_node_pid=lambda: 42 if live else None,
        process_alive=lambda _pid: live,
    )
    watch = BreakerWatchState(node_pid=42 if live else None, node_first_seen_ns=NOW - 7200 * SEC)
    _tick(ports, watch, Path("/nowhere"))  # spawn / terminate_after_recheck raise if touched
    assert sink.payloads, "the scenario must actually alert"
