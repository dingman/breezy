"""RED/GREEN coverage for the supervisor's own fast-path node-liveness
check (SP-6 A11, rows 14/14b).

Per the plan: drive `decide_node_liveness` directly for the pure rules,
then `_run_forever(..., ports=<fakes>, max_iterations=N)` with a fake
clock parked in `Phase.NONE` for the join. The pid-cmdline-first /
pgrep-fallback fork-rate fix (AM-13/SEC2-M1) and the two-independent-
mechanisms absence rule (B4) are exercised at the `_do_node_liveness`
I/O-shell level, since those are properties of the wiring, not of the
pure decision function (already covered by `test_decide_node_liveness.py`).
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from breezy.runtime.health import AlertPayload
from breezy.runtime.trade_supervisor import SupervisorPorts, _do_node_liveness, _run_forever
from breezy.runtime.trade_supervisor_core import (
    AlertDetail,
    NodeLivenessState,
    decide_node_liveness,
)

_DAY = dt.date(2026, 9, 12)


def _utc(hour: int, minute: int, second: int = 0, *, day: dt.date = _DAY) -> dt.datetime:
    return dt.datetime.combine(day, dt.time(hour, minute, second), tzinfo=dt.UTC)


class _RecordingAlertSink:
    def __init__(self) -> None:
        self.payloads: list[AlertPayload] = []

    def emit(self, payload: AlertPayload) -> None:
        self.payloads.append(payload)


class FakeClock:
    def __init__(self, start: dt.datetime) -> None:
        self.current = start

    def __call__(self) -> dt.datetime:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current = self.current + dt.timedelta(seconds=seconds)


def _make_ports(**overrides: object) -> SupervisorPorts:
    base = {
        "find_node_pid": lambda: None,
        "resolve_intent_lock_holder": lambda _p: None,
        "intent_lock_free": lambda _p: True,
        "count_intent_lock_holders": lambda _p: 0,
        "terminate_after_recheck": lambda pid, **kw: None,
        "process_alive": lambda _pid: False,
        "probe_open_intent_state": lambda *a, **kw: False,
        "spawn": lambda **kw: None,
        "read_log_new": lambda _p: "",
        "alert_sink": _RecordingAlertSink(),
        "sigterm_poll_sleep": lambda _s: None,
    }
    base.update(overrides)
    return SupervisorPorts(**base)  # type: ignore[arg-type]


def _run(*, clock: FakeClock, ports: SupervisorPorts, max_iterations: int, tmp_path: Path) -> None:
    def fake_sleep(seconds: float) -> None:
        clock.advance(seconds)

    _run_forever(
        store_path=tmp_path / "state" / "store.sqlite3",
        repo_root=tmp_path,
        node_bin=tmp_path / "node_bin",
        log_dir=tmp_path / "logs",
        clock=clock,
        sleep=fake_sleep,
        ports=ports,
        max_iterations=max_iterations,
    )


# ---------------------------------------------------------------------------
# Row 14 -- pure rules driven directly through decide_node_liveness, plus
# the one full-join integration test through _run_forever.
# ---------------------------------------------------------------------------


class _TogglingFinder:
    """Present for the first `present_for` calls, absent thereafter --
    simulates a node that was successfully launched and later disappears."""

    def __init__(self, present_for: int, pid: int = 555) -> None:
        self.calls = 0
        self.present_for = present_for
        self.pid = pid

    def __call__(self) -> int | None:
        self.calls += 1
        return self.pid if self.calls <= self.present_for else None


def test_absent_node_after_a_successful_launch_emits_one_critical(tmp_path: Path) -> None:
    # Mid-day: node_expected_alive is True throughout, and Phase.NONE is
    # due on every pass (clock parked well away from any scheduled phase).
    clock = FakeClock(_utc(12, 0, 0))
    sink = _RecordingAlertSink()
    finder = _TogglingFinder(present_for=2)
    ports = _make_ports(find_node_pid=finder, alert_sink=sink)

    _run(clock=clock, ports=ports, max_iterations=6, tmp_path=tmp_path)

    critical_payloads = [p for p in sink.payloads if p.event == "TRADE_NODE_ABSENT"]
    assert len(critical_payloads) == 1
    assert critical_payloads[0].severity == "CRITICAL"
    assert critical_payloads[0].detail == AlertDetail.TRADE_NODE_ABSENT.value


def test_no_alert_before_the_first_launch_of_the_day() -> None:
    # 02:00Z, before today's 16:50 LAUNCH -- but the node IS present
    # (e.g. adopted from yesterday's still-running process). Presence
    # alone must never alert, regardless of what phase is due today.
    new_state, should_alert = decide_node_liveness(
        now_utc=_utc(2, 0, 0), node_present=True, state=NodeLivenessState()
    )
    assert should_alert is False
    assert new_state == NodeLivenessState()


def test_no_alert_between_the_scheduled_stop_and_the_next_launch() -> None:
    for minute in (41, 45, 54):
        state = NodeLivenessState()
        for _ in range(5):
            state, fired = decide_node_liveness(
                now_utc=_utc(16, minute, 0), node_present=False, state=state
            )
            assert fired is False
        assert state == NodeLivenessState()


def test_an_absent_node_at_0200Z_still_alerts() -> None:
    state = NodeLivenessState()
    state, first = decide_node_liveness(now_utc=_utc(2, 0, 0), node_present=False, state=state)
    assert first is False
    state, second = decide_node_liveness(now_utc=_utc(2, 0, 0), node_present=False, state=state)
    assert second is True


def test_a_reappearing_node_re_arms_the_alert() -> None:
    now = _utc(2, 0, 0)
    state = NodeLivenessState()
    state, _ = decide_node_liveness(now_utc=now, node_present=False, state=state)
    state, fired = decide_node_liveness(now_utc=now, node_present=False, state=state)
    assert fired is True
    assert state.alerted is True

    # The node comes back -- the state resets, ready to alert again.
    state, rearm_fired = decide_node_liveness(now_utc=now, node_present=True, state=state)
    assert rearm_fired is False
    assert state == NodeLivenessState()

    # And a fresh absence confirms and alerts again.
    state, _ = decide_node_liveness(now_utc=now, node_present=False, state=state)
    state, second_alert = decide_node_liveness(now_utc=now, node_present=False, state=state)
    assert second_alert is True


def test_absence_is_confirmed_by_two_consecutive_probes_before_alerting() -> None:
    now = _utc(2, 0, 0)
    state = NodeLivenessState()
    state, fired_after_one = decide_node_liveness(now_utc=now, node_present=False, state=state)
    assert fired_after_one is False
    assert state.consecutive_absent == 1
    state, fired_after_two = decide_node_liveness(now_utc=now, node_present=False, state=state)
    assert fired_after_two is True
    assert state.consecutive_absent == 2


def test_detail_is_a_closed_enum_value() -> None:
    assert AlertDetail.TRADE_NODE_ABSENT.value == "trade_node_absent"
    assert isinstance(AlertDetail.TRADE_NODE_ABSENT, AlertDetail)
    assert AlertDetail.TRADE_NODE_ABSENT.value == AlertDetail.TRADE_NODE_ABSENT.value.lower()


# ---------------------------------------------------------------------------
# Row 14b -- the I/O-shell properties: latch, containment, probe
# cardinality, the two-mechanism absence rule, and the fork-rate fix.
# ---------------------------------------------------------------------------


def test_a_standing_absence_alerts_once_not_every_pass(tmp_path: Path) -> None:
    clock = FakeClock(_utc(12, 0, 0))
    sink = _RecordingAlertSink()
    ports = _make_ports(find_node_pid=lambda: None, alert_sink=sink)

    _run(clock=clock, ports=ports, max_iterations=8, tmp_path=tmp_path)

    assert len([p for p in sink.payloads if p.event == "TRADE_NODE_ABSENT"]) == 1


def test_a_probe_exception_never_ends_the_supervisor(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, never_signals: None
) -> None:
    def bombing_finder() -> int | None:
        raise RuntimeError("simulated /proc read failure")

    clock = FakeClock(_utc(12, 0, 0))
    sink = _RecordingAlertSink()
    ports = _make_ports(find_node_pid=bombing_finder, alert_sink=sink)

    with caplog.at_level("ERROR"):
        _run(clock=clock, ports=ports, max_iterations=5, tmp_path=tmp_path)

    # Reaching here (no raised exception) IS the assertion: the loop ran
    # its full max_iterations budget despite every pass raising.
    assert clock.current == _utc(12, 5, 0)


def test_exactly_one_probe_per_quiet_iteration(tmp_path: Path) -> None:
    calls = {"n": 0}

    def counting_finder() -> int | None:
        calls["n"] += 1
        return None

    clock = FakeClock(_utc(12, 0, 0))
    ports = _make_ports(find_node_pid=counting_finder)

    _run(clock=clock, ports=ports, max_iterations=4, tmp_path=tmp_path)

    assert calls["n"] == 4


def test_absence_requires_both_the_pid_probe_and_the_lock_probe_to_agree(tmp_path: Path) -> None:
    # The pid probe says absent, but the intent-lock probe -- a completely
    # independent mechanism (B4) -- says a holder exists: overall presence
    # wins, and no alert is ever raised even across many passes.
    liveness = NodeLivenessState()
    sink = _RecordingAlertSink()
    ports = _make_ports(
        find_node_pid=lambda: None,
        resolve_intent_lock_holder=lambda _p: 4242,
        alert_sink=sink,
    )
    for _ in range(5):
        liveness = _do_node_liveness(
            ports=ports,
            now=_utc(2, 0, 0),
            liveness=liveness,
            tracked_pid=None,
            store_path=tmp_path / "store.sqlite3",
        )
    assert liveness == NodeLivenessState()
    assert sink.payloads == []


def test_a_tracked_pid_that_still_matches_its_cmdline_never_forks_pgrep(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, never_signals: None
) -> None:
    monkeypatch.setattr(
        "breezy.runtime.trade_supervisor.pid_cmdline_matches",
        lambda pid, anchor: True,
    )

    def bomb() -> int | None:
        raise AssertionError("ports.find_node_pid must not be called -- the cmdline read matched")

    sink = _RecordingAlertSink()
    ports = _make_ports(find_node_pid=bomb, alert_sink=sink)

    liveness = _do_node_liveness(
        ports=ports,
        now=_utc(12, 0, 0),
        liveness=NodeLivenessState(),
        tracked_pid=555,
        store_path=tmp_path / "store.sqlite3",
    )
    assert liveness == NodeLivenessState()
    assert sink.payloads == []


def test_a_tracked_pid_whose_cmdline_no_longer_matches_falls_back_to_pgrep(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, never_signals: None
) -> None:
    monkeypatch.setattr(
        "breezy.runtime.trade_supervisor.pid_cmdline_matches",
        lambda pid, anchor: False,
    )
    calls = {"n": 0}

    def fallback_finder() -> int | None:
        calls["n"] += 1
        return 777

    ports = _make_ports(find_node_pid=fallback_finder)

    liveness = _do_node_liveness(
        ports=ports,
        now=_utc(12, 0, 0),
        liveness=NodeLivenessState(),
        tracked_pid=555,
        store_path=tmp_path / "store.sqlite3",
    )
    assert calls["n"] == 1
    assert liveness == NodeLivenessState()  # present via the fallback -- never alerts


def test_a_reused_pid_is_not_mistaken_for_the_node(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, never_signals: None
) -> None:
    # The tracked pid was reused by an unrelated process -- its cmdline no
    # longer matches the node's anchor -- and the real node is genuinely
    # gone (the pgrep fallback also finds nothing, and no lock holder
    # exists either). This must be treated as a genuine, alertable absence,
    # never silently accepted because *a* process still owns that pid.
    monkeypatch.setattr(
        "breezy.runtime.trade_supervisor.pid_cmdline_matches",
        lambda pid, anchor: False,
    )
    sink = _RecordingAlertSink()
    ports = _make_ports(
        find_node_pid=lambda: None, resolve_intent_lock_holder=lambda _p: None, alert_sink=sink
    )

    liveness = NodeLivenessState()
    for _ in range(2):
        liveness = _do_node_liveness(
            ports=ports,
            now=_utc(12, 0, 0),
            liveness=liveness,
            tracked_pid=555,
            store_path=tmp_path / "store.sqlite3",
        )
    assert liveness.alerted is True
    assert len(sink.payloads) == 1
