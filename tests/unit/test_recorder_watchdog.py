"""AUT-1 WP3 step 1: the recorder watchdog gate (r12 section 3.10.1; WP0-measured constants).

Pure classifier tests plus the gate's pinger decisions; the pinger task itself is in
``test_recorder_watchdog_pinger.py``. Constants under test (WP0 part b): STREAM_SILENCE_S=900,
QUIET_HOURS_MULTIPLIER=1, WRITER_STALL_S=120, FLUSH_MARGIN_S=30, DISCOVERY_ATTEMPT_BUDGET_S=180.
"""

from __future__ import annotations

import json
import os
import re
import socket
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import breezy.adapters.polymarket_us.recorder_watchdog as rw
from breezy.adapters.polymarket_us.recorder_watchdog import (
    ACTION_EXTEND,
    ACTION_NONE,
    ACTION_PING,
    CAUSE_CONNECTING_OVERRUN,
    CAUSE_DISCOVERING_OVERRUN,
    CAUSE_DISCOVERY_ATTEMPT_HUNG,
    CAUSE_DISCOVERY_RELOAD_OVERDUE,
    CAUSE_FEED_WATCH_DEAD,
    CAUSE_SAFE_MODE_OVERRUN,
    CAUSE_STREAM_STALLED,
    CAUSE_WRITER_STALL,
    PHASE_CONNECTING,
    PHASE_DISCOVERING,
    PHASE_SAFE_MODE,
    RecorderWatchdogPinger,
    classify_recorder_sample,
    decide_action,
    deferred_line,
    extend_timeout_message,
    sd_notify,
)
from breezy.runtime import node_config
from tests.support.recorder_watchdog import NS, ListLogger, sample, series, utc_ns

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "recorder_watchdog"
RETRY = 3600.0
MORNING = utc_ns(8, 0, 0)


def _classify(history: list[Any], now_ns: int, **kwargs: Any) -> str:
    return classify_recorder_sample(history, now_ns, **kwargs)


# ------------------------------------------------------------------------ streaming gate


def test_ok_streaming_pings() -> None:
    history = series(MORNING, 1200, events_at=lambda t: 1200 - t, bytes_at=lambda t: 5000 - t)
    assert _classify(history, MORNING) == "OK"
    action = decide_action(
        verdict="OK", ready=True, stop_begun=False, started_ns=MORNING - 9000 * NS, now_ns=MORNING
    )
    assert action == ACTION_PING


def test_empty_listing_with_fresh_reload_pings() -> None:
    history = [
        sample(
            MORNING,
            discovered_slugs=0,
            subscribed_count=0,
            last_discovery_reload_ns=MORNING - 100 * NS,
        )
    ]
    assert _classify(history, MORNING) == "OK"


def test_empty_listing_with_reload_older_than_twice_delay_withholds() -> None:
    def at(age_s: int) -> str:
        reload_ns = MORNING - age_s * NS
        return _classify(
            [
                sample(
                    MORNING,
                    discovered_slugs=0,
                    subscribed_count=0,
                    last_discovery_reload_ns=reload_ns,
                )
            ],
            MORNING,
        )

    assert at(1800) == "OK"
    assert at(1801) == CAUSE_DISCOVERY_RELOAD_OVERDUE


def test_discovering_within_budget_extends_start_timeout() -> None:
    history = [sample(MORNING, phase=PHASE_DISCOVERING, phase_started_ns=MORNING - 3900 * NS)]
    assert _classify(history, MORNING, ready=False) == "OK"
    action = decide_action(
        verdict="OK", ready=False, stop_begun=False, started_ns=MORNING - 3900 * NS, now_ns=MORNING
    )
    assert action == ACTION_EXTEND
    assert extend_timeout_message() == "EXTEND_TIMEOUT_USEC=120000000"


def test_discovering_overrun_stops_extending() -> None:
    history = [sample(MORNING, phase=PHASE_DISCOVERING, phase_started_ns=MORNING - 3901 * NS)]
    verdict = _classify(history, MORNING, ready=False)
    assert verdict == CAUSE_DISCOVERING_OVERRUN
    assert (
        decide_action(
            verdict=verdict,
            ready=False,
            stop_begun=False,
            started_ns=MORNING - 3901 * NS,
            now_ns=MORNING,
        )
        == ACTION_NONE
    )


def test_connecting_overrun_stops_extending() -> None:
    def verdict(age_s: int) -> str:
        return _classify(
            [sample(MORNING, phase=PHASE_CONNECTING, phase_started_ns=MORNING - age_s * NS)],
            MORNING,
            ready=False,
        )

    assert verdict(300) == "OK"
    assert verdict(301) == CAUSE_CONNECTING_OVERRUN
    assert (
        decide_action(
            verdict=CAUSE_CONNECTING_OVERRUN,
            ready=False,
            stop_begun=False,
            started_ns=MORNING,
            now_ns=MORNING,
        )
        == ACTION_NONE
    )


def test_safe_mode_overrun_withholds() -> None:
    streamed = series(MORNING - 400 * NS, 100)

    def verdict(age_s: int) -> str:
        history = [
            *streamed,
            sample(
                MORNING,
                phase=PHASE_SAFE_MODE,
                phase_started_ns=MORNING - age_s * NS,
                safe_mode=True,
            ),
        ]
        return _classify(history, MORNING)

    assert verdict(300) == "OK"
    assert verdict(301) == CAUSE_SAFE_MODE_OVERRUN


def test_frozen_counters_and_bytes_withhold_after_stream_silence() -> None:
    def verdict(span_s: int) -> str:
        return _classify(
            series(MORNING, span_s, events_at=lambda t: 7, bytes_at=lambda t: 9000), MORNING
        )

    assert verdict(895) == "OK"
    assert verdict(905) == CAUSE_STREAM_STALLED


def test_frozen_counters_with_moving_bytes_is_not_stalled() -> None:
    history = series(MORNING, 1000, events_at=lambda t: 7, bytes_at=lambda t: 9000 + (t // 5))
    assert _classify(history, MORNING) == "OK"


def test_no_subscriptions_is_never_stream_stalled() -> None:
    history = series(MORNING, 1000, subscribed_count=0, discovered_slugs=0)
    assert _classify(history, MORNING) == "OK"


def test_one_event_flat_bytes_over_writer_stall_withholds() -> None:
    # One event at t-100 s; bytes flat for 200 s (the event never reached disk).
    history = series(
        MORNING, 200, events_at=lambda t: 1 if t <= 100 else 0, bytes_at=lambda t: 4000
    )
    assert _classify(history, MORNING) == CAUSE_WRITER_STALL


def test_healthy_quiet_trickle_never_writer_stall() -> None:
    # One event, and the bytes grow ten seconds later: the writer flushed.
    history = series(
        MORNING,
        200,
        events_at=lambda t: 1 if t <= 100 else 0,
        bytes_at=lambda t: 4000 if t > 90 else 4400,
    )
    assert _classify(history, MORNING) == "OK"


def test_event_inside_flush_margin_still_pings() -> None:
    history = series(MORNING, 200, events_at=lambda t: 1 if t <= 10 else 0, bytes_at=lambda t: 4000)
    assert _classify(history, MORNING) == "OK"


def test_quiet_hours_use_wp0_multiplier(monkeypatch: pytest.MonkeyPatch) -> None:
    assert rw.QUIET_HOURS_MULTIPLIER == 1 and rw.STREAM_SILENCE_S == 900
    assert rw.QUIET_HOURS_UTC == frozenset({11, 22, 23})
    quiet = utc_ns(11, 30, 0)

    def verdict(now_ns: int) -> str:
        return _classify(series(now_ns, 1000, events_at=lambda t: 1, bytes_at=lambda t: 1), now_ns)

    assert verdict(quiet) == CAUSE_STREAM_STALLED
    monkeypatch.setattr(rw, "QUIET_HOURS_MULTIPLIER", 3)
    assert verdict(quiet) == "OK"  # the horizon is 2700 s in a quiet hour
    assert verdict(MORNING) == CAUSE_STREAM_STALLED  # active hours keep 900 s


def test_midnight_rotation_is_not_writer_stall() -> None:
    now = utc_ns(0, 1, 50, day=5)
    rotated = utc_ns(0, 0, 5, day=5)
    history = series(
        now,
        200,
        events_at=lambda t: 200 - t,
        bytes_at=lambda t: 4000 if now - t * NS < rotated else 4000 + 700_000,
    )
    assert _classify(history, now) == "OK"


def test_dead_feed_watch_withholds_feed_watch_dead() -> None:
    history = series(
        MORNING,
        100,
        events_at=lambda t: 100 - t,
        bytes_at=lambda t: 100 - t,
        feed_watch_alive=False,
    )
    assert _classify(history, MORNING) == CAUSE_FEED_WATCH_DEAD


def test_discovery_attempt_inflight_over_budget_stops_extending() -> None:
    def verdict(inflight_s: int) -> str:
        return _classify(
            [
                sample(
                    MORNING,
                    phase=PHASE_DISCOVERING,
                    phase_started_ns=MORNING - 600 * NS,
                    discovery_attempt_inflight_since_ns=MORNING - inflight_s * NS,
                )
            ],
            MORNING,
            ready=False,
        )

    assert verdict(180) == "OK"
    assert verdict(181) == CAUSE_DISCOVERY_ATTEMPT_HUNG


def test_retry_sleep_between_attempts_stays_ok() -> None:
    history = [
        sample(
            MORNING,
            phase=PHASE_DISCOVERING,
            phase_started_ns=MORNING - 2000 * NS,
            discovery_attempt_inflight_since_ns=0,
        )
    ]
    assert _classify(history, MORNING, ready=False) == "OK"


# ------------------------------------------------------------------- launch window (X-3)


def _stalled_history(now_ns: int) -> list[Any]:
    return series(now_ns, 1000, events_at=lambda t: 1, bytes_at=lambda t: 1)


def test_deferral_ends_at_1710z_and_withholds() -> None:
    inside = utc_ns(17, 9, 55)
    edge = utc_ns(17, 10, 0)
    assert _classify(_stalled_history(inside), inside) == "OK_DEFERRED"
    assert _classify(_stalled_history(edge), edge) == CAUSE_STREAM_STALLED


def test_deferral_horizon_reaches_back_before_the_window() -> None:
    # A stall whose kill would land inside 16:30Z..17:10Z is deferred: H = 600 + 120 + 180.
    assert rw.DEFERRAL_HORIZON_S == 900
    early = utc_ns(16, 15, 0)
    assert _classify(_stalled_history(early), early) == "OK_DEFERRED"
    too_early = utc_ns(16, 14, 59)
    assert _classify(_stalled_history(too_early), too_early) == CAUSE_STREAM_STALLED


def test_pre_ready_withhold_is_never_deferred() -> None:
    now = utc_ns(16, 40, 0)
    history = [sample(now, phase=PHASE_DISCOVERING, phase_started_ns=now - 4000 * NS)]
    verdict = _classify(history, now, ready=False)
    assert verdict == CAUSE_DISCOVERING_OVERRUN
    assert rw.window_meets_launch_window(now)
    assert (
        decide_action(
            verdict=verdict, ready=False, stop_begun=False, started_ns=now - 4000 * NS, now_ns=now
        )
        == ACTION_NONE
    )
    # The same cause after READY IS deferred.
    after_ready = [
        *series(now - 300 * NS, 100),
        sample(now, phase=PHASE_SAFE_MODE, phase_started_ns=now - 400 * NS),
    ]
    assert _classify(after_ready, now) == "OK_DEFERRED"


def test_stop_begun_never_extends_before_ready() -> None:
    kwargs: dict[str, Any] = {
        "verdict": "OK",
        "ready": False,
        "started_ns": MORNING,
        "now_ns": MORNING,
    }
    assert decide_action(stop_begun=False, **kwargs) == ACTION_EXTEND
    assert decide_action(stop_begun=True, **kwargs) == ACTION_NONE


_SEGMENT = st.tuples(
    st.sampled_from([PHASE_DISCOVERING, PHASE_CONNECTING, PHASE_SAFE_MODE]),
    st.integers(min_value=0, max_value=5000),
    st.booleans(),
)


@settings(max_examples=60, deadline=None)
@given(
    segments=st.lists(_SEGMENT, min_size=1, max_size=6),
    tick_s=st.integers(min_value=5, max_value=30),
    pre_connect_s=st.integers(min_value=0, max_value=int(rw.UNIT_TIMEOUT_START_SEC)),
    start_hour=st.sampled_from([8, 16, 16, 16]),
    start_minute=st.integers(min_value=0, max_value=59),
)
def test_extension_deadline_never_exceeds_max_start_budget(
    segments: list[tuple[str, int, bool]],
    tick_s: int,
    pre_connect_s: int,
    start_hour: int,
    start_minute: int,
) -> None:
    """Whatever the phases do, and even for starts that meet the launch window, the last
    extension's deadline is never later than process start + QUOTE_TAPE_MAX_START_SECS."""
    process_start = utc_ns(start_hour, start_minute, 0)
    pinger_start = process_start + pre_connect_s * NS
    deadline_ns = process_start + int(rw.UNIT_TIMEOUT_START_SEC) * NS
    now = pinger_start
    phase_started = pinger_start
    for phase, length_s, hung in segments:
        end = phase_started + length_s * NS
        while now <= end:
            history = [
                sample(
                    now,
                    phase=phase,
                    phase_started_ns=phase_started,
                    safe_mode=phase == PHASE_SAFE_MODE,
                    discovery_attempt_inflight_since_ns=phase_started if hung else 0,
                )
            ]
            verdict = _classify(history, now, ready=False)
            action = decide_action(
                verdict=verdict, ready=False, stop_begun=False, started_ns=pinger_start, now_ns=now
            )
            if action == ACTION_EXTEND:
                deadline_ns = max(deadline_ns, now + int(rw.START_EXTEND_S) * NS)
            now += tick_s * NS
        phase_started = end
    assert deadline_ns <= process_start + node_config.QUOTE_TAPE_MAX_START_SECS * NS


# ------------------------------------------------------------------------------ sd_notify


def test_sd_notify_without_socket_is_false_never_raises() -> None:
    assert sd_notify("READY=1", environ={}) is False
    assert sd_notify("READY=1", environ={"NOTIFY_SOCKET": ""}) is False
    # An unreachable path is a logged-nothing False, never an exception.
    assert sd_notify("READY=1", environ={"NOTIFY_SOCKET": "/nonexistent/dir/notify"}) is False
    assert sd_notify("READY=1", environ={"NOTIFY_SOCKET": "@" + "x" * 500}) is False


def test_sd_notify_without_socket_never_touches_the_process_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    assert sd_notify("WATCHDOG=1") is False


def test_sd_notify_abstract_namespace_socket() -> None:
    name = f"breezy-wp3-{os.getpid()}"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        server.bind("\0" + name)
        assert sd_notify("READY=1", environ={"NOTIFY_SOCKET": "@" + name}) is True
        assert server.recv(64) == b"READY=1"
    finally:
        server.close()


def test_sd_notify_filesystem_socket(tmp_path: Path) -> None:
    path = tmp_path / "notify"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        server.bind(str(path))
        assert sd_notify("WATCHDOG=1", environ={"NOTIFY_SOCKET": str(path)}) is True
        assert server.recv(64) == b"WATCHDOG=1"
    finally:
        server.close()


# ----------------------------------------------------------- hourly log, deferral, journal


class _Scenario:
    """A pinger over a scripted sample stream on a fake clock."""

    def __init__(self, start_ns: int, *, ready: bool = True, samples: Any = None) -> None:
        self.now = start_ns
        self.sent: list[str] = []
        self.log = ListLogger()
        self.samples = samples or (lambda now: sample(now))
        self.pinger = RecorderWatchdogPinger(
            read_sample=lambda: self.samples(self.now),
            clock_ns=lambda: self.now,
            logger=self.log,
            interval_s=5.0,
            notify=self._notify,
            socket_present=True,
        )
        if ready:
            self.pinger.mark_ready()
            self.sent.clear()

    def _notify(self, message: str) -> bool:
        self.sent.append(message)
        return True

    def run(self, seconds: int, *, step_s: int = 5) -> None:
        end = self.now + seconds * NS
        while self.now < end:
            self.pinger.tick()
            self.now += step_s * NS


def test_withheld_line_logged_at_most_hourly() -> None:
    scenario = _Scenario(MORNING, samples=lambda now: sample(now, feed_watch_alive=False))
    scenario.run(2 * 3600 + 60)
    lines = scenario.log.messages("RECORDER_WATCHDOG_WITHHELD")
    assert lines == ["RECORDER_WATCHDOG_WITHHELD cause=feed_watch_dead"] * 3
    assert scenario.sent == []


def test_launch_window_defers_and_journals_once_per_stall() -> None:
    start = utc_ns(16, 40, 0)
    dead = {"on": True}
    scenario = _Scenario(start, samples=lambda now: sample(now, feed_watch_alive=not dead["on"]))
    stall_id = start
    scenario.run(300)
    deferred = scenario.log.messages("RECORDER_WATCHDOG_DEFERRED")
    assert deferred == [deferred_line(stall_id=stall_id, cause=CAUSE_FEED_WATCH_DEAD)]
    assert scenario.sent and set(scenario.sent) == {"WATCHDOG=1"}  # it keeps pinging
    # A recovery ends the stall; the next stall journals once more, with its own id.
    dead["on"] = False
    scenario.run(10)
    dead["on"] = True
    second_start = scenario.now
    scenario.run(60)
    deferred = scenario.log.messages("RECORDER_WATCHDOG_DEFERRED")
    assert len(deferred) == 2 and deferred[1] == deferred_line(
        stall_id=second_start, cause=CAUSE_FEED_WATCH_DEAD
    )


def test_deferral_ends_at_1710z_pinger_stops_pinging() -> None:
    start = utc_ns(17, 9, 0)
    scenario = _Scenario(start, samples=lambda now: sample(now, feed_watch_alive=False))
    scenario.run(60)  # up to 17:10:00, still deferred
    sent_inside = len(scenario.sent)
    assert sent_inside > 0
    scenario.run(120)  # 17:10:00 .. 17:12:00
    assert len(scenario.sent) == sent_inside
    assert scenario.log.messages("RECORDER_WATCHDOG_WITHHELD")


def test_deferred_line_names_stall_start_and_until() -> None:
    line = deferred_line(stall_id=123, cause="writer_stall")
    assert line == (
        "RECORDER_WATCHDOG_DEFERRED stall_id=123 stall_started_ns=123 "
        "cause=writer_stall until=17:10Z"
    )


def test_deferred_fixture_matches_logged_line() -> None:
    entry = json.loads((FIXTURES / "deferred_journal_line.json").read_text())
    message = entry["MESSAGE"]
    text = bytes(message).decode() if isinstance(message, list) else message
    plain = re.sub(r"\x1b\[[0-9;]*m", "", text)
    stall_id = int(re.search(r"stall_id=(\d+)", plain).group(1))  # type: ignore[union-attr]
    cause = re.search(r"cause=(\w+)", plain).group(1)  # type: ignore[union-attr]
    assert plain.endswith(deferred_line(stall_id=stall_id, cause=cause))
    assert "[WARN]" in plain
    assert entry["SYSLOG_IDENTIFIER"] == "breezy-quote-tape"
    assert entry["_SYSTEMD_USER_UNIT"] == "breezy-quote-tape.service"
    assert entry["PRIORITY"] == "4"
    # The module constant AUT-6 imports is the prefix of the logged text.
    assert rw.RECORDER_WATCHDOG_DEFERRED == "RECORDER_WATCHDOG_DEFERRED"
    assert "RECORDER_WATCHDOG_DEFERRED stall_id=" in plain


# -------------------------------------------------------- node-config opt-in and unit pins


def test_trade_node_config_never_sets_watchdog_notify(tmp_path: Path) -> None:
    import ast

    from tests.unit.test_quote_tape_recorder import make_data_client_config, make_tape_settings

    assert make_data_client_config().watchdog_notify is False
    source = Path(node_config.__file__).read_text()
    tree = ast.parse(source)
    setters: list[str] = []
    for fn in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)):
        for node in ast.walk(fn):
            if isinstance(node, ast.keyword) and node.arg == "watchdog_notify":
                setters.append(fn.name)
    assert setters == ["build_quote_tape_node_config"]
    recorder = node_config.build_quote_tape_node_config(
        make_tape_settings(tmp_path), make_data_client_config()
    )
    client_config = next(iter(recorder.data_clients.values()))
    assert client_config.watchdog_notify is True
    assert recorder.instance_id is not None
    assert str(client_config.watchdog_stream_dir).endswith(f"/live/{recorder.instance_id.value}")


def _unit_lines(text: str) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if line and not line.startswith(("#", "[")) and "=" in line:
            key, _, value = line.partition("=")
            found.setdefault(key.strip(), []).append(value.strip())
    return found


def test_classifier_timing_constants_equal_unit_file() -> None:
    """Fixture case (r11, GL1): the pending step-2 unit text pins the classifier constants.

    Step 2 adds the deployed-unit case; no unit file is read here.
    """
    lines = _unit_lines((FIXTURES / "pending_recorder_unit.service").read_text())
    assert int(lines["WatchdogSec"][0]) == rw.UNIT_WATCHDOG_SEC
    assert int(lines["TimeoutStopSec"][0]) == rw.UNIT_TIMEOUT_STOP_SEC
    assert int(lines["TimeoutStartSec"][0]) == rw.UNIT_TIMEOUT_START_SEC
    (stop_post,) = lines["ExecStopPost"]
    match = re.match(r"-/usr/bin/timeout -k (\d+) (\d+) ", stop_post)
    assert match is not None
    assert int(match.group(1)) + int(match.group(2)) == rw.STOP_HOOK_BOUND_S
    assert lines["Type"] == ["notify"]
    assert lines["NotifyAccess"] == ["all"]
    assert lines["WatchdogSignal"] == ["SIGTERM"]
    assert lines["OnFailure"] == ["breezy-autonomy-failed@%n.service"]
    assert len(lines["ExecStart"]) == 1 and "ExecStartPre" not in lines
    assert "RuntimeMaxSec" not in lines


def test_discovery_retry_default_equals_the_node_config_budget() -> None:
    assert rw._DEFAULT_RETRY_SECS == node_config.QUOTE_TAPE_EMPTY_DISCOVERY_RETRY_SECS
    assert rw.extension_window_s() == 3600 + 300 + 300


def test_wp0_constants_are_pinned() -> None:
    assert (
        rw.STREAM_SILENCE_S,
        rw.QUIET_HOURS_MULTIPLIER,
        rw.WRITER_STALL_S,
        rw.FLUSH_MARGIN_S,
        rw.DISCOVERY_ATTEMPT_BUDGET_S,
    ) == (900, 1, 120, 30, 180)
    assert rw.RECORDER_WATCHDOG_STORM_KILLS == 3


# ------------------------------------------------ WP3-R3: flush-margin boundary, notify socket


def _margin_verdict(event_age_s: int) -> str:
    """One event published ``event_age_s`` before now, bytes flat across 200 s."""
    history = series(
        MORNING, 200, events_at=lambda t: 1 if t <= event_age_s else 0, bytes_at=lambda t: 4000
    )
    return _classify(history, MORNING)


def test_event_exactly_at_the_flush_margin_is_a_writer_stall() -> None:
    assert rw.FLUSH_MARGIN_S == 30
    assert _margin_verdict(30) == CAUSE_WRITER_STALL


def test_event_just_inside_the_flush_margin_still_pings() -> None:
    assert _margin_verdict(29) == "OK"


def test_sd_notify_refuses_a_socket_address_that_is_neither_path_nor_abstract() -> None:
    for bad in ("relative/notify", "vsock:2:1234", "notify"):
        assert sd_notify("READY=1", environ={"NOTIFY_SOCKET": bad}) is False
