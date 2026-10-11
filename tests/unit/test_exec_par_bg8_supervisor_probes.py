"""EXEC-PAR BG-8: supervisor probes at any K, and the stage-stamp probe at K>1.

Spec: EXEC-PAR-D-PREREG section 1a (supervisor / stamp stale after 26 h) and
section 14 steps 8 and 10 (no-respawn pin).
"""

from __future__ import annotations

import datetime as dt
import os
import sqlite3
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from breezy.runtime import trade_supervisor as ts
from breezy.runtime.breaker_supervisor_watch import (
    PROBE_INTERVAL_NS,
    RETRY_INTERVAL_NS,
    STAGE_STAMP_MAX_AGE_NS,
    UNREADABLE_DEBOUNCE_PROBES,
    BreakerAlertDetail,
    BreakerProbe,
    BreakerWatchState,
    decide_breaker_alerts,
)
from breezy.runtime.exec_par_records import (
    EPOCH_KEY_PREFIX,
    EpochRow,
    StageEvalStamp,
    encode_record,
)
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


def test_k1_unreadable_probe_alerts_once_after_two_consecutive_and_not_as_dead_watcher() -> None:
    assert UNREADABLE_DEBOUNCE_PROBES == 2
    state = BreakerWatchState()
    bad = replace(BreakerProbe.absent(), readable=False)
    assert _decide(bad, state, k=1, live=True) == []  # one transient failure: silent
    specs = _decide(bad, state, k=1, live=True, now_ns=NOW + PROBE_INTERVAL_NS)
    assert [s.detail for s in specs] == [BreakerAlertDetail.PROBE_UNREADABLE]
    for spec in specs:
        state.delivered(spec, NOW)
    assert _decide(bad, state, k=1, live=True, now_ns=NOW + 7200 * SEC) == []


def test_a_good_read_resets_the_unreadable_counter() -> None:
    state = BreakerWatchState()
    bad = replace(BreakerProbe.absent(), readable=False)
    assert _decide(bad, state, k=1, live=False) == []
    assert _decide(FRESH, state, k=1, live=False) == []  # recovery
    assert _decide(bad, state, k=1, live=False) == []  # counter restarted at one
    assert len(_decide(bad, state, k=1, live=False)) == 1


def test_a_cached_redecide_does_not_count_as_a_probe() -> None:
    state = BreakerWatchState()
    bad = replace(BreakerProbe.absent(), readable=False)
    assert _decide(bad, state, k=1, live=False) == []
    again = decide_breaker_alerts(
        probe=bad, k_configured=1, node_live=False, now_ns=NOW, state=state, fresh=False
    )
    assert again == []


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


def test_k1_garbage_store_alerts_once_after_two_consecutive_probes_and_does_not_raise(
    tmp_path: Path,
) -> None:
    path = tmp_path / "state.sqlite3"
    path.write_bytes(b"this is not a sqlite database" * 50)
    sink = _Sink()
    ports = _ports(sink, probe_breaker_record=probe_breaker_record, configured_exec_par_k=_k(1))
    watch = BreakerWatchState()
    _tick(ports, watch, path, NOW)
    assert sink.payloads == []
    for i in range(1, 6):
        _tick(ports, watch, path, NOW + i * PROBE_INTERVAL_NS)
    assert [p.event for p in sink.payloads] == ["TRADE_SUPERVISOR_BREAKER_PROBE_UNREADABLE"]


def test_a_real_exclusive_lock_is_a_failed_probe_that_alerts_only_when_it_persists(
    tmp_path: Path,
) -> None:
    path = tmp_path / "state.sqlite3"
    setup = sqlite3.connect(path)  # rollback-journal mode: a writer blocks readers
    setup.execute("CREATE TABLE state (key TEXT PRIMARY KEY, value BLOB)")
    setup.commit()
    setup.close()
    locker = sqlite3.connect(path, isolation_level=None)
    locker.execute("BEGIN EXCLUSIVE")
    try:
        assert not probe_breaker_record(path).readable
        sink = _Sink()
        ports = _ports(sink, probe_breaker_record=probe_breaker_record, configured_exec_par_k=_k(1))
        watch = BreakerWatchState()
        _tick(ports, watch, path, NOW)
        assert sink.payloads == []  # one busy read does not page
        locker.execute("ROLLBACK")
        _tick(ports, watch, path, NOW + PROBE_INTERVAL_NS)  # recovery resets
        locker.execute("BEGIN EXCLUSIVE")
        _tick(ports, watch, path, NOW + 2 * PROBE_INTERVAL_NS)
        assert sink.payloads == []
    finally:
        locker.close()


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


# -- lost-send retry: own 60 s throttle, probe throttle untouched ----------------


def _halted_ports(sink: _Sink, **overrides: Any) -> tuple[SupervisorPorts, list[int]]:
    probes: list[int] = []

    def probe(_p: Path) -> BreakerProbe:
        probes.append(1)
        return replace(FRESH, halted=True)

    return (
        _ports(sink, probe_breaker_record=probe, configured_exec_par_k=_k(1), **overrides),
        probes,
    )


def test_a_send_that_keeps_raising_is_attempted_at_most_once_per_60s() -> None:
    attempts: list[int] = []

    def raising(_sink: object, _payload: AlertPayload) -> bool:
        attempts.append(1)
        raise RuntimeError("outbox write succeeded, then the POST layer blew up")

    ports, probes = _halted_ports(_Sink(), send_alert_durable=raising)
    watch = BreakerWatchState()
    for sec in range(0, 600, 10):  # a poll every 10 s for 10 minutes
        _tick(ports, watch, Path("/x"), NOW + sec * SEC)
    assert RETRY_INTERVAL_NS == 60 * SEC
    assert len(attempts) == 10  # t=0,60,...,540
    assert len(probes) == 1  # retries never reopened the probe throttle


def test_a_non_durable_result_retries_on_the_60s_throttle_then_stops_when_durable() -> None:
    results = iter([False, False, True])
    attempts: list[int] = []

    def send(_sink: object, _payload: AlertPayload) -> bool:
        attempts.append(1)
        return next(results)

    ports, probes = _halted_ports(_Sink(), send_alert_durable=send)
    watch = BreakerWatchState()
    for sec in range(0, 400, 5):
        _tick(ports, watch, Path("/x"), NOW + sec * SEC)
    assert len(attempts) == 3
    assert len(probes) == 1


# -- durable K>1 anchor for a never-written stamp --------------------------------


def _put_epoch(path: Path, boot_ts: int, k: int, key: str | None = None) -> None:
    with SqliteStateStore(path) as store:
        store.set(
            key or f"{EPOCH_KEY_PREFIX}{boot_ts}",
            encode_record(EpochRow("abc", k, None, boot_ts)),
        )


def test_probe_anchor_is_the_minimum_k_gt_1_epoch_boot_ts(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite3"
    _make_store(path)
    _put_epoch(path, 50 * SEC, 1)
    _put_epoch(path, 900 * SEC, 2)
    _put_epoch(path, 700 * SEC, 2)
    _put_epoch(path, 1000 * SEC, 1, key=f"{EPOCH_KEY_PREFIX}latest")  # pointer row: skipped
    probe = probe_breaker_record(path)
    assert probe.readable and probe.k_anchor_ns == 700 * SEC


def test_probe_has_no_anchor_without_a_k_gt_1_epoch(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite3"
    _make_store(path)
    _put_epoch(path, 50 * SEC, 1)
    assert probe_breaker_record(path).k_anchor_ns is None


def test_corrupt_epoch_row_is_an_unreadable_probe_not_a_crash(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite3"
    _make_store(path)
    with SqliteStateStore(path) as store:
        store.set(f"{EPOCH_KEY_PREFIX}123", b"garbage")
    assert not probe_breaker_record(path).readable


def test_anchor_survives_a_supervisor_restart() -> None:
    anchor = NOW - STAGE_STAMP_MAX_AGE_NS - SEC
    never = replace(FRESH, stamp_ts_ns=None, k_anchor_ns=anchor)
    # a brand-new supervisor (fresh state) alerts at once: the clock is durable
    specs = _decide(never, BreakerWatchState(), k=2, live=False)
    assert [s.event for s in specs] == [STAMP_EVENT]
    assert specs[0].detail is BreakerAlertDetail.STAGE_STAMP_STALE


def test_no_k_gt_1_epoch_falls_back_to_first_sighting_and_labels_it() -> None:
    never = replace(FRESH, stamp_ts_ns=None, k_anchor_ns=None)
    state = BreakerWatchState()
    assert _decide(never, state, k=2, live=False) == []
    later = _decide(never, state, k=2, live=False, now_ns=NOW + STAGE_STAMP_MAX_AGE_NS)
    assert [s.detail for s in later] == [BreakerAlertDetail.STAGE_STAMP_STALE_FIRST_SIGHTING]
    assert "anchor=first_sighting" in later[0].detail.value


def test_a_young_anchor_does_not_alert() -> None:
    never = replace(FRESH, stamp_ts_ns=None, k_anchor_ns=NOW - 3600 * SEC)
    assert _decide(never, BreakerWatchState(), k=2, live=False) == []


# -- no-respawn pin, completed ----------------------------------------------------


def _no_signal(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: object, **_kw: object) -> Any:
        raise AssertionError("the breaker watch must not signal or spawn")

    monkeypatch.setattr(os, "kill", boom)
    monkeypatch.setattr(os, "killpg", boom)
    for name in ("Popen", "run", "call", "check_call", "check_output"):
        monkeypatch.setattr(subprocess, name, boom)


@pytest.mark.parametrize("send", ["raises", "non_durable"])
@pytest.mark.parametrize("live", [True, False])
def test_no_respawn_when_the_send_fails_or_the_node_is_down(
    monkeypatch: pytest.MonkeyPatch, send: str, live: bool
) -> None:
    _no_signal(monkeypatch)

    def durable(_sink: object, _payload: AlertPayload) -> bool:
        if send == "raises":
            raise RuntimeError("send failed")
        return False

    dead = replace(FRESH, hb_ns=NOW - 3600 * SEC, halted=True)
    ports = _ports(
        _Sink(),
        probe_breaker_record=lambda _p: dead,
        configured_exec_par_k=_k(2),
        find_node_pid=lambda: 42 if live else None,
        process_alive=lambda _pid: live,
        send_alert_durable=durable,
    )
    watch = BreakerWatchState(node_pid=42 if live else None, node_first_seen_ns=NOW - 7200 * SEC)
    for i in range(5):
        _tick(ports, watch, Path("/nowhere"), NOW + i * 61 * SEC)


def test_watcher_dead_with_the_node_down_does_not_alert_or_signal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_signal(monkeypatch)
    sink = _Sink()
    ports = _ports(
        sink,
        probe_breaker_record=lambda _p: replace(FRESH, hb_ns=NOW - 3600 * SEC),
        configured_exec_par_k=_k(2),
        find_node_pid=lambda: None,
    )
    _tick(ports, BreakerWatchState(), Path("/nowhere"))
    assert sink.payloads == []
