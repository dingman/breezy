"""RED-first tests: the 17:05 UTC self-check's continuous-family extension.

[2026-09-12] When the supervisor's environment says the continuous family
(``BREEZY_CONTINUOUS_RUNG_HOLD=1``) is active, the self-check ALSO verifies
three named checks -- (a) no ``Phase0PermitForbiddenError`` in the node log,
(b) the durable startup-evidence record is present, fresh (written at/after
today's 16:50 UTC launch), ``eof_complete=True`` and
``position_read_refused=False``, and (c) the family-halt key is absent --
each reported as its own named :class:`SelfCheckResult`/``AlertDetail`` pair.

Flag-absent (``continuous_check=None``) behaviour is BYTE-IDENTICAL to v2:
covered here by re-running the pre-existing ``TestSelfCheck`` scenarios with
the new parameter simply omitted.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.trade_supervisor import (
    ContinuousFamilyStoreState,
    SupervisorPorts,
    _do_self_check,
    continuous_rung_hold_env_active,
    read_continuous_family_store_state,
)
from breezy.runtime.trade_supervisor_core import (
    CONTINUOUS_FAMILY_HALT_CLEARED_MARKER,
    CONTINUOUS_FAMILY_HALT_KEY,
    CONTINUOUS_STARTUP_EVIDENCE_KEY,
    PHASE0_PERMIT_FORBIDDEN_MARKER,
    SELF_CHECK_ALERT_DETAIL,
    AlertDetail,
    ContinuousFamilyCheck,
    SelfCheckResult,
    continuous_family_check,
    continuous_family_is_halted,
    continuous_startup_evidence_valid,
    launch_time_ns,
    self_check,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

_LAUNCH_NS = 1_000_000_000_000
_VALID_EVIDENCE = {
    "ts_ns": _LAUNCH_NS + 1,
    "eof_complete": True,
    "position_read_refused": False,
    "fill_walk_complete": True,
    "positions": [],
}


def _base_kwargs(**overrides) -> dict:
    base = {
        "child_alive": True,
        "flock_holder_count": 1,
        "flock_held_by_tracked_pid": True,
        "permit_issued": True,
        "permit_expiry_valid": True,
        "strategy_subscribed": True,
    }
    base.update(overrides)
    return base


class TestFlagAbsentIsByteIdentical:
    """``continuous_check`` omitted (default ``None``) -- v2 behaviour, unchanged."""

    def test_pass_when_all_signals_true_and_single_holder(self):
        result = self_check(**_base_kwargs())
        assert result is SelfCheckResult.PASS

    def test_shadow_mode_is_its_own_distinct_fail_state(self):
        result = self_check(
            **_base_kwargs(permit_issued=False, permit_expiry_valid=False)
        )
        assert result is SelfCheckResult.FAIL_SHADOW_MODE_NO_PERMIT

    def test_child_exited_fails_first_even_with_a_passing_continuous_check(self):
        """A continuous_check that would itself PASS must never override an
        earlier structural failure -- child_alive is still checked first."""
        passing = ContinuousFamilyCheck(
            phase0_clean=True, startup_evidence_valid=True, family_not_halted=True
        )
        result = self_check(
            **_base_kwargs(child_alive=False), continuous_check=passing
        )
        assert result is SelfCheckResult.FAIL_CHILD_EXITED


class TestContinuousFamilyCheckNamedFailures:
    def test_all_passing_is_plain_pass(self):
        passing = ContinuousFamilyCheck(
            phase0_clean=True, startup_evidence_valid=True, family_not_halted=True
        )
        result = self_check(**_base_kwargs(), continuous_check=passing)
        assert result is SelfCheckResult.PASS

    def test_phase0_forbidden_fails_named(self):
        check = ContinuousFamilyCheck(
            phase0_clean=False, startup_evidence_valid=True, family_not_halted=True
        )
        result = self_check(**_base_kwargs(), continuous_check=check)
        assert result is SelfCheckResult.FAIL_CONTINUOUS_PHASE0_FORBIDDEN
        assert (
            SELF_CHECK_ALERT_DETAIL[result]
            is AlertDetail.SELF_CHECK_FAIL_CONTINUOUS_PHASE0_FORBIDDEN
        )

    def test_startup_evidence_invalid_fails_named(self):
        check = ContinuousFamilyCheck(
            phase0_clean=True, startup_evidence_valid=False, family_not_halted=True
        )
        result = self_check(**_base_kwargs(), continuous_check=check)
        assert result is SelfCheckResult.FAIL_CONTINUOUS_STARTUP_EVIDENCE_INVALID
        assert (
            SELF_CHECK_ALERT_DETAIL[result]
            is AlertDetail.SELF_CHECK_FAIL_CONTINUOUS_STARTUP_EVIDENCE_INVALID
        )

    def test_family_halted_fails_named(self):
        check = ContinuousFamilyCheck(
            phase0_clean=True, startup_evidence_valid=True, family_not_halted=False
        )
        result = self_check(**_base_kwargs(), continuous_check=check)
        assert result is SelfCheckResult.FAIL_CONTINUOUS_FAMILY_HALTED
        assert (
            SELF_CHECK_ALERT_DETAIL[result]
            is AlertDetail.SELF_CHECK_FAIL_CONTINUOUS_FAMILY_HALTED
        )

    def test_first_failing_check_wins_when_several_fail(self):
        check = ContinuousFamilyCheck(
            phase0_clean=False, startup_evidence_valid=False, family_not_halted=False
        )
        result = self_check(**_base_kwargs(), continuous_check=check)
        assert result is SelfCheckResult.FAIL_CONTINUOUS_PHASE0_FORBIDDEN


class TestContinuousFamilyCheckBuilder:
    """``continuous_family_check`` -- pure projection of (log_text,
    startup_evidence, family_halted, launch_ns) onto the three named booleans."""

    def test_all_clean_passes(self):
        result = continuous_family_check(
            log_text="CurrentRungHoldStrategy subscribed X\n",
            startup_evidence=_VALID_EVIDENCE,
            family_halted=False,
            launch_ns=_LAUNCH_NS,
        )
        assert result == ContinuousFamilyCheck(
            phase0_clean=True, startup_evidence_valid=True, family_not_halted=True
        )
        assert result.passed is True

    def test_phase0_forbidden_marker_in_log_fails_that_check_only(self):
        result = continuous_family_check(
            log_text="... continuous_strategy.Phase0PermitForbiddenError: boom\n",
            startup_evidence=_VALID_EVIDENCE,
            family_halted=False,
            launch_ns=_LAUNCH_NS,
        )
        assert result.phase0_clean is False
        assert result.startup_evidence_valid is True
        assert result.family_not_halted is True
        assert result.passed is False

    def test_family_halted_fails_that_check_only(self):
        result = continuous_family_check(
            log_text="",
            startup_evidence=_VALID_EVIDENCE,
            family_halted=True,
            launch_ns=_LAUNCH_NS,
        )
        assert result == ContinuousFamilyCheck(
            phase0_clean=True, startup_evidence_valid=True, family_not_halted=False
        )


class TestContinuousStartupEvidenceValid:
    def test_absent_record_is_invalid(self):
        assert continuous_startup_evidence_valid(None, launch_ns=_LAUNCH_NS) is False

    def test_valid_record_at_exactly_launch_time_is_valid(self):
        evidence = dict(_VALID_EVIDENCE, ts_ns=_LAUNCH_NS)
        assert continuous_startup_evidence_valid(evidence, launch_ns=_LAUNCH_NS) is True

    def test_stale_record_before_launch_is_invalid(self):
        evidence = dict(_VALID_EVIDENCE, ts_ns=_LAUNCH_NS - 1)
        assert continuous_startup_evidence_valid(evidence, launch_ns=_LAUNCH_NS) is False

    def test_eof_not_complete_is_invalid(self):
        evidence = dict(_VALID_EVIDENCE, eof_complete=False)
        assert continuous_startup_evidence_valid(evidence, launch_ns=_LAUNCH_NS) is False

    def test_position_read_refused_is_invalid(self):
        evidence = dict(_VALID_EVIDENCE, position_read_refused=True)
        assert continuous_startup_evidence_valid(evidence, launch_ns=_LAUNCH_NS) is False

    def test_malformed_ts_ns_is_invalid(self):
        evidence = dict(_VALID_EVIDENCE, ts_ns="not-an-int")
        assert continuous_startup_evidence_valid(evidence, launch_ns=_LAUNCH_NS) is False

    def test_bool_ts_ns_is_invalid(self):
        # bool is an int subclass -- must be rejected explicitly, not laundered.
        evidence = dict(_VALID_EVIDENCE, ts_ns=True)
        assert continuous_startup_evidence_valid(evidence, launch_ns=_LAUNCH_NS) is False


class TestLaunchTimeNs:
    def test_matches_1650_utc_on_the_given_day(self):
        import datetime as dt

        day = dt.date(2026, 9, 12)
        expected = dt.datetime(2026, 9, 12, 16, 50, tzinfo=dt.UTC)
        assert launch_time_ns(day) == int(expected.timestamp() * 1e9)


class TestMarkerAndKeyConstantsPinnedAgainstRealEmitters:
    """Same discipline as ``PERMIT_ISSUED_MARKER``/``STRATEGY_SUBSCRIBED_MARKER``
    in ``test_trade_supervisor.py``: a reworded emitter or a renamed store key
    fails this test, not just a hardcoded duplicate."""

    def test_phase0_permit_forbidden_marker_is_the_real_exception_class_name(self):
        source = (
            REPO_ROOT / "src/breezy/strategy/current_rung_hold/continuous_strategy.py"
        ).read_text()
        assert f"class {PHASE0_PERMIT_FORBIDDEN_MARKER}(" in source

    def test_startup_evidence_key_matches_the_real_client_and_latch(self):
        latch_source = (
            REPO_ROOT / "src/breezy/strategy/current_rung_hold/trial_day_latch.py"
        ).read_text()
        assert f'"{CONTINUOUS_STARTUP_EVIDENCE_KEY}"' in latch_source

    def test_family_halt_key_matches_the_real_latch(self):
        latch_source = (
            REPO_ROOT / "src/breezy/strategy/current_rung_hold/trial_day_latch.py"
        ).read_text()
        assert f'"{CONTINUOUS_FAMILY_HALT_KEY}"' in latch_source


# ---------------------------------------------------------------------------
# I/O shell -- env-flag read, the read-only store read, and `_do_self_check`
# wiring end to end.
# ---------------------------------------------------------------------------


class _RecordingAlertSink:
    def __init__(self) -> None:
        self.payloads: list[object] = []

    def emit(self, payload: object) -> None:
        self.payloads.append(payload)


def _make_ports(**overrides) -> SupervisorPorts:
    base = {
        "find_node_pid": lambda: None,
        "resolve_intent_lock_holder": lambda _p: 42,
        "intent_lock_free": lambda _p: True,
        "count_intent_lock_holders": lambda _p: 1,
        "terminate_after_recheck": lambda pid, **kw: None,
        "process_alive": lambda _pid: True,
        "probe_open_intent_state": lambda *a, **kw: False,
        "spawn": lambda **kw: None,
        "read_log_new": lambda _p: "CurrentRungHoldStrategy subscribed X\n",
        "alert_sink": _RecordingAlertSink(),
    }
    base.update(overrides)
    return SupervisorPorts(**base)


_READY_LOG_LINE = (
    "live-trading permit issued issued_at_ns=1 expires_at_ns=4102444800000000000 ttl_s=1\n"
    "CurrentRungHoldStrategy subscribed X\n"
)


class TestContinuousRungHoldEnvActive:
    def test_true_only_for_exactly_the_string_1(self, monkeypatch):
        monkeypatch.setenv("BREEZY_CONTINUOUS_RUNG_HOLD", "1")
        assert continuous_rung_hold_env_active() is True

    def test_false_when_absent(self, monkeypatch):
        monkeypatch.delenv("BREEZY_CONTINUOUS_RUNG_HOLD", raising=False)
        assert continuous_rung_hold_env_active() is False

    def test_false_for_any_other_value(self, monkeypatch):
        monkeypatch.setenv("BREEZY_CONTINUOUS_RUNG_HOLD", "true")
        assert continuous_rung_hold_env_active() is False


class TestReadContinuousFamilyStoreState:
    def test_absent_keys_read_as_none_and_not_halted(self, tmp_path):
        store_path = tmp_path / "state" / "store.sqlite3"
        with SqliteStateStore(store_path):
            pass  # just create the file/table, write nothing
        state = read_continuous_family_store_state(store_path)
        assert state == ContinuousFamilyStoreState(startup_evidence=None, family_halted=False)

    def test_reads_the_evidence_and_halt_keys_the_client_writes(self, tmp_path):
        store_path = tmp_path / "state" / "store.sqlite3"
        evidence = {"ts_ns": 1, "eof_complete": True, "position_read_refused": False}
        with SqliteStateStore(store_path) as store:
            store.set(
                CONTINUOUS_STARTUP_EVIDENCE_KEY,
                json.dumps(evidence).encode("utf-8"),
            )
            store.set(CONTINUOUS_FAMILY_HALT_KEY, b'{"v":1}')
        state = read_continuous_family_store_state(store_path)
        assert state.startup_evidence == evidence
        assert state.family_halted is True

    def test_malformed_evidence_bytes_decode_as_none_not_raise(self, tmp_path):
        store_path = tmp_path / "state" / "store.sqlite3"
        with SqliteStateStore(store_path) as store:
            store.set(CONTINUOUS_STARTUP_EVIDENCE_KEY, b"not json")
        state = read_continuous_family_store_state(store_path)
        assert state.startup_evidence is None

    def test_read_is_safe_via_a_second_independent_connection_while_a_writer_handle_is_open(
        self, tmp_path
    ):
        """The exact scenario this exists for: the node's own writer
        connection stays open (as it does at 17:05 UTC) while the
        supervisor opens its OWN read-only connection concurrently."""
        store_path = tmp_path / "state" / "store.sqlite3"
        with SqliteStateStore(store_path) as writer:
            writer.set(CONTINUOUS_FAMILY_HALT_KEY, b'{"v":1}')
            # writer handle still open here -- the read below must not block
            # or raise against it (WAL serves concurrent readers).
            state = read_continuous_family_store_state(store_path)
        assert state.family_halted is True


class TestDoSelfCheckContinuousWiring:
    def test_flag_absent_behaviour_is_unchanged(self, tmp_path):
        store_path = tmp_path / "state" / "store.sqlite3"
        sink = _RecordingAlertSink()
        ports = _make_ports(read_log_new=lambda _p: _READY_LOG_LINE, alert_sink=sink)
        _do_self_check(
            ports=ports,
            now=dt.datetime(2026, 9, 12, 17, 5, tzinfo=dt.UTC),
            store_path=store_path,
            log_dir=tmp_path / "logs",
            tracked_pid=42,
            node_log=tmp_path / "n.log",
        )
        assert sink.payloads == []

    def test_continuous_active_all_clean_is_pass_no_alert(self, tmp_path):
        store_path = tmp_path / "state" / "store.sqlite3"
        sink = _RecordingAlertSink()
        launch_ns = launch_time_ns(dt.date(2026, 9, 12))
        store_state = ContinuousFamilyStoreState(
            startup_evidence={
                "ts_ns": launch_ns + 1,
                "eof_complete": True,
                "position_read_refused": False,
            },
            family_halted=False,
        )
        ports = _make_ports(
            read_log_new=lambda _p: _READY_LOG_LINE,
            alert_sink=sink,
            continuous_family_active=lambda: True,
            read_continuous_family_store_state=lambda _p: store_state,
        )
        _do_self_check(
            ports=ports,
            now=dt.datetime(2026, 9, 12, 17, 5, tzinfo=dt.UTC),
            store_path=store_path,
            log_dir=tmp_path / "logs",
            tracked_pid=42,
            node_log=tmp_path / "n.log",
        )
        assert sink.payloads == []

    def test_continuous_active_phase0_forbidden_in_log_alerts_named(self, tmp_path):
        store_path = tmp_path / "state" / "store.sqlite3"
        sink = _RecordingAlertSink()
        launch_ns = launch_time_ns(dt.date(2026, 9, 12))
        store_state = ContinuousFamilyStoreState(
            startup_evidence={
                "ts_ns": launch_ns + 1,
                "eof_complete": True,
                "position_read_refused": False,
            },
            family_halted=False,
        )
        log_with_error = _READY_LOG_LINE + f"...{PHASE0_PERMIT_FORBIDDEN_MARKER}: boom\n"
        ports = _make_ports(
            read_log_new=lambda _p: log_with_error,
            alert_sink=sink,
            continuous_family_active=lambda: True,
            read_continuous_family_store_state=lambda _p: store_state,
        )
        _do_self_check(
            ports=ports,
            now=dt.datetime(2026, 9, 12, 17, 5, tzinfo=dt.UTC),
            store_path=store_path,
            log_dir=tmp_path / "logs",
            tracked_pid=42,
            node_log=tmp_path / "n.log",
        )
        assert len(sink.payloads) == 1
        assert (
            sink.payloads[0].detail
            == AlertDetail.SELF_CHECK_FAIL_CONTINUOUS_PHASE0_FORBIDDEN.value
        )

    def test_continuous_active_stale_startup_evidence_alerts_named(self, tmp_path):
        store_path = tmp_path / "state" / "store.sqlite3"
        sink = _RecordingAlertSink()
        launch_ns = launch_time_ns(dt.date(2026, 9, 12))
        store_state = ContinuousFamilyStoreState(
            startup_evidence={
                "ts_ns": launch_ns - 1,  # written BEFORE today's launch -- stale
                "eof_complete": True,
                "position_read_refused": False,
            },
            family_halted=False,
        )
        ports = _make_ports(
            read_log_new=lambda _p: _READY_LOG_LINE,
            alert_sink=sink,
            continuous_family_active=lambda: True,
            read_continuous_family_store_state=lambda _p: store_state,
        )
        _do_self_check(
            ports=ports,
            now=dt.datetime(2026, 9, 12, 17, 5, tzinfo=dt.UTC),
            store_path=store_path,
            log_dir=tmp_path / "logs",
            tracked_pid=42,
            node_log=tmp_path / "n.log",
        )
        assert len(sink.payloads) == 1
        assert (
            sink.payloads[0].detail
            == AlertDetail.SELF_CHECK_FAIL_CONTINUOUS_STARTUP_EVIDENCE_INVALID.value
        )

    def test_continuous_active_family_halted_alerts_named(self, tmp_path):
        store_path = tmp_path / "state" / "store.sqlite3"
        sink = _RecordingAlertSink()
        launch_ns = launch_time_ns(dt.date(2026, 9, 12))
        store_state = ContinuousFamilyStoreState(
            startup_evidence={
                "ts_ns": launch_ns + 1,
                "eof_complete": True,
                "position_read_refused": False,
            },
            family_halted=True,
        )
        ports = _make_ports(
            read_log_new=lambda _p: _READY_LOG_LINE,
            alert_sink=sink,
            continuous_family_active=lambda: True,
            read_continuous_family_store_state=lambda _p: store_state,
        )
        _do_self_check(
            ports=ports,
            now=dt.datetime(2026, 9, 12, 17, 5, tzinfo=dt.UTC),
            store_path=store_path,
            log_dir=tmp_path / "logs",
            tracked_pid=42,
            node_log=tmp_path / "n.log",
        )
        assert len(sink.payloads) == 1
        assert (
            sink.payloads[0].detail == AlertDetail.SELF_CHECK_FAIL_CONTINUOUS_FAMILY_HALTED.value
        )


# ---------------------------------------------------------------------------
# [2026-09-12 cross-seam fix] The store has no delete, so
# `breezy-clear-family-halt` overwrites FAMILY_HALT_KEY with a distinguishable
# "cleared" sentinel rather than an absent key. Key-present must NOT mean
# halted any more -- only "present AND not the cleared sentinel" does.
# ---------------------------------------------------------------------------


class TestContinuousFamilyIsHalted:
    """Pure mirror of ``TrialDayLatch.is_family_halted()``: absent key or the
    exact cleared sentinel is NOT halted; any other stored value (including
    corrupt/unknown bytes) IS halted -- fail-closed, matching the strategy
    layer's own stance."""

    def test_absent_key_is_not_halted(self):
        assert continuous_family_is_halted(None) is False

    def test_cleared_sentinel_is_not_halted(self):
        assert continuous_family_is_halted(CONTINUOUS_FAMILY_HALT_CLEARED_MARKER) is False

    def test_a_genuine_halt_payload_is_halted(self):
        assert continuous_family_is_halted(b'{"v":1,"reason":"duplicate_fill"}') is True

    def test_corrupt_or_unknown_bytes_are_halted_fail_closed(self):
        assert continuous_family_is_halted(b"not json") is True
        assert continuous_family_is_halted(b"") is True


class TestReadContinuousFamilyStoreStateHonoursTheClearedSentinel:
    def test_cleared_sentinel_reads_as_not_halted(self, tmp_path):
        store_path = tmp_path / "state" / "store.sqlite3"
        with SqliteStateStore(store_path) as store:
            store.set(CONTINUOUS_FAMILY_HALT_KEY, CONTINUOUS_FAMILY_HALT_CLEARED_MARKER)
        state = read_continuous_family_store_state(store_path)
        assert state.family_halted is False

    def test_a_genuine_halt_payload_reads_as_halted(self, tmp_path):
        store_path = tmp_path / "state" / "store.sqlite3"
        with SqliteStateStore(store_path) as store:
            store.set(CONTINUOUS_FAMILY_HALT_KEY, b'{"v":1,"reason":"duplicate_fill"}')
        state = read_continuous_family_store_state(store_path)
        assert state.family_halted is True


class TestDoSelfCheckPassesAfterALegitimateClear:
    def test_cleared_halt_key_self_check_passes_no_alert(self, tmp_path):
        """RED case this fix targets: before the fix, ANY value at
        FAMILY_HALT_KEY (including the cleared sentinel) read as halted, so
        the 17:05Z self-check would FAIL forever after a legitimate clear."""
        store_path = tmp_path / "state" / "store.sqlite3"
        sink = _RecordingAlertSink()
        with SqliteStateStore(store_path) as store:
            store.set(CONTINUOUS_FAMILY_HALT_KEY, CONTINUOUS_FAMILY_HALT_CLEARED_MARKER)
        launch_ns = launch_time_ns(dt.date(2026, 9, 12))
        with SqliteStateStore(store_path) as store:
            store.set(
                CONTINUOUS_STARTUP_EVIDENCE_KEY,
                json.dumps(
                    {
                        "ts_ns": launch_ns + 1,
                        "eof_complete": True,
                        "position_read_refused": False,
                    }
                ).encode("utf-8"),
            )
        ports = _make_ports(
            read_log_new=lambda _p: _READY_LOG_LINE,
            alert_sink=sink,
            continuous_family_active=lambda: True,
            read_continuous_family_store_state=read_continuous_family_store_state,
        )
        _do_self_check(
            ports=ports,
            now=dt.datetime(2026, 9, 12, 17, 5, tzinfo=dt.UTC),
            store_path=store_path,
            log_dir=tmp_path / "logs",
            tracked_pid=42,
            node_log=tmp_path / "n.log",
        )
        assert sink.payloads == []


# ---------------------------------------------------------------------------
# WP-0a: the live family logs ``ContinuousRungHoldStrategy subscribed``;
# the hardcoded ``CurrentRungHoldStrategy subscribed`` marker currently
# false-fails the 17:05Z self-check as FAIL_NODE_NOT_READY.
# ---------------------------------------------------------------------------

_CONTINUOUS_READY_LOG_LINE = (
    "live-trading permit issued issued_at_ns=1 expires_at_ns=4102444800000000000 ttl_s=1\n"
    "ContinuousRungHoldStrategy subscribed X\n"
)


def _clean_continuous_store_state(*, day: dt.date) -> ContinuousFamilyStoreState:
    launch_ns = launch_time_ns(day)
    return ContinuousFamilyStoreState(
        startup_evidence={
            "ts_ns": launch_ns + 1,
            "eof_complete": True,
            "position_read_refused": False,
        },
        family_halted=False,
    )


class TestWp0aSubscribeMarkerAcceptsBothPrefixes:
    """Both rung-hold class-name prefixes must make 17:05Z self-check PASS.

    WP-11b later parameterises the marker by ``composition_kind``; this
    package only accepts the two prefixes.
    """

    def _run_self_check(self, tmp_path, *, log_text: str) -> _RecordingAlertSink:
        store_path = tmp_path / "state" / "store.sqlite3"
        sink = _RecordingAlertSink()
        ports = _make_ports(
            read_log_new=lambda _p: log_text,
            alert_sink=sink,
            continuous_family_active=lambda: True,
            read_continuous_family_store_state=lambda _p: _clean_continuous_store_state(
                day=dt.date(2026, 9, 12)
            ),
        )
        _do_self_check(
            ports=ports,
            now=dt.datetime(2026, 9, 12, 17, 5, tzinfo=dt.UTC),
            store_path=store_path,
            log_dir=tmp_path / "logs",
            tracked_pid=42,
            node_log=tmp_path / "n.log",
        )
        return sink

    def test_continuous_family_log_line_self_check_passes(self, tmp_path):
        """Live-family subscribe line must PASS; today it is FAIL_NODE_NOT_READY."""
        sink = self._run_self_check(tmp_path, log_text=_CONTINUOUS_READY_LOG_LINE)
        assert sink.payloads == []

    def test_current_rung_hold_log_line_self_check_still_passes(self, tmp_path):
        """The original CurrentRungHoldStrategy prefix must keep PASSing."""
        sink = self._run_self_check(tmp_path, log_text=_READY_LOG_LINE)
        assert sink.payloads == []


class TestRuntimeLiteralsPinnedAgainstTheStrategyLayer:
    """[2026-09-12] Tests may import both layers even though production code
    must not (runtime never imports strategy -- the layers contract). This
    is the ONE place the three duplicated literals are asserted equal to
    their strategy-layer originals, so they can never drift silently."""

    def test_family_halt_key_matches_the_strategy_layer_constant(self):
        from breezy.strategy.current_rung_hold.trial_day_latch import FAMILY_HALT_KEY

        assert CONTINUOUS_FAMILY_HALT_KEY == FAMILY_HALT_KEY

    def test_startup_evidence_key_matches_the_strategy_layer_constant(self):
        from breezy.strategy.current_rung_hold.trial_day_latch import STARTUP_EVIDENCE_KEY

        assert CONTINUOUS_STARTUP_EVIDENCE_KEY == STARTUP_EVIDENCE_KEY

    def test_cleared_sentinel_matches_the_strategy_layer_constant(self):
        from breezy.strategy.current_rung_hold.trial_day_latch import _HALT_CLEARED_MARKER

        assert CONTINUOUS_FAMILY_HALT_CLEARED_MARKER == _HALT_CLEARED_MARKER
