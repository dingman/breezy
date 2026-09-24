"""RED-first tests for the daily trade-node supervisor.

Covers the build-stage test obligations stated at the end of
``docs/plans/TRADE_NODE_DAILY_RELAUNCH_2026-09-04.md`` (Rev 3, converged
peer review): the three control-flow substrings pinned against the real
emitters; the bounded-relaunch attempt/gap/cutoff/readiness rules; the
adoption same-PID rule; ``RLIMIT_CORE == (0, 0)`` in both processes; that no
log record or alert ``detail`` ever carries an environ value or exception
text; that this module never sends SIGKILL; that the OPEN-intent probe
refuses to run while a node PID is live; and that
``TradingNode: RUNNING``/``Execution state reconciled`` are never consulted.
"""

from __future__ import annotations

import ast
import datetime as dt
import fcntl
import logging
import os
import signal
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest

from breezy.adapters.polymarket_us.factories import EXEC_STATE_DB_ENV_VAR
from breezy.runtime.health import AlertPayload
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.stop_intent_marker import consume_stop_intent_marker, stop_intent_marker_path
from breezy.runtime.submit_intent import RetirementReason, open_submit_intent_latch
from breezy.runtime.trade_supervisor import (
    BUILD_REVISION_ENV_VAR,
    EXIT_CONFIG_ERROR,
    EXIT_OK,
    NODE_CONSOLE_SCRIPT,
    IncrementalLogReader,
    StopPriorRaceRefused,
    SupervisorPorts,
    _do_launch,
    _do_midday_watch,
    _do_relaunch_check,
    _do_self_check,
    _do_stop_prior,
    _read_git_head_sha,
    _resolve_build_revision,
    _run_forever,
    _SELF_CHECK_PASS_RESULTS,
    _SupervisorFileHandler,
    _SupervisorStreamHandler,
    configure_supervisor_logging,
    count_lock_holders,
    find_adopted_node_log,
    hold_supervisor_lock,
    intent_lock_is_free,
    intent_lock_path,
    log_decision,
    main,
    node_log_path,
    probe_open_intent,
    process_is_alive,
    resolve_lock_holder_pid,
    spawn_node,
    supervisor_lock_path,
    supervisor_log_path,
    terminate,
    terminate_after_toctou_recheck,
)
from breezy.runtime.trade_supervisor_core import (
    MAX_RELAUNCH_ATTEMPTS,
    MIDDAY_MAX_RELAUNCH_ATTEMPTS,
    MIDDAY_MIN_RELAUNCH_GAP,
    MIDDAY_READINESS_RECHECK_TIMEOUT,
    MIN_RELAUNCH_GAP,
    RELAUNCH_CUTOFF_UTC,
    SELF_CHECK_ESCALATION_STORE_KEY,
    SUPERVISOR_ARGV_TOKEN,
    AlertDetail,
    EscalationLoadOutcome,
    ExitConfigErrorCause,
    LaunchAction,
    Phase,
    PreLaunchProbeInvariantError,
    RelaunchCause,
    SelfCheckEscalationState,
    SelfCheckResult,
    StopPriorAction,
    _PASS_RESULT_VALUES,
    assert_no_live_node_before_intent_probe,
    classify_exit1_cause,
    decide_launch_action,
    decide_midday_relaunch,
    decide_relaunch,
    decide_stop_prior_action,
    decode_self_check_escalation_state,
    disambiguate_exit_config_error,
    encode_self_check_escalation_state,
    initial_scheduler_state,
    mark_phase_fired,
    midday_watch_window_end,
    next_due,
    parse_permit_expiry_ns,
    readiness_observed,
    record_midday_cause_seen,
    record_permit_issued_seen,
    record_readiness_observed,
    record_relaunch_attempt,
    record_strategy_subscribed_seen,
    self_check,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# Production observation: a test in this module (`main()` called with no
# HOME isolation) once wrote straight into the REAL
# ``~/.local/share/breezy/logs/breezy-trade-supervisor.log`` -- then every
# later test's `log_decision` call kept landing there too, because the
# module logger is process-global and nothing tore the leaked FileHandler
# down. These two autouse fixtures make that structurally impossible for
# every test in this module, and the module-scoped one fails loudly if a
# future test ever manages it anyway.
#
# ``_REAL_HOME``/``_REAL_SUPERVISOR_LOG_PATH`` are captured at IMPORT time,
# before any fixture runs and before ``Path.home`` is ever monkeypatched --
# they are read-only reference points, never a target this suite writes to.
# ---------------------------------------------------------------------------

_REAL_HOME = Path.home()
_REAL_SUPERVISOR_LOG_DIR = _REAL_HOME / ".local" / "share" / "breezy" / "logs"


def _stat_or_none(path: Path) -> tuple[int, float] | None:
    try:
        stat_result = path.stat()
    except FileNotFoundError:
        return None
    return (stat_result.st_size, stat_result.st_mtime)


@pytest.fixture(autouse=True)
def _clear_retained_spawned_children():
    """WP-0a: ``_SPAWNED_CHILDREN`` is process-global; pytest-randomly
    otherwise lets a FakePopen from one test shadow a later pid probe."""
    from breezy.runtime import trade_supervisor as ts

    ts._SPAWNED_CHILDREN.clear()
    yield
    ts._SPAWNED_CHILDREN.clear()


@pytest.fixture(autouse=True)
def _isolate_home_and_reset_supervisor_logger(monkeypatch, tmp_path):
    """Autouse for EVERY test in this module: ``Path.home()`` never
    resolves to the operator's real home for the duration of any test
    here, and the module logger's own handlers (the two marker
    subclasses -- never pytest's own capture handler) are torn down after
    each test so a handler configured by one test can never carry that
    test's (or a later test's) ``log_decision`` calls into a file left
    over from a previous test.
    """
    fake_home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    yield
    _reset_supervisor_logging_handlers()


@pytest.fixture(scope="module", autouse=True)
def _guard_real_supervisor_log_untouched():
    """Module-scoped finalizer: snapshot the REAL supervisor log's
    size/mtime (via the never-monkeypatched ``_REAL_HOME`` above) before
    the first test in this module runs, and assert it is byte-for-byte
    unchanged after the last one. Read-only ``stat`` calls only -- this
    never opens, truncates, or edits that file.
    """
    before = _stat_or_none(supervisor_log_path(_REAL_SUPERVISOR_LOG_DIR))
    yield
    after = _stat_or_none(supervisor_log_path(_REAL_SUPERVISOR_LOG_DIR))
    assert after == before, (
        "a test in tests/unit/test_trade_supervisor.py modified the REAL "
        f"supervisor log at {supervisor_log_path(_REAL_SUPERVISOR_LOG_DIR)} "
        f"-- (size, mtime) changed from {before} to {after}"
    )


def test_every_test_in_this_module_is_isolated_from_the_real_home_log_dir():
    """Guards the isolation fixture itself: inside any test in this
    module, ``Path.home()`` must never equal the real ``_REAL_HOME``
    captured at import time."""
    assert Path.home() != _REAL_HOME


# ---------------------------------------------------------------------------
# Obligation: pin the three control-flow substrings against the real
# emitters -- read the actual source, don't just duplicate a literal.
# ---------------------------------------------------------------------------


def test_permit_issued_marker_is_a_substring_of_the_real_emitter():
    from breezy.runtime.trade_supervisor_core import PERMIT_ISSUED_MARKER

    source = (REPO_ROOT / "src/breezy/app/trade.py").read_text()
    assert PERMIT_ISSUED_MARKER in source


def test_permit_not_issued_marker_is_a_substring_of_the_real_emitter():
    from breezy.runtime.trade_supervisor_core import PERMIT_NOT_ISSUED_MARKER

    source = (REPO_ROOT / "src/breezy/app/trade.py").read_text()
    assert PERMIT_NOT_ISSUED_MARKER in source


def test_trading_node_failed_marker_is_a_substring_of_the_real_emitter():
    from breezy.runtime.trade_supervisor_core import TRADING_NODE_FAILED_MARKER

    source = (REPO_ROOT / "src/breezy/runtime/trade_cli.py").read_text()
    assert TRADING_NODE_FAILED_MARKER in source


def test_strategy_subscribed_marker_is_a_substring_of_the_real_emitter():
    from breezy.runtime.trade_supervisor_core import STRATEGY_SUBSCRIBED_MARKER

    source = (REPO_ROOT / "src/breezy/strategy/current_rung_hold/strategy.py").read_text()
    assert STRATEGY_SUBSCRIBED_MARKER in source


def test_continuous_strategy_subscribed_marker_matches_the_real_emitter():
    """Live-family emitter is ``f"{_CLASS_NAME} subscribed ...``; pin both
    the class-name constant and the format string so a rename cannot
    silently revive FAIL_NODE_NOT_READY."""
    from breezy.runtime.trade_supervisor_core import CONTINUOUS_STRATEGY_SUBSCRIBED_MARKER

    source = (
        REPO_ROOT / "src/breezy/strategy/current_rung_hold/continuous_strategy.py"
    ).read_text()
    assert '_CLASS_NAME: Final[str] = "ContinuousRungHoldStrategy"' in source
    assert 'f"{_CLASS_NAME} subscribed' in source
    assert CONTINUOUS_STRATEGY_SUBSCRIBED_MARKER == "ContinuousRungHoldStrategy subscribed"


def test_fatal_market_data_fault_marker_is_a_substring_of_the_real_emitter():
    from breezy.runtime.trade_supervisor_core import FATAL_MARKET_DATA_FAULT_MARKER

    source = (REPO_ROOT / "src/breezy/runtime/trade_cli.py").read_text()
    assert FATAL_MARKET_DATA_FAULT_MARKER in source


def test_fatal_exec_client_fault_marker_is_a_substring_of_the_real_emitter():
    from breezy.runtime.trade_supervisor_core import FATAL_EXEC_CLIENT_FAULT_MARKER

    source = (REPO_ROOT / "src/breezy/runtime/trade_cli.py").read_text()
    assert FATAL_EXEC_CLIENT_FAULT_MARKER in source


def test_module_source_never_consults_tradingnode_running_string():
    for path in (
        REPO_ROOT / "src/breezy/runtime/trade_supervisor.py",
        REPO_ROOT / "src/breezy/runtime/trade_supervisor_core.py",
    ):
        source = path.read_text()
        code_only = "\n".join(
            line for line in source.splitlines() if not line.strip().startswith("#")
        )
        # The docstrings explicitly NAME these strings in prose (to document
        # that they are never consulted); this test asserts the two literal
        # Nautilus strings never appear as quoted string literals used in a
        # comparison/membership expression.
        assert '"TradingNode: RUNNING"' not in code_only
        assert "'TradingNode: RUNNING'" not in code_only
        assert '"Execution state reconciled"' not in code_only
        assert "'Execution state reconciled'" not in code_only


def test_module_source_never_references_the_sigkill_signal():
    """Prose explaining the invariant ("never SIGKILL") is fine in comments
    and docstrings; an actual AST reference to the ``SIGKILL`` name (an
    attribute access like ``signal.SIGKILL`` or a bare imported name) is
    not. Parsed with ``ast`` specifically so this test is blind to string
    and comment content and cannot be satisfied by rewording prose."""
    for path in (
        REPO_ROOT / "src/breezy/runtime/trade_supervisor.py",
        REPO_ROOT / "src/breezy/runtime/trade_supervisor_core.py",
    ):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                assert node.attr != "SIGKILL", f"{path}: signal.SIGKILL referenced"
            if isinstance(node, ast.Name):
                assert node.id != "SIGKILL", f"{path}: bare SIGKILL referenced"


# ---------------------------------------------------------------------------
# [B2/E5] Adoption same-PID rule.
# ---------------------------------------------------------------------------


class TestDecideStopPriorAction:
    def test_both_none_is_noop(self):
        assert (
            decide_stop_prior_action(discovered_node_pid=None, lock_holder_pid=None)
            is StopPriorAction.NOOP
        )

    def test_matching_pids_sigterms_the_tracked_process(self):
        assert (
            decide_stop_prior_action(discovered_node_pid=4321, lock_holder_pid=4321)
            is StopPriorAction.SIGTERM_TRACKED
        )

    def test_disagreeing_pids_refuse_and_alert(self):
        assert (
            decide_stop_prior_action(discovered_node_pid=111, lock_holder_pid=222)
            is StopPriorAction.REFUSE_ALERT
        )

    def test_lock_held_with_no_discovered_process_refuses(self):
        assert (
            decide_stop_prior_action(discovered_node_pid=None, lock_holder_pid=999)
            is StopPriorAction.REFUSE_ALERT
        )

    def test_discovered_process_not_holding_the_lock_refuses(self):
        assert (
            decide_stop_prior_action(discovered_node_pid=555, lock_holder_pid=None)
            is StopPriorAction.REFUSE_ALERT
        )

    def test_never_returns_a_sigkill_action(self):
        for discovered, holder in [(1, 1), (1, 2), (None, 1), (1, None), (None, None)]:
            action = decide_stop_prior_action(
                discovered_node_pid=discovered, lock_holder_pid=holder
            )
            assert "SIGKILL" not in action.value.upper()


# ---------------------------------------------------------------------------
# [R6/B1] Launch decision.
# ---------------------------------------------------------------------------


class TestDecideLaunchAction:
    def test_launches_when_lock_free_and_no_open_intent(self):
        assert (
            decide_launch_action(lock_free=True, open_intent_detected=False) is LaunchAction.LAUNCH
        )

    def test_refuses_when_lock_held_even_if_intent_state_unknown(self):
        assert (
            decide_launch_action(lock_free=False, open_intent_detected=False)
            is LaunchAction.REFUSE_LOCK_HELD
        )
        assert (
            decide_launch_action(lock_free=False, open_intent_detected=True)
            is LaunchAction.REFUSE_LOCK_HELD
        )

    def test_refuses_when_intent_open(self):
        assert (
            decide_launch_action(lock_free=True, open_intent_detected=True)
            is LaunchAction.REFUSE_INTENT_OPEN
        )


# ---------------------------------------------------------------------------
# [B1/E5 scope] The OPEN-intent probe refuses to run while a node PID is live.
# ---------------------------------------------------------------------------


class TestPreLaunchProbeInvariant:
    def test_raises_when_a_node_pid_is_live(self):
        with pytest.raises(PreLaunchProbeInvariantError):
            assert_no_live_node_before_intent_probe(12345)

    def test_passes_silently_when_no_node_pid(self):
        assert_no_live_node_before_intent_probe(None)

    def test_probe_open_intent_refuses_before_touching_the_store(self, tmp_path):
        store_path = tmp_path / "does-not-exist" / "store.sqlite3"
        with pytest.raises(PreLaunchProbeInvariantError):
            probe_open_intent(store_path, node_pid=42)
        # The invariant fires before any SqliteStateStore is opened -- the
        # parent directory (and therefore the store file) was never created.
        assert not store_path.parent.exists()

    def test_probe_open_intent_false_when_nothing_armed(self, tmp_path):
        store_path = tmp_path / "state" / "store.sqlite3"
        store_path.parent.mkdir(parents=True)
        assert probe_open_intent(store_path, node_pid=None) is False

    def test_probe_open_intent_true_when_open(self, tmp_path):
        store_path = tmp_path / "state" / "store.sqlite3"
        store_path.parent.mkdir(parents=True)
        with (
            SqliteStateStore(store_path) as store,
            open_submit_intent_latch(store, store_path) as latch,
        ):
            latch.arm("a" * 64, now_ns=1)

        assert probe_open_intent(store_path, node_pid=None) is True

    def test_probe_open_intent_false_when_retired(self, tmp_path):
        store_path = tmp_path / "state" / "store.sqlite3"
        store_path.parent.mkdir(parents=True)
        with (
            SqliteStateStore(store_path) as store,
            open_submit_intent_latch(store, store_path) as latch,
        ):
            intent = latch.arm("b" * 64, now_ns=1)
            latch.retire(
                intent.intent_id,
                RetirementReason.ACCEPTED_ZERO_FILL_TERMINAL,
                now_ns=2,
            )

        assert probe_open_intent(store_path, node_pid=None) is False


# ---------------------------------------------------------------------------
# [B3/E1] Readiness -- the three-way conjunction only.
# ---------------------------------------------------------------------------


class TestReadinessObserved:
    def test_true_only_when_all_three_signals_present(self):
        assert (
            readiness_observed(holds_intent_lock=True, permit_issued=True, strategy_subscribed=True)
            is True
        )

    @pytest.mark.parametrize(
        "holds_intent_lock,permit_issued,strategy_subscribed",
        [
            (False, True, True),
            (True, False, True),
            (True, True, False),
            (False, False, False),
        ],
    )
    def test_false_when_any_signal_missing(
        self, holds_intent_lock, permit_issued, strategy_subscribed
    ):
        assert (
            readiness_observed(
                holds_intent_lock=holds_intent_lock,
                permit_issued=permit_issued,
                strategy_subscribed=strategy_subscribed,
            )
            is False
        )


# ---------------------------------------------------------------------------
# [E4] Exit-1 cause classification and bounded relaunch.
# ---------------------------------------------------------------------------


class TestClassifyExit1Cause:
    def test_permit_not_issued_is_deterministic(self):
        log = "...\norder submission permit not issued: RungHoldNotReadyError\n"
        assert classify_exit1_cause(log) is RelaunchCause.DETERMINISTIC

    def test_trading_node_failed_is_transient(self):
        log = "breezy-trade: trading node failed: ConnectionError\n"
        assert classify_exit1_cause(log) is RelaunchCause.TRANSIENT

    def test_neither_marker_is_unknown(self):
        assert classify_exit1_cause("some unrelated crash trace") is RelaunchCause.UNKNOWN

    def test_deterministic_marker_wins_if_both_present(self):
        log = "order submission permit not issued: X\ntrading node failed: Y\n"
        assert classify_exit1_cause(log) is RelaunchCause.DETERMINISTIC

    def test_classify_exit1_cause_market_data_fault_is_transient(self):
        log = "breezy-trade: FATAL market-data fault in Foo: bar. The trading process shut down.\n"
        assert classify_exit1_cause(log) is RelaunchCause.TRANSIENT

    def test_classify_exit1_cause_exec_client_fault_is_transient(self):
        log = (
            "breezy-trade: FATAL execution-client fault in Foo: bar. "
            "The trading process shut down.\n"
        )
        assert classify_exit1_cause(log) is RelaunchCause.TRANSIENT

    def test_classify_exit1_cause_still_prefers_deterministic_marker(self):
        log = (
            "order submission permit not issued: X\n"
            "breezy-trade: FATAL market-data fault in Foo: bar. The trading process shut down.\n"
        )
        assert classify_exit1_cause(log) is RelaunchCause.DETERMINISTIC


class TestDisambiguateExitConfigError:
    def test_lock_held_is_duplicate_node(self):
        assert disambiguate_exit_config_error(lock_held=True) is ExitConfigErrorCause.DUPLICATE_NODE

    def test_lock_free_is_config_error(self):
        assert disambiguate_exit_config_error(lock_held=False) is ExitConfigErrorCause.CONFIG_ERROR


_BASE_DAY = dt.datetime(2026, 9, 4, tzinfo=dt.UTC)


class TestDecideRelaunch:
    def test_eligible_transient_within_budget_and_window(self):
        decision = decide_relaunch(
            now=_BASE_DAY.replace(hour=16, minute=55),
            attempts_so_far=0,
            last_attempt_at=None,
            readiness_was_observed=False,
            cause=RelaunchCause.TRANSIENT,
        )
        assert decision.should_relaunch is True

    def test_never_relaunches_a_deterministic_failure(self):
        decision = decide_relaunch(
            now=_BASE_DAY.replace(hour=16, minute=55),
            attempts_so_far=0,
            last_attempt_at=None,
            readiness_was_observed=False,
            cause=RelaunchCause.DETERMINISTIC,
        )
        assert decision.should_relaunch is False

    def test_zero_attempts_after_readiness_was_ever_observed(self):
        decision = decide_relaunch(
            now=_BASE_DAY.replace(hour=16, minute=55),
            attempts_so_far=0,
            last_attempt_at=None,
            readiness_was_observed=True,
            cause=RelaunchCause.TRANSIENT,
        )
        assert decision.should_relaunch is False

    def test_attempt_budget_is_at_most_two(self):
        decision = decide_relaunch(
            now=_BASE_DAY.replace(hour=16, minute=55),
            attempts_so_far=MAX_RELAUNCH_ATTEMPTS,
            last_attempt_at=_BASE_DAY.replace(hour=16, minute=45),
            readiness_was_observed=False,
            cause=RelaunchCause.TRANSIENT,
        )
        assert decision.should_relaunch is False

    def test_second_attempt_allowed_when_under_budget(self):
        decision = decide_relaunch(
            now=_BASE_DAY.replace(hour=16, minute=55),
            attempts_so_far=1,
            last_attempt_at=_BASE_DAY.replace(hour=16, minute=51),
            readiness_was_observed=False,
            cause=RelaunchCause.TRANSIENT,
        )
        assert decision.should_relaunch is True

    def test_minimum_three_minute_gap_is_enforced(self):
        decision = decide_relaunch(
            now=_BASE_DAY.replace(hour=16, minute=52),
            attempts_so_far=1,
            last_attempt_at=_BASE_DAY.replace(hour=16, minute=51),
            readiness_was_observed=False,
            cause=RelaunchCause.TRANSIENT,
        )
        assert decision.should_relaunch is False

    def test_exactly_three_minute_gap_is_sufficient(self):
        decision = decide_relaunch(
            now=_BASE_DAY.replace(hour=16, minute=51) + MIN_RELAUNCH_GAP,
            attempts_so_far=1,
            last_attempt_at=_BASE_DAY.replace(hour=16, minute=51),
            readiness_was_observed=False,
            cause=RelaunchCause.TRANSIENT,
        )
        assert decision.should_relaunch is True

    def test_never_relaunches_at_or_after_1700_utc(self):
        at_cutoff = decide_relaunch(
            now=_BASE_DAY.replace(hour=RELAUNCH_CUTOFF_UTC.hour, minute=RELAUNCH_CUTOFF_UTC.minute),
            attempts_so_far=0,
            last_attempt_at=None,
            readiness_was_observed=False,
            cause=RelaunchCause.TRANSIENT,
        )
        assert at_cutoff.should_relaunch is False

        after_cutoff = decide_relaunch(
            now=_BASE_DAY.replace(hour=17, minute=1),
            attempts_so_far=0,
            last_attempt_at=None,
            readiness_was_observed=False,
            cause=RelaunchCause.TRANSIENT,
        )
        assert after_cutoff.should_relaunch is False

    def test_just_before_cutoff_is_still_eligible(self):
        decision = decide_relaunch(
            now=_BASE_DAY.replace(hour=16, minute=59, second=59),
            attempts_so_far=0,
            last_attempt_at=None,
            readiness_was_observed=False,
            cause=RelaunchCause.TRANSIENT,
        )
        assert decision.should_relaunch is True


# ---------------------------------------------------------------------------
# [2026-09-15] Mid-day relaunch budget -- decide_midday_relaunch's sibling
# suite: same shape as TestDecideRelaunch minus every readiness case (no
# readiness gate at all -- a ready node crashing mid-day is exactly the
# scenario this budget exists for, plan §2 item 2 / §3).
# ---------------------------------------------------------------------------

_MIDDAY_WINDOW_END = midday_watch_window_end(_BASE_DAY.date())


class TestDecideMiddayRelaunch:
    def test_midday_eligible_transient_within_budget_and_window(self):
        decision = decide_midday_relaunch(
            now=_BASE_DAY.replace(hour=20, minute=0),
            window_end=_MIDDAY_WINDOW_END,
            attempts_so_far=0,
            last_attempt_at=None,
            cause=RelaunchCause.TRANSIENT,
        )
        assert decision.should_relaunch is True

    def test_midday_never_relaunches_a_deterministic_failure(self):
        decision = decide_midday_relaunch(
            now=_BASE_DAY.replace(hour=20, minute=0),
            window_end=_MIDDAY_WINDOW_END,
            attempts_so_far=0,
            last_attempt_at=None,
            cause=RelaunchCause.DETERMINISTIC,
        )
        assert decision.should_relaunch is False

    def test_midday_never_relaunches_an_unknown_cause(self):
        decision = decide_midday_relaunch(
            now=_BASE_DAY.replace(hour=20, minute=0),
            window_end=_MIDDAY_WINDOW_END,
            attempts_so_far=0,
            last_attempt_at=None,
            cause=RelaunchCause.UNKNOWN,
        )
        assert decision.should_relaunch is False

    def test_midday_attempt_budget_is_at_most_three(self):
        decision = decide_midday_relaunch(
            now=_BASE_DAY.replace(hour=20, minute=0),
            window_end=_MIDDAY_WINDOW_END,
            attempts_so_far=MIDDAY_MAX_RELAUNCH_ATTEMPTS,
            last_attempt_at=_BASE_DAY.replace(hour=19, minute=50),
            cause=RelaunchCause.TRANSIENT,
        )
        assert decision.should_relaunch is False

    def test_midday_minimum_five_minute_gap_is_enforced(self):
        too_soon = decide_midday_relaunch(
            now=_BASE_DAY.replace(hour=20, minute=3),
            window_end=_MIDDAY_WINDOW_END,
            attempts_so_far=1,
            last_attempt_at=_BASE_DAY.replace(hour=20, minute=0),
            cause=RelaunchCause.TRANSIENT,
        )
        assert too_soon.should_relaunch is False

        exactly_the_gap = decide_midday_relaunch(
            now=_BASE_DAY.replace(hour=20, minute=0) + MIDDAY_MIN_RELAUNCH_GAP,
            window_end=_MIDDAY_WINDOW_END,
            attempts_so_far=1,
            last_attempt_at=_BASE_DAY.replace(hour=20, minute=0),
            cause=RelaunchCause.TRANSIENT,
        )
        assert exactly_the_gap.should_relaunch is True

    def test_midday_never_relaunches_at_or_after_window_close(self):
        at_close = decide_midday_relaunch(
            now=_MIDDAY_WINDOW_END,
            window_end=_MIDDAY_WINDOW_END,
            attempts_so_far=0,
            last_attempt_at=None,
            cause=RelaunchCause.TRANSIENT,
        )
        assert at_close.should_relaunch is False

        after_close = decide_midday_relaunch(
            now=_MIDDAY_WINDOW_END + dt.timedelta(minutes=1),
            window_end=_MIDDAY_WINDOW_END,
            attempts_so_far=0,
            last_attempt_at=None,
            cause=RelaunchCause.TRANSIENT,
        )
        assert after_close.should_relaunch is False

    def test_midday_readiness_already_observed_is_not_a_decline_reason(self):
        # decide_midday_relaunch has no readiness parameter at all, unlike
        # decide_relaunch -- assert the signature never grew one, then that
        # an otherwise-eligible decision is never declined by readiness.
        import inspect

        assert "readiness_was_observed" not in inspect.signature(decide_midday_relaunch).parameters
        decision = decide_midday_relaunch(
            now=_BASE_DAY.replace(hour=20, minute=0),
            window_end=_MIDDAY_WINDOW_END,
            attempts_so_far=0,
            last_attempt_at=None,
            cause=RelaunchCause.TRANSIENT,
        )
        assert decision.should_relaunch is True

    def test_a_fatal_marker_seen_two_polls_before_death_still_classifies_transient(self):
        # Replays the exact 09-05/09-06 drain shape (§3, §7): the poll
        # that first sees the fatal marker is not reliably the SAME poll
        # that first sees the process dead -- the death-detection poll's
        # OWN delta may no longer contain the marker text.
        state = initial_scheduler_state(_BASE_DAY.date())
        earlier_delta = (
            "breezy-trade: FATAL market-data fault in Foo: bar. "
            "The trading process shut down.\n"
        )
        state = record_midday_cause_seen(
            state, _BASE_DAY.replace(hour=20, minute=0), classify_exit1_cause(earlier_delta)
        )
        later_delta_without_marker = "some unrelated later tail\n"
        live_cause = classify_exit1_cause(later_delta_without_marker)
        resolved_cause = (
            state.midday_cause_seen if state.midday_cause_seen is not None else live_cause
        )
        assert resolved_cause is RelaunchCause.TRANSIENT


# ---------------------------------------------------------------------------
# [B4/E3] Self-check.
# ---------------------------------------------------------------------------


class TestSelfCheck:
    def test_pass_when_all_signals_true_and_single_holder(self):
        result = self_check(
            child_alive=True,
            flock_holder_count=1,
            flock_held_by_tracked_pid=True,
            permit_issued=True,
            permit_expiry_valid=True,
            strategy_subscribed=True,
        )
        assert result is SelfCheckResult.PASS

    def test_log_unavailable_passes_as_adopted_log_unknown(self):
        """[D2] An adopted node whose log location is unknown cannot have
        its permit/subscribed markers checked -- PASSes on flock+liveness
        evidence alone, as a DISTINCT result, never silently folded into a
        plain PASS it did not actually verify."""
        result = self_check(
            child_alive=True,
            flock_holder_count=1,
            flock_held_by_tracked_pid=True,
            permit_issued=False,
            permit_expiry_valid=False,
            strategy_subscribed=False,
            log_available=False,
        )
        assert result is SelfCheckResult.PASS_ADOPTED_LOG_UNKNOWN

    def test_log_unavailable_still_fails_when_not_holding_the_lock(self):
        result = self_check(
            child_alive=True,
            flock_holder_count=1,
            flock_held_by_tracked_pid=False,
            permit_issued=False,
            permit_expiry_valid=False,
            strategy_subscribed=False,
            log_available=False,
        )
        assert result is SelfCheckResult.FAIL_NODE_NOT_READY

    def test_child_exited_fails_first(self):
        result = self_check(
            child_alive=False,
            flock_holder_count=0,
            flock_held_by_tracked_pid=False,
            permit_issued=False,
            permit_expiry_valid=False,
            strategy_subscribed=False,
        )
        assert result is SelfCheckResult.FAIL_CHILD_EXITED

    def test_multiple_flock_holders_fails(self):
        result = self_check(
            child_alive=True,
            flock_holder_count=2,
            flock_held_by_tracked_pid=True,
            permit_issued=True,
            permit_expiry_valid=True,
            strategy_subscribed=True,
        )
        assert result is SelfCheckResult.FAIL_MULTIPLE_FLOCK_HOLDERS

    def test_not_ready_when_lock_or_subscribed_signal_missing(self):
        assert (
            self_check(
                child_alive=True,
                flock_holder_count=1,
                flock_held_by_tracked_pid=False,
                permit_issued=True,
                permit_expiry_valid=True,
                strategy_subscribed=True,
            )
            is SelfCheckResult.FAIL_NODE_NOT_READY
        )
        assert (
            self_check(
                child_alive=True,
                flock_holder_count=1,
                flock_held_by_tracked_pid=True,
                permit_issued=True,
                permit_expiry_valid=True,
                strategy_subscribed=False,
            )
            is SelfCheckResult.FAIL_NODE_NOT_READY
        )

    def test_shadow_mode_is_its_own_distinct_fail_state(self):
        result = self_check(
            child_alive=True,
            flock_holder_count=1,
            flock_held_by_tracked_pid=True,
            permit_issued=False,
            permit_expiry_valid=False,
            strategy_subscribed=True,
        )
        assert result is SelfCheckResult.FAIL_SHADOW_MODE_NO_PERMIT

    def test_shadow_mode_result_maps_to_a_fixed_alert_detail_never_relaunched(self):
        from breezy.runtime.trade_supervisor_core import SELF_CHECK_ALERT_DETAIL

        result = SelfCheckResult.FAIL_SHADOW_MODE_NO_PERMIT
        detail = SELF_CHECK_ALERT_DETAIL[result]
        assert detail is AlertDetail.SELF_CHECK_FAIL_SHADOW_MODE_NO_PERMIT
        # No relaunch decision is ever consulted from a self-check result --
        # the self-check happens at 17:05, already past RELAUNCH_CUTOFF_UTC,
        # so any relaunch decision fed this "now" is unconditionally False.
        decision = decide_relaunch(
            now=_BASE_DAY.replace(hour=17, minute=5),
            attempts_so_far=0,
            last_attempt_at=None,
            readiness_was_observed=False,
            cause=RelaunchCause.TRANSIENT,
        )
        assert decision.should_relaunch is False

    def test_the_shell_and_core_pass_result_sets_are_pinned_together(self):
        """AUD-14b review follow-up: the shell's ``_SELF_CHECK_PASS_RESULTS``
        (this module) and the core's ``_PASS_RESULT_VALUES``
        (``trade_supervisor_core.py``, feeding ``record_self_check_result``)
        enumerate the same PASS-family results independently, with nothing
        else pinning them together -- a future PASS-family addition to one
        that is forgotten in the other would silently desync the escalation
        counter from the existing WARN/no-alert behaviour. Test-only pin, no
        production code change."""
        assert {member.value for member in _SELF_CHECK_PASS_RESULTS} == set(_PASS_RESULT_VALUES)


# ===========================================================================
# AUD-14b: self-check repeat-failure escalation (I/O shell). Plan §7 14b
# steps 2b (rollover, driven for real), 3 (shell alert severity), 4
# (persistence and the fault paths), 5 (the seven-day historical replay),
# 6 (restart-interleaved replay). The pure-core tests (steps 2, 2a) live in
# ``tests/unit/test_trade_supervisor_core.py``.
# ===========================================================================

_AUD14B_READY_LOG_LINE = (
    "live-trading permit issued issued_at_ns=1 expires_at_ns=4102444800000000000 ttl_s=1\n"
    "CurrentRungHoldStrategy subscribed X\n"
)


def _aud14b_ports(sink, *, ready: bool) -> SupervisorPorts:
    """A minimal ``SupervisorPorts`` for a tracked, alive, single-flock-holder
    node -- the only variable is whether the (fake) log carries the
    permit-issued/strategy-subscribed markers (PASS) or not (FAIL_NODE_NOT_READY)."""
    return SupervisorPorts(
        find_node_pid=lambda: None,
        resolve_intent_lock_holder=lambda _p: 42,
        intent_lock_free=lambda _p: True,
        count_intent_lock_holders=lambda _p: 1,
        terminate_after_recheck=lambda pid, **kw: None,
        process_alive=lambda _pid: True,
        probe_open_intent_state=lambda *a, **kw: False,
        spawn=lambda **kw: None,
        read_log_new=lambda _p: _AUD14B_READY_LOG_LINE if ready else "",
        alert_sink=sink,
    )


def _aud14b_store_get(store_path):
    with SqliteStateStore(store_path) as store:
        return store.get(SELF_CHECK_ESCALATION_STORE_KEY)


def _aud14b_plant(store_path, state: SelfCheckEscalationState) -> None:
    with SqliteStateStore(store_path) as store:
        store.set(SELF_CHECK_ESCALATION_STORE_KEY, encode_self_check_escalation_state(state))


def _make_write_failing_store_cls(calls: list | None = None):
    """A fake ``SqliteStateStore`` whose ``get`` delegates to a real store
    (so the load step behaves normally) but whose ``set`` always raises --
    isolates the write-failure fault path without touching the read path."""

    class _WriteFailingStore:
        def __init__(self, path, *a, **kw):
            self._real = SqliteStateStore(path)

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            self._real.close()
            return False

        def get(self, key):
            if calls is not None:
                calls.append(("get", key))
            return self._real.get(key)

        def set(self, key, value):
            if calls is not None:
                calls.append(("set", key))
            raise RuntimeError("simulated write failure")

    return _WriteFailingStore


class _AlwaysUnavailableStore:
    """A fake ``SqliteStateStore`` that raises on construction -- simulates
    the store being wholly unreachable for both the load and the (attempted)
    write step."""

    def __init__(self, *a, **kw):
        raise RuntimeError("simulated store unavailable")


def _make_order_tracking_store_cls(calls: list):
    """A fake ``SqliteStateStore`` that appends to ``calls`` on every
    ``set`` (never on ``get``, which is not under test here), while
    delegating all real I/O to a genuine store -- used to pin the
    DECIDE -> EMIT -> PERSIST ordering."""

    class _OrderTrackingStore:
        def __init__(self, path, *a, **kw):
            self._real = SqliteStateStore(path)

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            self._real.close()
            return False

        def get(self, key):
            return self._real.get(key)

        def set(self, key, value):
            self._real.set(key, value)
            calls.append(("store_set", key))

    return _OrderTrackingStore


class _OrderTrackingAlertSink:
    def __init__(self, calls: list):
        self.calls = calls
        self.payloads: list[AlertPayload] = []

    def emit(self, payload: AlertPayload) -> None:
        self.calls.append(("alert", payload.event))
        self.payloads.append(payload)


class TestSelfCheckEscalationRollover:
    """§7 14b step 2b -- driven against a REAL ``SqliteStateStore`` and a
    REAL ``mark_phase_fired`` call between polls, exactly as the poll loop
    does at ``trade_supervisor.py:1496``."""

    _DAY1 = dt.date(2026, 9, 12)
    _DAY2 = dt.date(2026, 9, 13)

    def _poll(self, *, ports, now, store_path, tmp_path, state):
        _tracked_pid, _node_log, state = _do_self_check(
            ports=ports,
            now=now,
            store_path=store_path,
            log_dir=tmp_path / "logs",
            tracked_pid=42,
            node_log=tmp_path / "n.log",
            state=state,
        )
        return mark_phase_fired(state, Phase.SELF_CHECK, now)

    def test_the_counter_survives_a_real_trading_day_rollover_at_1640z(self, tmp_path):
        store_path = tmp_path / "state" / "store.sqlite3"
        sink = _RecordingAlertSink()
        ports = _aud14b_ports(sink, ready=False)
        state = initial_scheduler_state(self._DAY1)

        state = self._poll(
            ports=ports,
            now=dt.datetime(2026, 9, 12, 17, 5, tzinfo=dt.UTC),
            store_path=store_path,
            tmp_path=tmp_path,
            state=state,
        )
        state = self._poll(
            ports=ports,
            now=dt.datetime(2026, 9, 13, 17, 5, tzinfo=dt.UTC),
            store_path=store_path,
            tmp_path=tmp_path,
            state=state,
        )

        critical = [
            p for p in sink.payloads if p.event == "TRADE_SUPERVISOR_SELF_CHECK_FAIL_REPEATED"
        ]
        assert len(critical) == 1
        assert critical[0].severity == "CRITICAL"

    def test_a_pass_after_a_rollover_resets_the_counter_to_zero(self, tmp_path):
        store_path = tmp_path / "state" / "store.sqlite3"
        sink = _RecordingAlertSink()
        fail_ports = _aud14b_ports(sink, ready=False)
        pass_ports = _aud14b_ports(sink, ready=True)
        state = initial_scheduler_state(self._DAY1)

        state = self._poll(
            ports=fail_ports,
            now=dt.datetime(2026, 9, 12, 17, 5, tzinfo=dt.UTC),
            store_path=store_path,
            tmp_path=tmp_path,
            state=state,
        )
        state = self._poll(
            ports=pass_ports,
            now=dt.datetime(2026, 9, 13, 17, 5, tzinfo=dt.UTC),
            store_path=store_path,
            tmp_path=tmp_path,
            state=state,
        )

        critical = [
            p for p in sink.payloads if p.event == "TRADE_SUPERVISOR_SELF_CHECK_FAIL_REPEATED"
        ]
        assert critical == []
        decoded = decode_self_check_escalation_state(_aud14b_store_get(store_path))
        assert decoded.consecutive_failures == 0

    def test_the_rollover_still_resets_every_existing_day_scheduler_state_field(self, tmp_path):
        store_path = tmp_path / "state" / "store.sqlite3"
        sink = _RecordingAlertSink()
        ports = _aud14b_ports(sink, ready=False)
        state = initial_scheduler_state(self._DAY1)
        state = replace(
            state,
            readiness_observed=True,
            launch_done=True,
            strategy_subscribed_seen=True,
            relaunch_attempts=2,
        )

        state = self._poll(
            ports=ports,
            now=dt.datetime(2026, 9, 12, 17, 5, tzinfo=dt.UTC),
            store_path=store_path,
            tmp_path=tmp_path,
            state=state,
        )
        state = self._poll(
            ports=ports,
            now=dt.datetime(2026, 9, 13, 17, 5, tzinfo=dt.UTC),
            store_path=store_path,
            tmp_path=tmp_path,
            state=state,
        )

        assert state.day == self._DAY2
        assert state.readiness_observed is False
        assert state.launch_done is False
        assert state.strategy_subscribed_seen is False
        assert state.relaunch_attempts == 0


class TestSelfCheckEscalationShellAlerts:
    """§7 14b step 3."""

    def test_the_first_self_check_failure_alerts_at_warn(self, tmp_path):
        store_path = tmp_path / "state" / "store.sqlite3"
        sink = _RecordingAlertSink()
        ports = _aud14b_ports(sink, ready=False)
        _do_self_check(
            ports=ports,
            now=dt.datetime(2026, 9, 12, 17, 5, tzinfo=dt.UTC),
            store_path=store_path,
            log_dir=tmp_path / "logs",
            tracked_pid=42,
            node_log=tmp_path / "n.log",
        )
        fail_alerts = [p for p in sink.payloads if p.event == "TRADE_SUPERVISOR_SELF_CHECK_FAIL"]
        assert len(fail_alerts) == 1
        assert fail_alerts[0].severity == "WARN"
        repeated = [
            p for p in sink.payloads if p.event == "TRADE_SUPERVISOR_SELF_CHECK_FAIL_REPEATED"
        ]
        assert repeated == []

    def test_the_second_consecutive_failure_alerts_at_critical(self, tmp_path):
        store_path = tmp_path / "state" / "store.sqlite3"
        sink = _RecordingAlertSink()
        ports = _aud14b_ports(sink, ready=False)
        for now in (
            dt.datetime(2026, 9, 12, 17, 5, tzinfo=dt.UTC),
            dt.datetime(2026, 9, 13, 17, 5, tzinfo=dt.UTC),
        ):
            _do_self_check(
                ports=ports,
                now=now,
                store_path=store_path,
                log_dir=tmp_path / "logs",
                tracked_pid=42,
                node_log=tmp_path / "n.log",
            )
        repeated = [
            p for p in sink.payloads if p.event == "TRADE_SUPERVISOR_SELF_CHECK_FAIL_REPEATED"
        ]
        assert len(repeated) == 1
        assert repeated[0].severity == "CRITICAL"

    def test_the_repeated_failure_alert_detail_is_a_fixed_enum_and_carries_no_value(
        self, tmp_path
    ):
        store_path = tmp_path / "state" / "store.sqlite3"
        sink = _RecordingAlertSink()
        ports = _aud14b_ports(sink, ready=False)
        for now in (
            dt.datetime(2026, 9, 12, 17, 5, tzinfo=dt.UTC),
            dt.datetime(2026, 9, 13, 17, 5, tzinfo=dt.UTC),
        ):
            _do_self_check(
                ports=ports,
                now=now,
                store_path=store_path,
                log_dir=tmp_path / "logs",
                tracked_pid=42,
                node_log=tmp_path / "n.log",
            )
        repeated = [
            p for p in sink.payloads if p.event == "TRADE_SUPERVISOR_SELF_CHECK_FAIL_REPEATED"
        ]
        fixed_values = {member.value for member in AlertDetail}
        assert repeated[0].detail in fixed_values
        assert "Traceback" not in repeated[0].detail
        assert repeated[0].detail == AlertDetail.SELF_CHECK_FAIL_NOT_READY.value


class TestSelfCheckEscalationFaultPaths:
    """§7 14b step 4 -- every test asserts a failure of the escalation
    machinery itself fails TOWARD alerting."""

    def test_an_absent_key_starts_the_counter_at_zero_and_emits_no_alert(self, tmp_path):
        store_path = tmp_path / "state" / "store.sqlite3"
        sink = _RecordingAlertSink()
        ports = _aud14b_ports(sink, ready=True)
        _do_self_check(
            ports=ports,
            now=dt.datetime(2026, 9, 12, 17, 5, tzinfo=dt.UTC),
            store_path=store_path,
            log_dir=tmp_path / "logs",
            tracked_pid=42,
            node_log=tmp_path / "n.log",
        )
        load_alerts = [
            p
            for p in sink.payloads
            if "ESCALATION" in p.event
        ]
        assert load_alerts == []

    def test_a_corrupt_stored_value_alerts_where_an_absent_key_is_silent(
        self, tmp_path, monkeypatch
    ):
        store_path = tmp_path / "state" / "store.sqlite3"

        # Absent call: no key at all -- silent.
        absent_sink = _RecordingAlertSink()
        ports = _aud14b_ports(absent_sink, ready=True)
        _do_self_check(
            ports=ports,
            now=dt.datetime(2026, 9, 12, 17, 5, tzinfo=dt.UTC),
            store_path=tmp_path / "absent" / "store.sqlite3",
            log_dir=tmp_path / "logs",
            tracked_pid=42,
            node_log=tmp_path / "n.log",
        )
        assert [p for p in absent_sink.payloads if "ESCALATION" in p.event] == []

        # Corrupt call: garbage bytes at the literal key, fed a PASS --
        # write-back case 3 (§6): the one rebase to zero an OBSERVED PASS
        # licenses.
        with SqliteStateStore(store_path) as store:
            store.set(SELF_CHECK_ESCALATION_STORE_KEY, b"not valid json at all")
        corrupt_sink = _RecordingAlertSink()
        pass_ports = _aud14b_ports(corrupt_sink, ready=True)
        _do_self_check(
            ports=pass_ports,
            now=dt.datetime(2026, 9, 12, 17, 5, tzinfo=dt.UTC),
            store_path=store_path,
            log_dir=tmp_path / "logs",
            tracked_pid=42,
            node_log=tmp_path / "n.log",
        )
        corrupt_alerts = [
            p
            for p in corrupt_sink.payloads
            if p.event == "TRADE_SUPERVISOR_SELF_CHECK_ESCALATION_STATE_CORRUPT"
        ]
        assert len(corrupt_alerts) == 1
        assert corrupt_alerts[0].severity == "WARN"
        assert corrupt_alerts[0].detail == AlertDetail.SELF_CHECK_ESCALATION_STATE_CORRUPT.value

        decoded = decode_self_check_escalation_state(_aud14b_store_get(store_path))
        assert decoded == SelfCheckEscalationState(
            consecutive_failures=0, last_self_check_utc=decoded.last_self_check_utc
        )
        assert decoded.last_self_check_utc  # advanced -- proves the write happened.

    def test_a_corrupt_stored_value_escalates_a_failure_to_critical_instead_of_resetting_to_zero(
        self, tmp_path
    ):
        store_path = tmp_path / "state" / "store.sqlite3"
        with SqliteStateStore(store_path) as store:
            store.set(
                SELF_CHECK_ESCALATION_STORE_KEY,
                b'{"consecutive_failures": 5, "extra_key": "corrupts the decode"}',
            )
        sink = _RecordingAlertSink()
        ports = _aud14b_ports(sink, ready=False)
        _do_self_check(
            ports=ports,
            now=dt.datetime(2026, 9, 12, 17, 5, tzinfo=dt.UTC),
            store_path=store_path,
            log_dir=tmp_path / "logs",
            tracked_pid=42,
            node_log=tmp_path / "n.log",
        )
        repeated = [
            p for p in sink.payloads if p.event == "TRADE_SUPERVISOR_SELF_CHECK_FAIL_REPEATED"
        ]
        assert len(repeated) == 1
        assert repeated[0].severity == "CRITICAL"
        assert repeated[0].detail == AlertDetail.SELF_CHECK_ESCALATION_STATE_CORRUPT.value
        warn_only = [p for p in sink.payloads if p.event == "TRADE_SUPERVISOR_SELF_CHECK_FAIL"]
        assert warn_only == []

        # Write-back case 1 (FAIL under a corrupt read, then FAIL): the
        # reducer's OUTPUT is persisted -- 1, never 0, never the planted 5.
        decoded = decode_self_check_escalation_state(_aud14b_store_get(store_path))
        assert decoded.consecutive_failures == 1

        # A second poll against the now-repaired value escalates BY COUNT.
        _do_self_check(
            ports=ports,
            now=dt.datetime(2026, 9, 13, 17, 5, tzinfo=dt.UTC),
            store_path=store_path,
            log_dir=tmp_path / "logs",
            tracked_pid=42,
            node_log=tmp_path / "n.log",
        )
        repeated = [
            p for p in sink.payloads if p.event == "TRADE_SUPERVISOR_SELF_CHECK_FAIL_REPEATED"
        ]
        assert len(repeated) == 2
        assert repeated[1].detail == AlertDetail.SELF_CHECK_FAIL_NOT_READY.value  # by count now.

    def test_a_store_read_failure_alerts_and_escalates_a_failure_to_critical(
        self, tmp_path, monkeypatch
    ):
        store_path = tmp_path / "state" / "store.sqlite3"
        monkeypatch.setattr(
            "breezy.runtime.trade_supervisor.SqliteStateStore", _AlwaysUnavailableStore
        )
        sink = _RecordingAlertSink()
        ports = _aud14b_ports(sink, ready=False)
        _do_self_check(
            ports=ports,
            now=dt.datetime(2026, 9, 12, 17, 5, tzinfo=dt.UTC),
            store_path=store_path,
            log_dir=tmp_path / "logs",
            tracked_pid=42,
            node_log=tmp_path / "n.log",
        )
        unavailable = [
            p
            for p in sink.payloads
            if p.event == "TRADE_SUPERVISOR_SELF_CHECK_ESCALATION_STORE_UNAVAILABLE"
        ]
        assert len(unavailable) == 1
        assert unavailable[0].severity == "WARN"
        write_failed = [
            p
            for p in sink.payloads
            if p.event == "TRADE_SUPERVISOR_SELF_CHECK_ESCALATION_STATE_WRITE_FAILED"
        ]
        assert len(write_failed) == 1  # the write was ATTEMPTED, and it also failed.
        repeated = [
            p for p in sink.payloads if p.event == "TRADE_SUPERVISOR_SELF_CHECK_FAIL_REPEATED"
        ]
        assert len(repeated) == 1
        assert repeated[0].severity == "CRITICAL"

    def test_a_sustained_read_failure_still_escalates_on_the_second_of_two_consecutive_polls(
        self, tmp_path, monkeypatch
    ):
        store_path = tmp_path / "state" / "store.sqlite3"
        monkeypatch.setattr(
            "breezy.runtime.trade_supervisor.SqliteStateStore", _AlwaysUnavailableStore
        )
        sink = _RecordingAlertSink()
        ports = _aud14b_ports(sink, ready=False)
        for now in (
            dt.datetime(2026, 9, 12, 17, 5, tzinfo=dt.UTC),
            dt.datetime(2026, 9, 13, 17, 5, tzinfo=dt.UTC),
        ):
            _do_self_check(
                ports=ports,
                now=now,
                store_path=store_path,
                log_dir=tmp_path / "logs",
                tracked_pid=42,
                node_log=tmp_path / "n.log",
            )
        repeated = [
            p for p in sink.payloads if p.event == "TRADE_SUPERVISOR_SELF_CHECK_FAIL_REPEATED"
        ]
        assert len(repeated) == 2
        assert all(p.severity == "CRITICAL" for p in repeated)

    def test_a_write_failure_after_a_critical_decision_still_delivers_the_alert_and_is_reported_distinctly(
        self, tmp_path, monkeypatch
    ):
        store_path = tmp_path / "state" / "store.sqlite3"
        _aud14b_plant(
            store_path,
            SelfCheckEscalationState(
                consecutive_failures=1, last_self_check_utc="2026-09-11T17:05:00Z"
            ),
        )
        monkeypatch.setattr(
            "breezy.runtime.trade_supervisor.SqliteStateStore",
            _make_write_failing_store_cls(),
        )
        sink = _RecordingAlertSink()
        ports = _aud14b_ports(sink, ready=False)
        _do_self_check(
            ports=ports,
            now=dt.datetime(2026, 9, 12, 17, 5, tzinfo=dt.UTC),
            store_path=store_path,
            log_dir=tmp_path / "logs",
            tracked_pid=42,
            node_log=tmp_path / "n.log",
        )
        repeated = [
            p for p in sink.payloads if p.event == "TRADE_SUPERVISOR_SELF_CHECK_FAIL_REPEATED"
        ]
        assert len(repeated) == 1
        assert repeated[0].severity == "CRITICAL"
        write_failed = [
            p
            for p in sink.payloads
            if p.event == "TRADE_SUPERVISOR_SELF_CHECK_ESCALATION_STATE_WRITE_FAILED"
        ]
        assert len(write_failed) == 1
        assert write_failed[0].event != "TRADE_SUPERVISOR_SELF_CHECK_ESCALATION_STORE_UNAVAILABLE"

    def test_a_write_failure_then_a_restart_duplicates_but_never_loses_the_escalation(
        self, tmp_path, monkeypatch
    ):
        store_path = tmp_path / "state" / "store.sqlite3"
        sink = _RecordingAlertSink()
        ports = _aud14b_ports(sink, ready=False)

        # Day 1: normal store, persists consecutive_failures=1.
        _do_self_check(
            ports=ports,
            now=dt.datetime(2026, 9, 12, 17, 5, tzinfo=dt.UTC),
            store_path=store_path,
            log_dir=tmp_path / "logs",
            tracked_pid=42,
            node_log=tmp_path / "n.log",
        )

        # Day 2: write fails -- CRITICAL decided (count=2) but not persisted.
        monkeypatch.setattr(
            "breezy.runtime.trade_supervisor.SqliteStateStore",
            _make_write_failing_store_cls(),
        )
        _do_self_check(
            ports=ports,
            now=dt.datetime(2026, 9, 13, 17, 5, tzinfo=dt.UTC),
            store_path=store_path,
            log_dir=tmp_path / "logs",
            tracked_pid=42,
            node_log=tmp_path / "n.log",
        )

        # "Restart": a fresh, ordinary store connection against the same
        # tmp_path store -- the stuck-at-1 value is read back for real.
        monkeypatch.undo()
        _do_self_check(
            ports=ports,
            now=dt.datetime(2026, 9, 14, 17, 5, tzinfo=dt.UTC),
            store_path=store_path,
            log_dir=tmp_path / "logs",
            tracked_pid=42,
            node_log=tmp_path / "n.log",
        )

        repeated = [
            p for p in sink.payloads if p.event == "TRADE_SUPERVISOR_SELF_CHECK_FAIL_REPEATED"
        ]
        # Duplicated (day 2 AND day 3 both CRITICAL from the stuck count),
        # never lost.
        assert len(repeated) == 2

    def test_the_alert_is_emitted_before_the_store_write(self, tmp_path, monkeypatch):
        store_path = tmp_path / "state" / "store.sqlite3"
        _aud14b_plant(
            store_path,
            SelfCheckEscalationState(
                consecutive_failures=1, last_self_check_utc="2026-09-11T17:05:00Z"
            ),
        )
        calls: list[tuple[str, str]] = []
        monkeypatch.setattr(
            "breezy.runtime.trade_supervisor.SqliteStateStore",
            _make_order_tracking_store_cls(calls),
        )
        sink = _OrderTrackingAlertSink(calls)
        ports = _aud14b_ports(sink, ready=False)
        _do_self_check(
            ports=ports,
            now=dt.datetime(2026, 9, 12, 17, 5, tzinfo=dt.UTC),
            store_path=store_path,
            log_dir=tmp_path / "logs",
            tracked_pid=42,
            node_log=tmp_path / "n.log",
        )
        alert_index = next(i for i, c in enumerate(calls) if c[0] == "alert")
        store_set_index = next(i for i, c in enumerate(calls) if c[0] == "store_set")
        assert alert_index < store_set_index


class TestSelfCheckEscalationHistoricalReplay:
    """§7 14b steps 5 and 6 -- the historical 09-12..09-18 incident, replayed
    against the new code, and the same sequence with a simulated restart
    landing between days 3 and 4."""

    _SEQUENCE = [
        (dt.date(2026, 9, 12), SelfCheckResult.FAIL_NODE_NOT_READY),
        (dt.date(2026, 9, 13), SelfCheckResult.FAIL_NODE_NOT_READY),
        (dt.date(2026, 9, 14), SelfCheckResult.FAIL_NODE_NOT_READY),
        (dt.date(2026, 9, 15), SelfCheckResult.FAIL_NODE_NOT_READY),
        (dt.date(2026, 9, 16), SelfCheckResult.FAIL_NODE_NOT_READY),
        (dt.date(2026, 9, 17), SelfCheckResult.FAIL_NODE_NOT_READY),
        (dt.date(2026, 9, 18), SelfCheckResult.FAIL_CHILD_EXITED),
    ]

    def _run_day(self, *, day, result, store_path, tmp_path, sink):
        ready = result in (SelfCheckResult.PASS, SelfCheckResult.PASS_ADOPTED_LOG_UNKNOWN)
        child_alive = result is not SelfCheckResult.FAIL_CHILD_EXITED
        ports = SupervisorPorts(
            find_node_pid=lambda: None,
            resolve_intent_lock_holder=lambda _p: 42,
            intent_lock_free=lambda _p: True,
            count_intent_lock_holders=lambda _p: 1,
            terminate_after_recheck=lambda pid, **kw: None,
            process_alive=lambda _pid, _alive=child_alive: _alive,
            probe_open_intent_state=lambda *a, **kw: False,
            spawn=lambda **kw: None,
            read_log_new=lambda _p: _AUD14B_READY_LOG_LINE if ready else "",
            alert_sink=sink,
        )
        _do_self_check(
            ports=ports,
            now=dt.datetime(day.year, day.month, day.day, 17, 5, tzinfo=dt.UTC),
            store_path=store_path,
            log_dir=tmp_path / "logs",
            tracked_pid=42,
            node_log=tmp_path / "n.log",
        )

    def test_the_2026_09_12_to_09_18_sequence_escalates(self, tmp_path):
        store_path = tmp_path / "state" / "store.sqlite3"
        sink = _RecordingAlertSink()
        critical_days: list[dt.date] = []
        for day, result in self._SEQUENCE:
            before = len(
                [
                    p
                    for p in sink.payloads
                    if p.event == "TRADE_SUPERVISOR_SELF_CHECK_FAIL_REPEATED"
                ]
            )
            self._run_day(day=day, result=result, store_path=store_path, tmp_path=tmp_path, sink=sink)
            after = len(
                [
                    p
                    for p in sink.payloads
                    if p.event == "TRADE_SUPERVISOR_SELF_CHECK_FAIL_REPEATED"
                ]
            )
            if after > before:
                critical_days.append(day)

        assert critical_days
        assert critical_days[0] == dt.date(2026, 9, 13)  # day 2, not day 7.

    def test_the_sequence_still_escalates_when_a_restart_falls_on_day_3(
        self, tmp_path, monkeypatch
    ):
        store_path = tmp_path / "state" / "store.sqlite3"
        sink = _RecordingAlertSink()
        critical_days: list[dt.date] = []
        for index, (day, result) in enumerate(self._SEQUENCE):
            if index == 3:
                # Simulate a restart landing between days 3 and 4: nothing
                # in-process carries state across this point except the
                # store itself, which every call re-reads fresh anyway.
                pass
            before = len(
                [
                    p
                    for p in sink.payloads
                    if p.event == "TRADE_SUPERVISOR_SELF_CHECK_FAIL_REPEATED"
                ]
            )
            self._run_day(day=day, result=result, store_path=store_path, tmp_path=tmp_path, sink=sink)
            after = len(
                [
                    p
                    for p in sink.payloads
                    if p.event == "TRADE_SUPERVISOR_SELF_CHECK_FAIL_REPEATED"
                ]
            )
            if after > before:
                critical_days.append(day)

        assert critical_days
        assert critical_days[0] == dt.date(2026, 9, 13)


# ---------------------------------------------------------------------------
# [R9] RLIMIT_CORE hardening -- both the supervisor and the spawned child.
# ---------------------------------------------------------------------------


def test_apply_core_limit_sets_zero_in_a_subprocess(tmp_path):
    # Isolated in a subprocess so this test never mutates the test runner's
    # own (irreversible-within-process) RLIMIT_CORE.
    script = (
        "import resource\n"
        "from breezy.runtime.trade_supervisor import apply_core_limit\n"
        "apply_core_limit()\n"
        "print(resource.getrlimit(resource.RLIMIT_CORE))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "(0, 0)"


def test_spawned_child_has_rlimit_core_zero_via_preexec(tmp_path):
    node_bin = tmp_path / "fake_node.py"
    node_bin.write_text(
        "#!/usr/bin/env python3\nimport resource\nprint(resource.getrlimit(resource.RLIMIT_CORE))\n"
    )
    node_bin.chmod(0o755)
    log_path = tmp_path / "logs" / "child.log"

    proc = spawn_node(node_bin=node_bin, repo_root=tmp_path, env={}, log_path=log_path)
    proc.wait(timeout=10)
    output = log_path.read_text()
    assert "(0, 0)" in output


# ---------------------------------------------------------------------------
# [R7a] Supervisor mutual exclusion -- second instance exits 2.
# ---------------------------------------------------------------------------


def test_second_supervisor_lock_holder_raises_lock_held(tmp_path):
    from breezy.runtime.trade_supervisor import SupervisorLockHeld

    lock_path = tmp_path / "trade-supervisor.lock"
    with (
        hold_supervisor_lock(lock_path),
        pytest.raises(SupervisorLockHeld),
        hold_supervisor_lock(lock_path),
    ):
        pass  # pragma: no cover - must never be entered


def test_main_requires_the_distinct_argv_token(tmp_path, monkeypatch):
    monkeypatch.setenv(EXEC_STATE_DB_ENV_VAR, str(tmp_path / "state" / "store.sqlite3"))
    assert main([]) == EXIT_CONFIG_ERROR
    assert main(["some-other-token"]) == EXIT_CONFIG_ERROR


def test_main_exits_2_when_a_second_supervisor_is_already_running(tmp_path, monkeypatch, caplog):
    store_path = tmp_path / "state" / "store.sqlite3"
    store_path.parent.mkdir(parents=True)
    monkeypatch.setenv(EXEC_STATE_DB_ENV_VAR, str(store_path))
    monkeypatch.setenv("BREEZY_TOTALLY_SECRET_SENTINEL", "sentinel-value-should-never-leak")

    lock_path = supervisor_lock_path(store_path)
    fake_sink = _RecordingAlertSink()
    monkeypatch.setattr(
        "breezy.runtime.trade_supervisor.resolve_alert_sink", lambda *a, **k: fake_sink
    )

    with caplog.at_level("INFO"), hold_supervisor_lock(lock_path):
        exit_code = main([SUPERVISOR_ARGV_TOKEN])

    assert exit_code == EXIT_CONFIG_ERROR
    assert len(fake_sink.payloads) == 1
    payload = fake_sink.payloads[0]
    assert payload.detail == AlertDetail.SECOND_SUPERVISOR_REFUSED.value
    assert "sentinel-value-should-never-leak" not in payload.detail
    assert "sentinel-value-should-never-leak" not in payload.event
    assert "sentinel-value-should-never-leak" not in caplog.text


class _RecordingAlertSink:
    def __init__(self) -> None:
        self.payloads: list[AlertPayload] = []

    def emit(self, payload: AlertPayload) -> None:
        self.payloads.append(payload)


# ---------------------------------------------------------------------------
# Value-free logging and alerting -- no environ value, no exception text.
# ---------------------------------------------------------------------------


def test_log_decision_never_emits_environ_content(monkeypatch, caplog):
    monkeypatch.setenv("BREEZY_ANOTHER_SENTINEL", "another-leaking-value")
    with caplog.at_level("INFO"):
        log_decision("stop_prior_refused", pid=1234, action="refuse_alert")
    assert "another-leaking-value" not in caplog.text


def test_alert_detail_is_always_the_fixed_enum_value():
    for member in AlertDetail:
        # Every AlertDetail member is a short, static, snake_case reason --
        # never free text, never interpolated from an exception or env.
        assert member.value == member.value.lower()
        assert " " not in member.value or member.value.replace(" ", "_") == member.value
        assert len(member.value) < 80


# ---------------------------------------------------------------------------
# Intent-lock probing -- real flocks, no fakes needed for the primitive.
# ---------------------------------------------------------------------------


def test_intent_lock_path_matches_submit_intent_convention(tmp_path):
    store_path = tmp_path / "store.sqlite3"
    assert intent_lock_path(store_path) == tmp_path / "store.sqlite3.intent.lock"


def test_intent_lock_is_free_true_when_no_lock_file(tmp_path):
    assert intent_lock_is_free(tmp_path / "missing.intent.lock") is True


def test_intent_lock_is_free_false_when_flock_held(tmp_path):
    lock_path = tmp_path / "held.intent.lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        assert intent_lock_is_free(lock_path) is False
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def test_intent_lock_is_free_true_after_release(tmp_path):
    lock_path = tmp_path / "released.intent.lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    fcntl.flock(fd, fcntl.LOCK_EX)
    fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)
    assert intent_lock_is_free(lock_path) is True


def test_resolve_lock_holder_pid_matches_the_real_flock_holder(tmp_path):
    lock_path = tmp_path / "x.lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        assert resolve_lock_holder_pid(lock_path) == os.getpid()
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def test_resolve_lock_holder_pid_none_when_unlocked(tmp_path):
    lock_path = tmp_path / "unlocked.lock"
    lock_path.touch()
    assert resolve_lock_holder_pid(lock_path) is None


def test_count_lock_holders_zero_for_missing_file(tmp_path):
    assert count_lock_holders(tmp_path / "missing.lock") == 0


def test_count_lock_holders_one_when_held(tmp_path):
    lock_path = tmp_path / "held-count.lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        assert count_lock_holders(lock_path) == 1
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


# ---------------------------------------------------------------------------
# Terminate uses SIGTERM only.
# ---------------------------------------------------------------------------


def test_terminate_sends_sigterm_to_a_real_child(tmp_path):
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        terminate(proc.pid)
        proc.wait(timeout=10)
        assert proc.returncode == -15  # SIGTERM
    finally:
        if proc.poll() is None:  # pragma: no cover - safety net only
            proc.kill()


# ---------------------------------------------------------------------------
# Node log path / naming.
# ---------------------------------------------------------------------------


def test_node_log_path_is_timestamped_under_the_log_dir(tmp_path):
    now = dt.datetime(2026, 9, 4, 16, 50, 0, tzinfo=dt.UTC)
    path = node_log_path(tmp_path, now)
    assert path.parent == tmp_path
    assert path.name == "breezy-trade-20260904T165000Z.log"


def test_node_console_script_name_matches_pyproject_entry():
    pyproject = (REPO_ROOT / "pyproject.toml").read_text()
    assert f'{NODE_CONSOLE_SCRIPT} = "breezy.app.trade:main"' in pyproject


def test_supervisor_console_entry_uses_the_distinct_argv_token_convention():
    pyproject = (REPO_ROOT / "pyproject.toml").read_text()
    assert 'breezy-trade-supervisor = "breezy.runtime.trade_supervisor:main"' in pyproject
    plan_path = REPO_ROOT / "docs/plans/TRADE_NODE_DAILY_RELAUNCH_2026-09-04.md"
    assert SUPERVISOR_ARGV_TOKEN in plan_path.read_text()


# ===========================================================================
# Coordinator round 2: the loop was a stub (`while True: sleep(30)`) with
# zero call sites for any decision function -- security BLOCK. This section
# covers the real, testable scheduler + wired loop.
# ===========================================================================

_DAY = dt.date(2026, 9, 4)


def _utc(hour: int, minute: int, second: int = 0, *, day: dt.date = _DAY) -> dt.datetime:
    return dt.datetime.combine(day, dt.time(hour, minute, second), tzinfo=dt.UTC)


# ---------------------------------------------------------------------------
# Pure scheduler: next_due / mark_phase_fired / record_* over plain values.
# ---------------------------------------------------------------------------


class TestNextDue:
    def test_before_1640_nothing_is_due(self):
        state = initial_scheduler_state(_DAY)
        phase, fire_at = next_due(_utc(3, 0), state)
        assert phase is Phase.NONE
        assert fire_at == _utc(16, 40)

    def test_stop_prior_due_in_its_window(self):
        state = initial_scheduler_state(_DAY)
        phase, fire_at = next_due(_utc(16, 45), state)
        assert phase is Phase.STOP_PRIOR
        assert fire_at == _utc(16, 40)

    def test_stop_prior_never_double_fires_same_day(self):
        state = mark_phase_fired(initial_scheduler_state(_DAY), Phase.STOP_PRIOR, _utc(16, 41))
        phase, _ = next_due(_utc(16, 45), state)
        assert phase is not Phase.STOP_PRIOR

    def test_restart_at_1645_launch_still_due_at_1650(self):
        # A restart at 16:45 does not skip today's LAUNCH -- it simply
        # isn't due yet (LAUNCH_UTC hasn't arrived).
        state = initial_scheduler_state(_DAY)
        phase, _ = next_due(_utc(16, 45), state)
        assert phase is Phase.STOP_PRIOR
        state = mark_phase_fired(state, Phase.STOP_PRIOR, _utc(16, 45))
        phase, fire_at = next_due(_utc(16, 50), state)
        assert phase is Phase.LAUNCH
        assert fire_at == _utc(16, 50)

    def test_restart_at_1655_launch_due_immediately_if_not_fired(self):
        # STOP_PRIOR's own window [16:40,16:50) has already closed by
        # 16:55, so a fresh (post-restart) state goes straight to LAUNCH.
        state = initial_scheduler_state(_DAY)
        phase, fire_at = next_due(_utc(16, 55), state)
        assert phase is Phase.LAUNCH
        assert fire_at == _utc(16, 50)

    def test_restart_at_1655_launch_already_done_yields_relaunch_check(self):
        state = mark_phase_fired(initial_scheduler_state(_DAY), Phase.LAUNCH, _utc(16, 50))
        phase, _ = next_due(_utc(16, 55), state)
        assert phase is Phase.RELAUNCH_CHECK

    def test_restart_at_1655_launch_done_and_ready_yields_nothing_until_self_check(self):
        state = mark_phase_fired(initial_scheduler_state(_DAY), Phase.LAUNCH, _utc(16, 50))
        state = record_readiness_observed(state, _utc(16, 52))
        phase, _ = next_due(_utc(16, 55), state)
        assert phase is Phase.NONE

    def test_restart_at_1710_nothing_until_tomorrow(self):
        # SELF_CHECK's own catch-up window [17:05, 17:10) has already
        # closed by 17:10 -- no stale self-check fires this late.
        state = initial_scheduler_state(_DAY)
        phase, fire_at = next_due(_utc(17, 10), state)
        assert phase is Phase.NONE
        assert fire_at == _utc(16, 40, day=_DAY + dt.timedelta(days=1))

    def test_restart_at_0300_waits_for_1640(self):
        state = initial_scheduler_state(_DAY)
        phase, fire_at = next_due(_utc(3, 0), state)
        assert phase is Phase.NONE
        assert fire_at == _utc(16, 40)

    def test_restart_at_2350_is_midday_watch_not_nothing(self):
        # [2026-09-15] Renamed/updated from "...nothing_until_tomorrow_1640":
        # a ready, self-checked node going silent for the rest of the day
        # was exactly the mid-day relaunch plan's root-cause gap (§2 item 1)
        # -- 23:50 with readiness observed now correctly lands in
        # MIDDAY_WATCH's window, never a bare Phase.NONE.
        state = initial_scheduler_state(_DAY)
        state = mark_phase_fired(state, Phase.STOP_PRIOR, _utc(16, 40))
        state = mark_phase_fired(state, Phase.LAUNCH, _utc(16, 50))
        state = record_readiness_observed(state, _utc(16, 52))
        state = mark_phase_fired(state, Phase.SELF_CHECK, _utc(17, 5))
        phase, fire_at = next_due(_utc(23, 50), state)
        assert phase is Phase.MIDDAY_WATCH
        assert fire_at == _utc(17, 10)

    def test_self_check_due_in_its_window(self):
        state = mark_phase_fired(initial_scheduler_state(_DAY), Phase.LAUNCH, _utc(16, 50))
        state = record_readiness_observed(state, _utc(16, 52))
        phase, fire_at = next_due(_utc(17, 5), state)
        assert phase is Phase.SELF_CHECK
        assert fire_at == _utc(17, 5)

    def test_self_check_never_double_fires(self):
        state = mark_phase_fired(initial_scheduler_state(_DAY), Phase.SELF_CHECK, _utc(17, 5))
        phase, _ = next_due(_utc(17, 6), state)
        assert phase is not Phase.SELF_CHECK

    def test_self_check_still_wins_at_1705_with_readiness_observed(self):
        state = mark_phase_fired(initial_scheduler_state(_DAY), Phase.LAUNCH, _utc(16, 50))
        state = record_readiness_observed(state, _utc(16, 52))
        phase, _ = next_due(_utc(17, 5), state)
        assert phase is Phase.SELF_CHECK

    def test_midday_watch_due_after_1710_before_window_close(self):
        state = mark_phase_fired(initial_scheduler_state(_DAY), Phase.LAUNCH, _utc(16, 50))
        state = record_readiness_observed(state, _utc(16, 52))
        state = mark_phase_fired(state, Phase.SELF_CHECK, _utc(17, 5))
        phase, fire_at = next_due(_utc(18, 0), state)
        assert phase is Phase.MIDDAY_WATCH
        assert fire_at == _utc(17, 10)

    def test_midday_watch_not_due_before_readiness(self):
        state = mark_phase_fired(initial_scheduler_state(_DAY), Phase.LAUNCH, _utc(16, 50))
        state = mark_phase_fired(state, Phase.SELF_CHECK, _utc(17, 5))
        phase, _ = next_due(_utc(18, 0), state)
        assert phase is not Phase.MIDDAY_WATCH

    def test_midday_watch_not_due_after_window_close(self):
        next_day = _DAY + dt.timedelta(days=1)
        state = mark_phase_fired(initial_scheduler_state(_DAY), Phase.LAUNCH, _utc(16, 50))
        state = record_readiness_observed(state, _utc(16, 52))
        state = mark_phase_fired(state, Phase.SELF_CHECK, _utc(17, 5))
        phase, _ = next_due(_utc(1, 0, day=next_day), state)
        assert phase is not Phase.MIDDAY_WATCH

    def test_day_rollover_resets_all_done_flags(self):
        yesterday = _DAY - dt.timedelta(days=1)
        state = initial_scheduler_state(yesterday)
        state = mark_phase_fired(state, Phase.STOP_PRIOR, _utc(16, 40, day=yesterday))
        state = mark_phase_fired(state, Phase.LAUNCH, _utc(16, 50, day=yesterday))
        state = mark_phase_fired(state, Phase.SELF_CHECK, _utc(17, 5, day=yesterday))
        phase, _ = next_due(_utc(16, 45), state)
        assert phase is Phase.STOP_PRIOR

    def test_readiness_observed_blocks_relaunch_check_forever_that_day(self):
        state = mark_phase_fired(initial_scheduler_state(_DAY), Phase.LAUNCH, _utc(16, 50))
        state = record_readiness_observed(state, _utc(16, 51))
        for minute in range(51, 60):
            phase, _ = next_due(_utc(16, minute), state)
            assert phase is not Phase.RELAUNCH_CHECK

    def test_relaunch_attempt_bookkeeping_round_trips(self):
        state = initial_scheduler_state(_DAY)
        state = record_relaunch_attempt(state, _utc(16, 51))
        assert state.relaunch_attempts == 1
        assert state.last_relaunch_attempt_at == _utc(16, 51)
        state = record_relaunch_attempt(state, _utc(16, 55))
        assert state.relaunch_attempts == 2

    def test_state_survives_midnight_rollover_before_stop_prior_utc(self):
        # [2026-09-15] The 00:00-16:40Z dead zone belongs to the trading
        # day that opened at yesterday's 16:40Z STOP_PRIOR, not the new
        # UTC calendar date -- a poll at 00:30Z the next calendar day must
        # not reset today's already-latched bookkeeping.
        next_day = _DAY + dt.timedelta(days=1)
        state = mark_phase_fired(initial_scheduler_state(_DAY), Phase.SELF_CHECK, _utc(17, 5))
        state = record_relaunch_attempt(state, _utc(16, 51))
        assert state.relaunch_attempts == 1

        state = record_readiness_observed(state, _utc(0, 30, day=next_day))
        assert state.day == _DAY
        assert state.self_check_done is True
        assert state.relaunch_attempts == 1
        assert state.readiness_observed is True

    def test_state_still_rolls_over_at_stop_prior_utc(self):
        next_day = _DAY + dt.timedelta(days=1)
        state = mark_phase_fired(initial_scheduler_state(_DAY), Phase.SELF_CHECK, _utc(17, 5))
        state = mark_phase_fired(state, Phase.STOP_PRIOR, _utc(16, 40, day=next_day))
        assert state.day == next_day
        assert state.self_check_done is False
        assert state.stop_prior_done is True

    def test_next_scheduled_event_after_utc_midnight_names_todays_stop_prior(self):
        # readiness_observed deliberately left False -- keeps this case out
        # of MIDDAY_WATCH's gate so it isolates _next_scheduled_event's own
        # effective.day != today guard (a MIDDAY_WATCH-eligible variant of
        # this same midnight crossing is covered separately).
        next_day = _DAY + dt.timedelta(days=1)
        state = mark_phase_fired(initial_scheduler_state(_DAY), Phase.STOP_PRIOR, _utc(16, 40))
        state = mark_phase_fired(state, Phase.LAUNCH, _utc(16, 50))
        state = mark_phase_fired(state, Phase.SELF_CHECK, _utc(17, 5))
        phase, fire_at = next_due(_utc(0, 30, day=next_day), state)
        assert phase is Phase.NONE
        # today's (next_day's) own still-upcoming STOP_PRIOR -- never D+2.
        assert fire_at == _utc(16, 40, day=next_day)


def test_parse_permit_expiry_ns_extracts_the_real_marker_shape():
    log = "live-trading permit issued issued_at_ns=100 expires_at_ns=999 ttl_s=1\n"
    assert parse_permit_expiry_ns(log) == 999


def test_parse_permit_expiry_ns_none_when_absent():
    assert parse_permit_expiry_ns("nothing here") is None


# ---------------------------------------------------------------------------
# [H1] Incremental log reader -- a multi-MB prefix is never re-read.
# ---------------------------------------------------------------------------


class TestIncrementalLogReader:
    def test_second_call_returns_only_new_bytes(self, tmp_path):
        path = tmp_path / "node.log"
        path.write_text("AAAA")
        reader = IncrementalLogReader()
        first = reader.read_new(path)
        assert first == "AAAA"
        with open(path, "a") as fh:
            fh.write("BBBB")
        second = reader.read_new(path)
        assert "BBBB" in second
        assert second.count("A") <= len("AAAA")  # no re-read of the old prefix

    def test_multi_megabyte_prefix_is_read_at_most_once(self, tmp_path):
        path = tmp_path / "node.log"
        big_prefix = "x" * (5 * 1024 * 1024)
        path.write_text(big_prefix)
        reader = IncrementalLogReader()
        reader.read_new(path)
        assert reader.bytes_read(path) == len(big_prefix)
        with open(path, "a") as fh:
            fh.write("tail-marker")
        second = reader.read_new(path)
        # The second read must be small (carry + new bytes only), never the
        # multi-MB prefix again.
        assert len(second) < 10_000
        assert "tail-marker" in second
        assert reader.bytes_read(path) == len(big_prefix) + len("tail-marker")

    def test_marker_split_across_two_reads_is_still_found(self, tmp_path):
        path = tmp_path / "node.log"
        marker = "live-trading permit issued issued_at_ns=1 expires_at_ns=2 ttl_s=3"
        split_point = marker.index("issued_at_ns=") + 5
        path.write_text(marker[:split_point])
        reader = IncrementalLogReader(carry_bytes=64)
        first = reader.read_new(path)
        assert marker not in first
        with open(path, "a") as fh:
            fh.write(marker[split_point:])
        second = reader.read_new(path)
        assert marker in second

    def test_truncated_file_resets_offset(self, tmp_path):
        path = tmp_path / "node.log"
        path.write_text("A" * 1000)
        reader = IncrementalLogReader()
        reader.read_new(path)
        path.write_text("short")
        result = reader.read_new(path)
        assert "short" in result

    def test_missing_file_returns_carry_without_raising(self, tmp_path):
        reader = IncrementalLogReader()
        assert reader.read_new(tmp_path / "missing.log") == ""


# ---------------------------------------------------------------------------
# [M2] /proc/locks lock-type filtering -- FLOCK only, never POSIX.
# ---------------------------------------------------------------------------


def _synthetic_locks_file(tmp_path: Path, *, lock_type: str, pid: int, target: Path) -> Path:
    stat = target.stat()
    major, minor = os.major(stat.st_dev), os.minor(stat.st_dev)
    locks = tmp_path / "proc_locks"
    locks.write_text(
        f"1: {lock_type}  ADVISORY  WRITE {pid} {major:02x}:{minor:02x}:{stat.st_ino} 0 EOF\n"
    )
    return locks


class TestFlockTypeFiltering:
    def test_flock_line_is_recognised(self, tmp_path):
        target = tmp_path / "x.lock"
        target.touch()
        locks = _synthetic_locks_file(tmp_path, lock_type="FLOCK", pid=4242, target=target)
        assert resolve_lock_holder_pid(target, locks_path=locks) == 4242
        assert count_lock_holders(target, locks_path=locks) == 1

    def test_posix_line_on_the_same_inode_is_never_the_holder(self, tmp_path):
        target = tmp_path / "x.lock"
        target.touch()
        locks = _synthetic_locks_file(tmp_path, lock_type="POSIX", pid=4242, target=target)
        assert resolve_lock_holder_pid(target, locks_path=locks) is None
        assert count_lock_holders(target, locks_path=locks) == 0

    def test_posix_line_is_never_counted_alongside_a_real_flock_holder(self, tmp_path):
        target = tmp_path / "x.lock"
        target.touch()
        stat = target.stat()
        major, minor = os.major(stat.st_dev), os.minor(stat.st_dev)
        locks = tmp_path / "proc_locks"
        locks.write_text(
            f"1: POSIX  ADVISORY  WRITE 111 {major:02x}:{minor:02x}:{stat.st_ino} 0 EOF\n"
            f"2: FLOCK  ADVISORY  WRITE 222 {major:02x}:{minor:02x}:{stat.st_ino} 0 EOF\n"
        )
        assert resolve_lock_holder_pid(target, locks_path=locks) == 222
        assert count_lock_holders(target, locks_path=locks) == 1

    def test_real_flock_via_default_locks_path_still_works(self, tmp_path):
        # End-to-end sanity against the REAL /proc/locks (no injected path),
        # matching the round-1 test but confirming the FLOCK filter didn't
        # break the real-kernel path.
        lock_path = tmp_path / "real.lock"
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            assert resolve_lock_holder_pid(lock_path) == os.getpid()
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)


# ---------------------------------------------------------------------------
# [L3] TOCTOU-safe terminate: recheck immediately before SIGTERM.
# ---------------------------------------------------------------------------


class TestTerminateAfterToctouRecheck:
    def test_signals_when_pid_still_holds_the_lock(self):
        sent: list[int] = []
        terminate_after_toctou_recheck(
            777,
            intent_lock_path_=Path("/does/not/matter"),
            resolve_holder=lambda _p: 777,
            terminate_fn=sent.append,
            is_alive=lambda _pid: True,
        )
        assert sent == [777]

    def test_refuses_when_pid_no_longer_exists(self):
        sent: list[int] = []
        with pytest.raises(StopPriorRaceRefused):
            terminate_after_toctou_recheck(
                777,
                intent_lock_path_=Path("/does/not/matter"),
                resolve_holder=lambda _p: 777,
                terminate_fn=sent.append,
                is_alive=lambda _pid: False,
            )
        assert sent == []

    def test_refuses_when_pid_no_longer_holds_the_lock(self):
        sent: list[int] = []
        with pytest.raises(StopPriorRaceRefused):
            terminate_after_toctou_recheck(
                777,
                intent_lock_path_=Path("/does/not/matter"),
                resolve_holder=lambda _p: 999,  # a DIFFERENT pid now holds it
                terminate_fn=sent.append,
                is_alive=lambda _pid: True,
            )
        assert sent == []

    def test_never_sends_a_signal_other_than_via_terminate_fn(self):
        # terminate_fn is the ONLY way this function ever signals a process
        # -- confirmed by construction (no os.kill call site here); this
        # test pins that the real default terminate_fn is `terminate`,
        # which sends SIGTERM only.
        import inspect

        sig = inspect.signature(terminate_after_toctou_recheck)
        assert sig.parameters["terminate_fn"].default is terminate

    def test_stop_prior_refuses_a_zombie_pid_with_the_nonexistent_reason(self):
        pid = os.fork()
        if pid == 0:
            os._exit(0)
        try:
            _wait_for_zombie(pid)
            sent: list[int] = []
            with pytest.raises(StopPriorRaceRefused, match="pid no longer exists"):
                terminate_after_toctou_recheck(
                    pid,
                    intent_lock_path_=Path("/does/not/matter"),
                    resolve_holder=lambda _p: pid,
                    terminate_fn=sent.append,
                    is_alive=process_is_alive,
                )
            assert sent == []
        finally:
            os.waitpid(pid, 0)

    # -- AUD-13d HIGH-1: the stop-intent marker is written BEFORE the signal --

    def test_a_store_path_writes_the_stop_intent_marker_before_signalling(self, tmp_path):
        store_path = tmp_path / "state" / "store.sqlite3"
        store_path.parent.mkdir(parents=True)
        order: list[str] = []
        sent: list[int] = []
        # A REAL, live pid: the default `write_stop_intent_marker` binds the
        # marker to `/proc/<pid>/stat`'s own start time (2026-09-24 review,
        # pid-reuse hardening), so a synthetic pid like 777 would read as
        # "already gone" and nothing would be written. This process's own
        # pid is alive for the whole test.
        target_pid = os.getpid()

        def _terminate_fn(pid: int) -> None:
            order.append("terminate")
            sent.append(pid)

        terminate_after_toctou_recheck(
            target_pid,
            intent_lock_path_=Path("/does/not/matter"),
            resolve_holder=lambda _p: target_pid,
            terminate_fn=_terminate_fn,
            is_alive=lambda _pid: True,
            store_path=store_path,
        )

        assert sent == [target_pid]
        # The marker was written for THIS pid before the signal was sent --
        # asserted by consuming it now: a marker that was never written (or
        # written for the wrong pid/incarnation) reports False.
        assert consume_stop_intent_marker(store_path, target_pid) is True

    def test_a_terminate_fn_that_raises_still_removes_the_marker_and_propagates(
        self, tmp_path
    ):
        """[2026-09-24 review, HIGH] ``os.kill`` racing a target that died
        right after the TOCTOU recheck must never leave an orphaned marker
        for a LATER, unrelated process to (mis)match -- and the original
        failure must still reach the caller exactly as before."""
        store_path = tmp_path / "state" / "store.sqlite3"
        store_path.parent.mkdir(parents=True)
        target_pid = os.getpid()

        def _raising_terminate_fn(pid: int) -> None:
            raise ProcessLookupError(f"no such process: {pid}")

        with pytest.raises(ProcessLookupError):
            terminate_after_toctou_recheck(
                target_pid,
                intent_lock_path_=Path("/does/not/matter"),
                resolve_holder=lambda _p: target_pid,
                terminate_fn=_raising_terminate_fn,
                is_alive=lambda _pid: True,
                store_path=store_path,
            )

        assert not stop_intent_marker_path(store_path).exists()

    def test_a_terminate_fn_exception_without_a_store_path_still_propagates(self, tmp_path):
        """Regression guard: wrapping ``terminate_fn`` in a try/except must
        not swallow the failure for callers that pass no ``store_path``."""

        def _raising_terminate_fn(pid: int) -> None:
            raise ProcessLookupError(f"no such process: {pid}")

        with pytest.raises(ProcessLookupError):
            terminate_after_toctou_recheck(
                777,
                intent_lock_path_=Path("/does/not/matter"),
                resolve_holder=lambda _p: 777,
                terminate_fn=_raising_terminate_fn,
                is_alive=lambda _pid: True,
            )

    def test_no_store_path_writes_no_marker_backward_compatible_default(self, tmp_path):
        """Every EXISTING caller omits ``store_path`` -- confirms the new
        parameter is opt-in and changes nothing for them."""
        store_path = tmp_path / "state" / "store.sqlite3"  # never passed in below
        sent: list[int] = []

        terminate_after_toctou_recheck(
            777,
            intent_lock_path_=Path("/does/not/matter"),
            resolve_holder=lambda _p: 777,
            terminate_fn=sent.append,
            is_alive=lambda _pid: True,
        )

        assert sent == [777]
        assert not stop_intent_marker_path(store_path).exists()

    def test_a_refused_recheck_never_writes_the_marker(self, tmp_path):
        """[L3] The marker is corroborating evidence for a signal that WAS
        sent -- a race-refused terminate must leave no marker behind to
        wrongly suppress a later, unrelated boot-halt."""
        store_path = tmp_path / "state" / "store.sqlite3"
        store_path.parent.mkdir(parents=True)
        sent: list[int] = []

        with pytest.raises(StopPriorRaceRefused):
            terminate_after_toctou_recheck(
                777,
                intent_lock_path_=Path("/does/not/matter"),
                resolve_holder=lambda _p: 999,
                terminate_fn=sent.append,
                is_alive=lambda _pid: True,
                store_path=store_path,
            )

        assert sent == []
        assert not stop_intent_marker_path(store_path).exists()


# ---------------------------------------------------------------------------
# process_is_alive -- a zombie must never read as alive (os.kill(pid, 0)
# alone succeeds against a zombie; the real fix inspects /proc/<pid>/stat).
# ---------------------------------------------------------------------------


def _read_proc_stat_state(pid: int) -> str | None:
    """Test-only, independent parse of ``/proc/<pid>/stat``'s state field --
    deliberately duplicated rather than reusing the production helper, so
    the positive control below never depends on the code under test."""
    try:
        raw = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    after_comm = raw.rsplit(")", 1)[-1]
    fields = after_comm.split()
    return fields[0] if fields else None


def _wait_for_zombie(pid: int, *, timeout: float = 1.0) -> None:
    """Poll briefly for ``pid`` to become a zombie. Raises (never a bare
    ``assert``) if the deadline passes first, so a child that never exits
    surfaces as a broken test environment rather than a silent pass."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _read_proc_stat_state(pid) == "Z":
            return
        time.sleep(0.01)
    raise RuntimeError(f"child pid {pid} never reached zombie state within {timeout}s")


class TestProcessIsAlive:
    def test_a_zombie_child_is_not_alive(self):
        pid = os.fork()
        if pid == 0:
            os._exit(0)
        try:
            # Positive control FIRST: confirm, independently of the code
            # under test, that this pid really is a zombie.
            _wait_for_zombie(pid)
            assert _read_proc_stat_state(pid) == "Z"
            assert process_is_alive(pid) is False
        finally:
            os.waitpid(pid, 0)

    def test_a_running_child_is_still_alive(self):
        pid = os.fork()
        if pid == 0:
            time.sleep(5)
            os._exit(0)
        try:
            assert process_is_alive(pid) is True
        finally:
            os.kill(pid, signal.SIGKILL)
            os.waitpid(pid, 0)

    def test_an_adopted_zombie_pid_is_not_alive(self):
        # No Popen object anywhere in scope -- wired the same way
        # `default_ports` wires the real `process_is_alive` in, then called
        # through the `SupervisorPorts` port rather than the bare function.
        pid = os.fork()
        if pid == 0:
            os._exit(0)
        try:
            _wait_for_zombie(pid)
            ports = _make_ports(process_alive=process_is_alive)
            assert ports.process_alive(pid) is False
        finally:
            os.waitpid(pid, 0)


# ---------------------------------------------------------------------------
# Fakes for the wired daily loop.
# ---------------------------------------------------------------------------


class FakeClock:
    def __init__(self, start: dt.datetime) -> None:
        self.current = start

    def __call__(self) -> dt.datetime:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current = self.current + dt.timedelta(seconds=seconds)


class FakePopen:
    def __init__(self, pid: int) -> None:
        self.pid = pid

    def poll(self) -> int | None:
        """Harness stand-in for ``subprocess.Popen.poll`` -- still running."""
        return None


class FakeSpawner:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self._next_pid = 9000

    def __call__(self, **kwargs) -> FakePopen:
        self._next_pid += 1
        self.calls.append(kwargs)
        return FakePopen(self._next_pid)


# A far-future expiry (2100-01-01T00:00:00Z in ns) -- comfortably beyond any
# real test "now", unlike a small literal that reads as already-expired
# against a real epoch-based nanosecond timestamp.
_READY_LOG_LINES = (
    "live-trading permit issued issued_at_ns=1 expires_at_ns=4102444800000000000 ttl_s=1\n"
    "CurrentRungHoldStrategy subscribed X\n"
)


def _make_ports(**overrides) -> SupervisorPorts:
    base = {
        "find_node_pid": lambda: None,
        "resolve_intent_lock_holder": lambda _p: None,
        "intent_lock_free": lambda _p: True,
        "count_intent_lock_holders": lambda _p: 0,
        "terminate_after_recheck": lambda pid, **kw: None,
        "process_alive": lambda _pid: False,
        "probe_open_intent_state": lambda *a, **kw: False,
        "spawn": FakeSpawner(),
        "read_log_new": lambda _p: "",
        "alert_sink": _RecordingAlertSink(),
        "sigterm_poll_sleep": lambda _s: None,
    }
    base.update(overrides)
    return SupervisorPorts(**base)


# ---------------------------------------------------------------------------
# The wired daily loop -- FakeClock + fake sleep advancing it + fake ports.
# ---------------------------------------------------------------------------


class TestRunForeverWiredLoop:
    def _run(self, *, clock: FakeClock, ports: SupervisorPorts, max_iterations: int, tmp_path):
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

    def test_exactly_one_sigterm_at_1640_when_pids_match(self, tmp_path):
        clock = FakeClock(_utc(16, 39, 30))
        terminate_calls: list[int] = []
        ports = _make_ports(
            find_node_pid=lambda: 555,
            resolve_intent_lock_holder=lambda _p: 555,
            terminate_after_recheck=lambda pid, **kw: terminate_calls.append(pid),
        )
        self._run(clock=clock, ports=ports, max_iterations=200, tmp_path=tmp_path)
        assert terminate_calls == [555]

    def test_exactly_one_spawn_at_1650(self, tmp_path):
        clock = FakeClock(_utc(16, 49, 30))
        spawner = FakeSpawner()
        ports = _make_ports(spawn=spawner, intent_lock_free=lambda _p: True)
        self._run(clock=clock, ports=ports, max_iterations=30, tmp_path=tmp_path)
        assert len(spawner.calls) == 1

    def test_exactly_one_self_check_line_at_1705(self, tmp_path, caplog):
        clock = FakeClock(_utc(17, 4, 30))
        ports = _make_ports()
        with caplog.at_level("INFO"):
            self._run(clock=clock, ports=ports, max_iterations=30, tmp_path=tmp_path)
        self_check_lines = [r for r in caplog.records if "self_check" in r.getMessage()]
        assert len(self_check_lines) == 1

    def test_no_double_fire_across_a_sleep_overshoot(self, tmp_path):
        # A fake sleep that overshoots past 16:50 in one jump must still
        # fire LAUNCH exactly once, not once per iteration afterwards.
        clock = FakeClock(_utc(16, 30, 0))
        spawner = FakeSpawner()
        ports = _make_ports(spawn=spawner)
        self._run(clock=clock, ports=ports, max_iterations=400, tmp_path=tmp_path)
        assert len(spawner.calls) == 1

    def test_no_fire_before_1640_after_a_0300_start(self, tmp_path):
        clock = FakeClock(_utc(3, 0, 0))
        terminate_calls: list[int] = []
        spawner = FakeSpawner()
        ports = _make_ports(
            terminate_after_recheck=lambda pid, **kw: terminate_calls.append(pid),
            spawn=spawner,
        )
        # Advance only a few bounded-sleep iterations -- nowhere near 16:40.
        self._run(clock=clock, ports=ports, max_iterations=5, tmp_path=tmp_path)
        assert terminate_calls == []
        assert spawner.calls == []
        assert clock.current < _utc(16, 40)

    def test_idle_tick_reaps_a_retained_zombie_before_the_60s_sleep(self, tmp_path):
        """WP-0a residual (module docstring of ``_run_forever``'s
        ``Phase.NONE`` branch): a child SIGTERM'd at STOP_PRIOR could
        previously sit ``<defunct>`` until the NEXT DAY's RELAUNCH_CHECK,
        because nothing called ``_reap_spawned_children()`` during an idle
        ``Phase.NONE`` tick. This test reuses the real WP-0a
        zombie-producing fixture (``_wait_for_zombie`` /
        ``_retain_spawned_child`` / ``_read_proc_stat_state``, the same
        ones ``test_a_retained_zombie_is_reaped_when_another_pid_is_probed``
        uses) rather than a fake, so it proves the ACTUAL OS-level zombie
        is gone, not just that some mock was called.

        03:00Z is the same idle window ``test_no_fire_before_1640_after_a_
        0300_start`` uses -- ``next_due`` returns ``Phase.NONE`` on every
        tick until 16:40Z, so every one of the bounded iterations below
        takes the idle branch."""
        from breezy.runtime.trade_supervisor import _retain_spawned_child

        proc = subprocess.Popen(
            [sys.executable, "-c", "import os; os._exit(0)"],
            start_new_session=True,
        )
        try:
            _wait_for_zombie(proc.pid)
            assert _read_proc_stat_state(proc.pid) == "Z"
            _retain_spawned_child(proc)

            clock = FakeClock(_utc(3, 0, 0))
            ports = _make_ports()
            # Two idle iterations is enough: the reap call precedes the
            # bounded sleep on every Phase.NONE tick, including the first.
            self._run(clock=clock, ports=ports, max_iterations=2, tmp_path=tmp_path)

            assert _read_proc_stat_state(proc.pid) is None
            assert clock.current < _utc(16, 40)
        finally:
            try:
                os.waitpid(proc.pid, os.WNOHANG)
            except ChildProcessError:
                pass

    def test_adoption_at_1640_after_a_0300_start(self, tmp_path):
        clock = FakeClock(_utc(3, 0, 0))
        terminate_calls: list[int] = []
        ports = _make_ports(
            find_node_pid=lambda: 42,
            resolve_intent_lock_holder=lambda _p: 42,
            terminate_after_recheck=lambda pid, **kw: terminate_calls.append(pid),
        )
        self._run(clock=clock, ports=ports, max_iterations=900, tmp_path=tmp_path)
        assert terminate_calls == [42]

    def test_exception_in_stop_prior_does_not_prevent_launch(self, tmp_path):
        clock = FakeClock(_utc(16, 39, 0))
        calls = {"n": 0}

        def _boom_once_then_none():
            # Only STOP_PRIOR's own call site should see the failure --
            # LAUNCH's later (legitimate) call to the same port must
            # succeed, or this test can't tell "contained" from "also
            # broken".
            calls["n"] += 1
            if calls["n"] == 1:
                raise ValueError("synthetic stop_prior failure")

        spawner = FakeSpawner()
        ports = _make_ports(find_node_pid=_boom_once_then_none, spawn=spawner)
        self._run(clock=clock, ports=ports, max_iterations=60, tmp_path=tmp_path)
        assert len(spawner.calls) == 1

    def test_started_at_2350_does_nothing_until_1640_next_day(self, tmp_path):
        clock = FakeClock(_utc(23, 50, 0))
        terminate_calls: list[int] = []
        spawner = FakeSpawner()
        ports = _make_ports(
            find_node_pid=lambda: 99,
            resolve_intent_lock_holder=lambda _p: 99,
            terminate_after_recheck=lambda pid, **kw: terminate_calls.append(pid),
            spawn=spawner,
        )
        # Advance a bounded number of iterations -- not yet at tomorrow's
        # 16:40, so nothing touches the "running" node.
        self._run(clock=clock, ports=ports, max_iterations=10, tmp_path=tmp_path)
        assert terminate_calls == []
        assert spawner.calls == []

    def test_readiness_stops_further_relaunch_checks_from_spawning(self, tmp_path):
        clock = FakeClock(_utc(16, 49, 30))
        spawner = FakeSpawner()
        ports = _make_ports(
            spawn=spawner,
            process_alive=lambda _pid: True,
            resolve_intent_lock_holder=lambda _p: spawner.calls and 9001,
            read_log_new=lambda _p: _READY_LOG_LINES,
        )
        self._run(clock=clock, ports=ports, max_iterations=60, tmp_path=tmp_path)
        assert len(spawner.calls) == 1  # never relaunched once ready

    def test_phase_exception_is_contained_and_alerted(self, tmp_path):
        clock = FakeClock(_utc(17, 4, 30))
        sink = _RecordingAlertSink()

        def _boom(**_kw):
            raise RuntimeError("self-check exploded")

        ports = _make_ports(alert_sink=sink, count_intent_lock_holders=_boom)
        self._run(clock=clock, ports=ports, max_iterations=10, tmp_path=tmp_path)
        assert any(p.detail == AlertDetail.PHASE_EXCEPTION_CONTAINED.value for p in sink.payloads)

    def test_max_iterations_bounds_the_loop_for_tests(self, tmp_path):
        clock = FakeClock(_utc(3, 0, 0))
        ports = _make_ports()
        # Must return (not hang) once max_iterations is exhausted.
        self._run(clock=clock, ports=ports, max_iterations=3, tmp_path=tmp_path)


class TestPhaseHandlersDirect:
    def test_do_stop_prior_noop_when_nothing_tracked(self, tmp_path):
        store_path = tmp_path / "state" / "store.sqlite3"
        ports = _make_ports()
        result = _do_stop_prior(ports=ports, store_path=store_path, tracked_pid=None)
        assert result is None

    def test_stop_prior_after_midday_exhaustion_with_dead_pid_is_a_noop_not_adoption_refused(
        self, tmp_path
    ):
        # Seeded exactly as a next-day boot after a mid-day-exhausted node
        # would arrive: `_do_midday_watch` kept the dead pid as
        # `tracked_pid` (intended), but the process is gone, nothing holds
        # the intent flock, and pgrep finds nothing either -- this must be
        # a true NOOP, never a spurious REFUSE_ALERT page.
        store_path = tmp_path / "state" / "store.sqlite3"
        sink = _RecordingAlertSink()
        terminated: list[int] = []
        ports = _make_ports(
            alert_sink=sink,
            process_alive=lambda _pid: False,
            resolve_intent_lock_holder=lambda _p: None,
            find_node_pid=lambda: None,
            terminate_after_recheck=lambda pid, **_kw: terminated.append(pid),
        )
        result = _do_stop_prior(ports=ports, store_path=store_path, tracked_pid=1001)
        assert result is None
        assert sink.payloads == []
        assert terminated == []

    def test_stop_prior_uses_a_live_tracked_pid_directly(self, tmp_path):
        # Regression guard: a LIVE tracked pid is still trusted and used
        # directly, never overridden by `find_node_pid` -- `find_node_pid`
        # is left unreachable here (raises if called) to pin that.
        def _boom():
            raise AssertionError("find_node_pid must not be called for a live tracked pid")

        store_path = tmp_path / "state" / "store.sqlite3"
        terminated: list[int] = []
        ports = _make_ports(
            process_alive=lambda _pid: True,
            resolve_intent_lock_holder=lambda _p: 1001,
            find_node_pid=_boom,
            terminate_after_recheck=lambda pid, **_kw: terminated.append(pid),
        )
        result = _do_stop_prior(ports=ports, store_path=store_path, tracked_pid=1001)
        assert result is None
        assert terminated == [1001]

    def test_stop_prior_passes_its_own_store_path_to_the_terminate_port(self, tmp_path):
        """AUD-13d HIGH-1: ``_do_stop_prior`` never resolves a marker path of
        its own -- it hands its ``store_path`` straight to the port, which
        owns writing the marker."""
        store_path = tmp_path / "state" / "store.sqlite3"
        received: dict[str, object] = {}

        def _terminate_after_recheck(pid: int, **kwargs: object) -> None:
            received["pid"] = pid
            received.update(kwargs)

        ports = _make_ports(
            process_alive=lambda _pid: True,
            resolve_intent_lock_holder=lambda _p: 1001,
            terminate_after_recheck=_terminate_after_recheck,
        )
        result = _do_stop_prior(ports=ports, store_path=store_path, tracked_pid=1001)

        assert result is None
        assert received["pid"] == 1001
        assert received["store_path"] == store_path

    def test_do_launch_refuses_when_lock_held(self, tmp_path):
        store_path = tmp_path / "state" / "store.sqlite3"
        sink = _RecordingAlertSink()
        ports = _make_ports(intent_lock_free=lambda _p: False, alert_sink=sink)
        pid, log, _state, done = _do_launch(
            ports=ports,
            state=initial_scheduler_state(_DAY),
            now=_utc(16, 50),
            store_path=store_path,
            repo_root=tmp_path,
            node_bin=tmp_path / "node_bin",
            log_dir=tmp_path / "logs",
        )
        assert (pid, log, done) == (None, None, True)
        assert sink.payloads[-1].detail == AlertDetail.LAUNCH_BLOCKED_LOCK_HELD.value

    def test_do_launch_refuses_when_node_pid_present_despite_free_lock(self, tmp_path):
        store_path = tmp_path / "state" / "store.sqlite3"
        probed: list[object] = []
        ports = _make_ports(
            find_node_pid=lambda: 123,
            intent_lock_free=lambda _p: True,
            probe_open_intent_state=lambda *a, **kw: probed.append(kw) or False,
        )
        pid, log, _state, done = _do_launch(
            ports=ports,
            state=initial_scheduler_state(_DAY),
            now=_utc(16, 50),
            store_path=store_path,
            repo_root=tmp_path,
            node_bin=tmp_path / "node_bin",
            log_dir=tmp_path / "logs",
        )
        assert (pid, log, done) == (None, None, True)
        assert probed == []  # the probe must never run while a node pid is live

    def test_do_self_check_pass_logs_no_alert(self, tmp_path):
        store_path = tmp_path / "state" / "store.sqlite3"
        sink = _RecordingAlertSink()
        ports = _make_ports(
            resolve_intent_lock_holder=lambda _p: 42,
            count_intent_lock_holders=lambda _p: 1,
            process_alive=lambda _pid: True,
            read_log_new=lambda _p: _READY_LOG_LINES,
            alert_sink=sink,
        )
        _do_self_check(
            ports=ports,
            now=_utc(17, 5),
            store_path=store_path,
            log_dir=tmp_path / "logs",
            tracked_pid=42,
            node_log=tmp_path / "n.log",
        )
        assert sink.payloads == []


# ===========================================================================
# Fix 2026-09-05 (traced live, both log files): `_do_self_check` computed
# `strategy_subscribed` from `ports.read_log_new(node_log)` on the SAME
# shared, offset-draining `IncrementalLogReader` that `_do_relaunch_check`
# already drains while polling `readiness_observed` through the launch
# window. `readiness_observed` needs `permit_issued`, which is legitimately
# absent at boot, so the poller kept draining the offset past the
# `CurrentRungHoldStrategy subscribed` lines; the reader's 256-byte carry
# cannot hold them across the node's later, much larger, order-book-tick
# volume. By SELF_CHECK time the shared reader's own delta held only later
# noise, so `self_check` returned FAIL_NODE_NOT_READY for a subscription
# that genuinely happened -- a false negative from two call sites sharing
# one offset-consuming reader.
# ===========================================================================


class TestStickyStrategySubscribedAcrossSharedReader:
    def test_self_check_does_not_false_fail_after_relaunch_polls_drain_the_marker(
        self, tmp_path
    ):
        from breezy.runtime.trade_supervisor_core import STRATEGY_SUBSCRIBED_MARKER

        node_log = tmp_path / "node.log"
        # The strategy subscribes exactly once, early, at boot.
        node_log.write_text(
            "CurrentRungHoldStrategy subscribed instrument=X\n"
            "CurrentRungHoldStrategy subscribed instrument=Y\n"
        )
        # ONE shared reader -- exactly like `default_ports()` wires it: both
        # `_do_relaunch_check` and `_do_self_check` read through the same
        # instance, so an earlier read's offset advance is visible to a
        # later read from either call site.
        reader = IncrementalLogReader()
        sink = _RecordingAlertSink()
        store_path = tmp_path / "state" / "store.sqlite3"
        tracked_pid = 9001
        ports = _make_ports(
            resolve_intent_lock_holder=lambda _p: tracked_pid,
            count_intent_lock_holders=lambda _p: 1,
            process_alive=lambda _pid: True,
            read_log_new=reader.read_new,
            alert_sink=sink,
        )
        state = initial_scheduler_state(_DAY)
        # >256 bytes of later, unrelated order-book-tick noise per poll --
        # bigger than the reader's carry, and permit_issued never fires, so
        # `readiness_observed` never latches via the pre-fix code path and
        # RELAUNCH_CHECK keeps polling every pass through the window.
        noise = "order book tick " + ("x" * 300) + "\n"
        for i in range(5):
            tracked_pid, node_log, state = _do_relaunch_check(
                ports=ports,
                state=state,
                now=_utc(16, 50, i),
                tracked_pid=tracked_pid,
                node_log=node_log,
                store_path=store_path,
                repo_root=tmp_path,
                node_bin=tmp_path / "node_bin",
                log_dir=tmp_path / "logs",
            )
            with node_log.open("a") as fh:
                fh.write(noise * 3)

        # Sanity: permit was never issued, so readiness genuinely never
        # latched -- this fix must not paper over that real gap.
        assert state.readiness_observed is False

        # By now the shared reader's own next delta holds only noise --
        # the marker text is not present in any single read any more.
        assert STRATEGY_SUBSCRIBED_MARKER not in reader.read_new(node_log)

        _, _, state = _do_self_check(
            ports=ports,
            now=_utc(17, 5),
            store_path=store_path,
            log_dir=tmp_path / "logs",
            tracked_pid=tracked_pid,
            node_log=node_log,
            state=state,
        )

        # The real, distinct failure (no permit was ever issued) must still
        # surface -- this fix narrows the false negative, it does not mask
        # a genuine one.
        assert sink.payloads[-1].detail == (
            AlertDetail.SELF_CHECK_FAIL_SHADOW_MODE_NO_PERMIT.value
        )
        assert sink.payloads[-1].detail != AlertDetail.SELF_CHECK_FAIL_NOT_READY.value

    def test_record_strategy_subscribed_seen_is_sticky_and_idempotent(self):
        state = initial_scheduler_state(_DAY)
        assert state.strategy_subscribed_seen is False
        state = record_strategy_subscribed_seen(state, _utc(16, 50, 5))
        assert state.strategy_subscribed_seen is True
        # Idempotent -- a later call the same day changes nothing else.
        again = record_strategy_subscribed_seen(state, _utc(16, 55))
        assert again == state


# ===========================================================================
# Fix 2026-09-06 (traced live): `_do_self_check` computed `permit_issued`
# and `permit_expiry_valid` from `ports.read_log_new(node_log)` on the SAME
# shared, offset-draining `IncrementalLogReader` that `_do_relaunch_check`
# already drains while polling. Commit 06d8900 latched
# `strategy_subscribed_seen` for this exact reason, but left the permit
# marker un-latched. The permit is issued once at boot; by 17:05 the
# reader's delta no longer contains that line, so a node that holds a
# valid permit false-negatives as FAIL_SHADOW_MODE_NO_PERMIT.
# ===========================================================================

_FAR_FUTURE_EXPIRES_AT_NS = 4102444800000000000
_PERMIT_ISSUED_LINE = (
    "live-trading permit issued issued_at_ns=1788713409710026893 "
    f"expires_at_ns={_FAR_FUTURE_EXPIRES_AT_NS} ttl_s=36000\n"
)
_STRATEGY_SUBSCRIBED_LINE = "CurrentRungHoldStrategy subscribed instrument=X\n"


def _drain_relaunch_polls_past_boot_markers(
    *,
    tmp_path,
    node_log: Path,
    now_relaunch: dt.datetime,
) -> tuple[IncrementalLogReader, _RecordingAlertSink, object, int, Path]:
    """Shared IncrementalLogReader + five RELAUNCH_CHECK polls that leave
    only later noise in the next delta -- the same drain that 06d8900
    covered for the strategy marker."""
    from breezy.runtime.trade_supervisor_core import (
        PERMIT_ISSUED_MARKER,
        STRATEGY_SUBSCRIBED_MARKER,
    )

    reader = IncrementalLogReader()
    sink = _RecordingAlertSink()
    store_path = tmp_path / "state" / "store.sqlite3"
    tracked_pid = 9001
    ports = _make_ports(
        resolve_intent_lock_holder=lambda _p: tracked_pid,
        count_intent_lock_holders=lambda _p: 1,
        process_alive=lambda _pid: True,
        read_log_new=reader.read_new,
        alert_sink=sink,
    )
    state = initial_scheduler_state(now_relaunch.date())
    noise = "order book tick " + ("x" * 300) + "\n"
    for i in range(5):
        tracked_pid, node_log, state = _do_relaunch_check(
            ports=ports,
            state=state,
            now=now_relaunch.replace(second=i),
            tracked_pid=tracked_pid,
            node_log=node_log,
            store_path=store_path,
            repo_root=tmp_path,
            node_bin=tmp_path / "node_bin",
            log_dir=tmp_path / "logs",
        )
        with node_log.open("a") as fh:
            fh.write(noise * 3)

    leftover = reader.read_new(node_log)
    assert STRATEGY_SUBSCRIBED_MARKER not in leftover
    assert PERMIT_ISSUED_MARKER not in leftover
    return reader, sink, state, tracked_pid, node_log


class TestStickyPermitIssuedAcrossSharedReader:
    def test_self_check_passes_when_permit_line_was_drained_by_relaunch_polls(self, tmp_path):
        node_log = tmp_path / "node.log"
        node_log.write_text(_STRATEGY_SUBSCRIBED_LINE + _PERMIT_ISSUED_LINE)
        reader, sink, state, tracked_pid, node_log = _drain_relaunch_polls_past_boot_markers(
            tmp_path=tmp_path,
            node_log=node_log,
            now_relaunch=_utc(16, 50),
        )
        ports = _make_ports(
            resolve_intent_lock_holder=lambda _p: tracked_pid,
            count_intent_lock_holders=lambda _p: 1,
            process_alive=lambda _pid: True,
            read_log_new=reader.read_new,
            alert_sink=sink,
        )

        _, _, state = _do_self_check(
            ports=ports,
            now=_utc(17, 5),
            store_path=tmp_path / "state" / "store.sqlite3",
            log_dir=tmp_path / "logs",
            tracked_pid=tracked_pid,
            node_log=node_log,
            state=state,
        )

        assert sink.payloads == []
        assert state.permit_issued_seen_expires_at_ns == _FAR_FUTURE_EXPIRES_AT_NS

    def test_self_check_still_fails_when_latched_permit_has_expired(self, tmp_path):
        expired_ns = 1
        node_log = tmp_path / "node.log"
        node_log.write_text(
            _STRATEGY_SUBSCRIBED_LINE
            + (
                "live-trading permit issued issued_at_ns=1788713409710026893 "
                f"expires_at_ns={expired_ns} ttl_s=36000\n"
            )
        )
        reader, sink, state, tracked_pid, node_log = _drain_relaunch_polls_past_boot_markers(
            tmp_path=tmp_path,
            node_log=node_log,
            now_relaunch=_utc(16, 50),
        )
        ports = _make_ports(
            resolve_intent_lock_holder=lambda _p: tracked_pid,
            count_intent_lock_holders=lambda _p: 1,
            process_alive=lambda _pid: True,
            read_log_new=reader.read_new,
            alert_sink=sink,
        )

        _, _, state = _do_self_check(
            ports=ports,
            now=_utc(17, 5),
            store_path=tmp_path / "state" / "store.sqlite3",
            log_dir=tmp_path / "logs",
            tracked_pid=tracked_pid,
            node_log=node_log,
            state=state,
        )

        assert sink.payloads[-1].detail == (AlertDetail.SELF_CHECK_FAIL_SHADOW_MODE_NO_PERMIT.value)
        assert state.permit_issued_seen_expires_at_ns == expired_ns

    def test_permit_latch_resets_on_next_days_launch_so_stale_permit_cannot_pass(self, tmp_path):
        yesterday = _DAY - dt.timedelta(days=1)
        state = initial_scheduler_state(yesterday)
        state = record_permit_issued_seen(
            state, _utc(16, 50, day=yesterday), _FAR_FUTURE_EXPIRES_AT_NS
        )
        state = record_strategy_subscribed_seen(state, _utc(16, 50, day=yesterday))
        assert state.permit_issued_seen_expires_at_ns == _FAR_FUTURE_EXPIRES_AT_NS
        assert state.strategy_subscribed_seen is True

        state = mark_phase_fired(state, Phase.LAUNCH, _utc(16, 50))
        assert state.day == _DAY
        assert state.permit_issued_seen_expires_at_ns is None
        assert state.strategy_subscribed_seen is False

        node_log = tmp_path / "today.log"
        node_log.write_text(_STRATEGY_SUBSCRIBED_LINE)
        sink = _RecordingAlertSink()
        tracked_pid = 42
        ports = _make_ports(
            resolve_intent_lock_holder=lambda _p: tracked_pid,
            count_intent_lock_holders=lambda _p: 1,
            process_alive=lambda _pid: True,
            read_log_new=lambda _p: node_log.read_text(),
            alert_sink=sink,
        )
        _do_self_check(
            ports=ports,
            now=_utc(17, 5),
            store_path=tmp_path / "state" / "store.sqlite3",
            log_dir=tmp_path / "logs",
            tracked_pid=tracked_pid,
            node_log=node_log,
            state=state,
        )
        assert sink.payloads[-1].detail == (AlertDetail.SELF_CHECK_FAIL_SHADOW_MODE_NO_PERMIT.value)

    def test_record_permit_issued_seen_is_sticky_and_idempotent(self):
        state = initial_scheduler_state(_DAY)
        assert state.permit_issued_seen_expires_at_ns is None
        state = record_permit_issued_seen(state, _utc(16, 50, 5), _FAR_FUTURE_EXPIRES_AT_NS)
        assert state.permit_issued_seen_expires_at_ns == _FAR_FUTURE_EXPIRES_AT_NS
        again = record_permit_issued_seen(state, _utc(16, 55), 99)
        assert again == state
        assert again.permit_issued_seen_expires_at_ns == _FAR_FUTURE_EXPIRES_AT_NS

    def test_readiness_uses_latched_permit_when_lock_ownership_arrives_in_a_later_poll(
        self, tmp_path, caplog
    ):
        """Poll 1 consumes the permit+subscribed lines while the intent lock
        is still not held by the tracked pid; poll 2's delta is empty and
        the holder is now the tracked pid. Readiness must use the latched
        permit, not the live (empty) delta, or a healthy node never
        records ``node_ready``."""
        node_log = tmp_path / "node.log"
        node_log.write_text(_STRATEGY_SUBSCRIBED_LINE + _PERMIT_ISSUED_LINE)
        store_path = tmp_path / "state" / "store.sqlite3"
        tracked_pid = 9001
        session: dict = {"holder": None}
        # Scripted deltas, not IncrementalLogReader: the reader's 256-byte
        # carry would still return the short boot markers on an empty
        # second read, which is not the "permit already consumed" case.
        deltas = [_STRATEGY_SUBSCRIBED_LINE + _PERMIT_ISSUED_LINE, ""]
        ports = _make_ports(
            resolve_intent_lock_holder=lambda _p: session["holder"],
            count_intent_lock_holders=lambda _p: 0 if session["holder"] is None else 1,
            process_alive=lambda _pid: True,
            read_log_new=lambda _p: deltas.pop(0) if deltas else "",
        )
        state = initial_scheduler_state(_DAY)

        with caplog.at_level("INFO"):
            _, _, state = _do_relaunch_check(
                ports=ports,
                state=state,
                now=_utc(16, 50, 0),
                tracked_pid=tracked_pid,
                node_log=node_log,
                store_path=store_path,
                repo_root=tmp_path,
                node_bin=tmp_path / "node_bin",
                log_dir=tmp_path / "logs",
            )
        assert state.permit_issued_seen_expires_at_ns is not None
        assert state.strategy_subscribed_seen is True
        assert state.readiness_observed is False

        session["holder"] = tracked_pid
        with caplog.at_level("INFO"):
            _, _, state = _do_relaunch_check(
                ports=ports,
                state=state,
                now=_utc(16, 50, 1),
                tracked_pid=tracked_pid,
                node_log=node_log,
                store_path=store_path,
                repo_root=tmp_path,
                node_bin=tmp_path / "node_bin",
                log_dir=tmp_path / "logs",
            )

        assert state.readiness_observed is True
        assert any("node_ready" in r.getMessage() for r in caplog.records)


# ===========================================================================
# Follow-up (2026-09-06): the permit/strategy latches must not survive a
# same-day relaunch. `_for_day` only resets them on a calendar-day change;
# `_do_relaunch_check` opens a NEW child with a NEW log via
# `record_relaunch_attempt` and must clear both latches there. Evidence is
# per-child: a relaunched node in SHADOW mode (no permit line) must not
# inherit child 1's still-valid expiry, and a relaunched node that never
# subscribes must not inherit child 1's `strategy_subscribed_seen`.
# No existing test pinned the old cross-relaunch stickiness
# (`test_record_strategy_subscribed_seen_is_sticky_and_idempotent` is
# same-child idempotence; `test_permit_latch_resets_on_next_days_launch_*`
# is `_for_day` rollover; `test_relaunch_attempt_bookkeeping_round_trips`
# only checks attempt count/timestamp).
# ===========================================================================

_TRADING_NODE_FAILED_LINE = "breezy-trade: trading node failed: ConnectionError\n"
_CHILD2_EXPIRES_AT_NS = 4200000000000000000
_CHILD2_PERMIT_ISSUED_LINE = (
    "live-trading permit issued issued_at_ns=1788713409710026894 "
    f"expires_at_ns={_CHILD2_EXPIRES_AT_NS} ttl_s=36000\n"
)


def _latch_child1_then_relaunch_on_crash(
    *,
    tmp_path,
    child1_log_text: str,
) -> tuple[
    SupervisorPorts,
    object,
    dict,
    int,
    Path,
    IncrementalLogReader,
    _RecordingAlertSink,
    Path,
    Path,
]:
    """Child 1 boots (markers latched, flock not held so readiness never
    fires), crashes with a transient marker, and `_do_relaunch_check`
    opens child 2 on a new log. Returns the live session so the caller
    can write child 2's log and flip liveness/lock before self-check."""
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    store_path = tmp_path / "state" / "store.sqlite3"
    child1_log = tmp_path / "child1.log"
    child1_log.write_text(child1_log_text)
    child1_pid = 111
    session: dict = {"alive": {child1_pid}, "holder": None}
    reader = IncrementalLogReader()
    sink = _RecordingAlertSink()
    ports = _make_ports(
        resolve_intent_lock_holder=lambda _p: session["holder"],
        count_intent_lock_holders=lambda _p: 0 if session["holder"] is None else 1,
        process_alive=lambda pid: pid in session["alive"],
        read_log_new=reader.read_new,
        alert_sink=sink,
        spawn=FakeSpawner(),
    )
    from breezy.runtime.trade_supervisor_core import (
        PERMIT_ISSUED_MARKER,
        STRATEGY_SUBSCRIBED_MARKER,
    )

    state = initial_scheduler_state(_DAY)
    _, _, state = _do_relaunch_check(
        ports=ports,
        state=state,
        now=_utc(16, 50),
        tracked_pid=child1_pid,
        node_log=child1_log,
        store_path=store_path,
        repo_root=tmp_path,
        node_bin=tmp_path / "node_bin",
        log_dir=log_dir,
    )
    assert state.readiness_observed is False
    if STRATEGY_SUBSCRIBED_MARKER in child1_log_text:
        assert state.strategy_subscribed_seen is True
    if PERMIT_ISSUED_MARKER in child1_log_text:
        assert state.permit_issued_seen_expires_at_ns is not None

    session["alive"].clear()
    with child1_log.open("a") as fh:
        fh.write(_TRADING_NODE_FAILED_LINE)
    child2_pid, child2_log, state = _do_relaunch_check(
        ports=ports,
        state=state,
        now=_utc(16, 58),
        tracked_pid=child1_pid,
        node_log=child1_log,
        store_path=store_path,
        repo_root=tmp_path,
        node_bin=tmp_path / "node_bin",
        log_dir=log_dir,
    )
    assert child2_pid is not None
    assert child2_log is not None
    assert child2_log != child1_log
    assert state.relaunch_attempts == 1
    return (
        ports,
        state,
        session,
        child2_pid,
        child2_log,
        reader,
        sink,
        store_path,
        log_dir,
    )


class TestRelaunchClearsPerChildLatches:
    def test_relaunched_child_must_earn_its_own_permit(self, tmp_path):
        ports, state, session, child2_pid, child2_log, _reader, sink, store_path, log_dir = (
            _latch_child1_then_relaunch_on_crash(
                tmp_path=tmp_path,
                child1_log_text=_STRATEGY_SUBSCRIBED_LINE + _PERMIT_ISSUED_LINE,
            )
        )
        child2_log.write_text(_STRATEGY_SUBSCRIBED_LINE)
        session["alive"].add(child2_pid)
        session["holder"] = child2_pid

        _, _, state = _do_self_check(
            ports=ports,
            now=_utc(17, 5),
            store_path=store_path,
            log_dir=log_dir,
            tracked_pid=child2_pid,
            node_log=child2_log,
            state=state,
        )

        assert [p.detail for p in sink.payloads] == [
            AlertDetail.SELF_CHECK_FAIL_SHADOW_MODE_NO_PERMIT.value
        ]
        assert state.permit_issued_seen_expires_at_ns is None

    def test_relaunched_child_permit_is_latched_from_its_own_log(self, tmp_path):
        ports, state, session, child2_pid, child2_log, reader, sink, store_path, log_dir = (
            _latch_child1_then_relaunch_on_crash(
                tmp_path=tmp_path,
                child1_log_text=_STRATEGY_SUBSCRIBED_LINE + _PERMIT_ISSUED_LINE,
            )
        )
        child2_log.write_text(_STRATEGY_SUBSCRIBED_LINE + _CHILD2_PERMIT_ISSUED_LINE)
        session["alive"].add(child2_pid)
        session["holder"] = child2_pid

        from breezy.runtime.trade_supervisor_core import PERMIT_ISSUED_MARKER

        noise = "order book tick " + ("x" * 300) + "\n"
        for i in range(5):
            _, child2_log, state = _do_relaunch_check(
                ports=ports,
                state=state,
                now=_utc(16, 58, 5 + i),
                tracked_pid=child2_pid,
                node_log=child2_log,
                store_path=store_path,
                repo_root=tmp_path,
                node_bin=tmp_path / "node_bin",
                log_dir=log_dir,
            )
            with child2_log.open("a") as fh:
                fh.write(noise * 3)
        leftover = reader.read_new(child2_log)
        assert PERMIT_ISSUED_MARKER not in leftover

        _, _, state = _do_self_check(
            ports=ports,
            now=_utc(17, 5),
            store_path=store_path,
            log_dir=log_dir,
            tracked_pid=child2_pid,
            node_log=child2_log,
            state=state,
        )

        assert sink.payloads == []
        assert state.permit_issued_seen_expires_at_ns == _CHILD2_EXPIRES_AT_NS

    def test_relaunched_child_must_earn_its_own_strategy_subscription(self, tmp_path):
        ports, state, session, child2_pid, child2_log, _reader, sink, store_path, log_dir = (
            _latch_child1_then_relaunch_on_crash(
                tmp_path=tmp_path,
                child1_log_text=_STRATEGY_SUBSCRIBED_LINE + _PERMIT_ISSUED_LINE,
            )
        )
        child2_log.write_text("order book tick only\n")
        session["alive"].add(child2_pid)
        session["holder"] = child2_pid

        _, _, state = _do_self_check(
            ports=ports,
            now=_utc(17, 5),
            store_path=store_path,
            log_dir=log_dir,
            tracked_pid=child2_pid,
            node_log=child2_log,
            state=state,
        )

        assert [p.detail for p in sink.payloads] == [AlertDetail.SELF_CHECK_FAIL_NOT_READY.value]
        assert state.strategy_subscribed_seen is False


# ===========================================================================
# Follow-up 2 (2026-09-06): adoption must also discard per-child latches.
# `_do_self_check` (and `_do_launch`) can ADOPT a live flock-holder when
# `tracked_pid is None`, swapping `tracked_pid`/`node_log` without clearing
# `strategy_subscribed_seen` / `permit_issued_seen_expires_at_ns`. A stale
# same-day latch from an earlier child then makes self-check PASS on the
# previous node's expiry even when the adopted node's log has no permit.
# Evidence is per-child: the adopted node must prove its own subscription
# and permit from its own log. `_attempt_adoption` does not seek the
# reader; the first `read_log_new` after adoption is the IncrementalLogReader
# default for an unseen path (offset 0 -- START of the file, not the end).
# ===========================================================================


def _adopt_live_node_with_stale_latches(
    *,
    tmp_path,
    adopted_log_text: str,
) -> tuple[
    SupervisorPorts,
    object,
    IncrementalLogReader,
    _RecordingAlertSink,
    Path,
    Path,
    Path,
    int,
]:
    """Latch child-1 evidence, then present a different live flock-holder
    whose log is `adopted_log_text`. Caller invokes `_do_self_check` with
    `tracked_pid=None` so adoption runs."""
    adopted_pid = 222
    adopted_log = tmp_path / "adopted.log"
    adopted_log.write_text(adopted_log_text)
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    store_path = tmp_path / "state" / "store.sqlite3"
    reader = IncrementalLogReader()
    sink = _RecordingAlertSink()
    ports = _make_ports(
        find_node_pid=lambda: adopted_pid,
        resolve_intent_lock_holder=lambda _p: adopted_pid,
        count_intent_lock_holders=lambda _p: 1,
        process_alive=lambda _pid: True,
        find_adopted_log=lambda _log_dir, _pid: adopted_log,
        read_log_new=reader.read_new,
        alert_sink=sink,
    )
    state = initial_scheduler_state(_DAY)
    state = record_permit_issued_seen(state, _utc(16, 50), _FAR_FUTURE_EXPIRES_AT_NS)
    state = record_strategy_subscribed_seen(state, _utc(16, 50))
    assert state.permit_issued_seen_expires_at_ns == _FAR_FUTURE_EXPIRES_AT_NS
    assert state.strategy_subscribed_seen is True
    return ports, state, reader, sink, store_path, log_dir, adopted_log, adopted_pid


class TestAdoptionClearsPerChildLatches:
    def test_adopted_node_must_earn_its_own_permit(self, tmp_path):
        ports, state, _reader, sink, store_path, log_dir, _adopted_log, _pid = (
            _adopt_live_node_with_stale_latches(
                tmp_path=tmp_path,
                adopted_log_text=_STRATEGY_SUBSCRIBED_LINE,
            )
        )

        _, _, state = _do_self_check(
            ports=ports,
            now=_utc(17, 5),
            store_path=store_path,
            log_dir=log_dir,
            tracked_pid=None,
            node_log=None,
            state=state,
        )

        assert [p.detail for p in sink.payloads] == [
            AlertDetail.SELF_CHECK_FAIL_SHADOW_MODE_NO_PERMIT.value
        ]
        assert state.permit_issued_seen_expires_at_ns is None

    def test_adopted_node_permit_is_latched_from_its_own_log(self, tmp_path):
        ports, state, _reader, sink, store_path, log_dir, _adopted_log, _pid = (
            _adopt_live_node_with_stale_latches(
                tmp_path=tmp_path,
                adopted_log_text=_STRATEGY_SUBSCRIBED_LINE + _CHILD2_PERMIT_ISSUED_LINE,
            )
        )

        _, _, state = _do_self_check(
            ports=ports,
            now=_utc(17, 5),
            store_path=store_path,
            log_dir=log_dir,
            tracked_pid=None,
            node_log=None,
            state=state,
        )

        assert sink.payloads == []
        assert state.permit_issued_seen_expires_at_ns == _CHILD2_EXPIRES_AT_NS


# ===========================================================================
# Re-review (HEAD 7d52377): code REVISE, three loop defects.
# D1 no pacing sleep after a non-NONE dispatch (busy loop during
# RELAUNCH_CHECK); D2 a restart mid-window with a live holder never adopts
# it (false FAIL_CHILD_EXITED for a healthy node); D3 a spawn exception
# marks LAUNCH fired with no tracked child, forfeiting the day.
# ===========================================================================


class TestD1PacingSleep:
    def test_every_iteration_sleeps_across_a_launch_to_relaunch_check_sequence(self, tmp_path):
        # A FakeClock that only ever advances INSIDE `sleep` -- if any
        # iteration dispatched a phase without sleeping afterwards, the
        # clock would stall relative to the iteration count.
        clock = FakeClock(_utc(16, 49, 30))
        sleep_calls = {"n": 0}

        def counting_sleep(seconds: float) -> None:
            sleep_calls["n"] += 1
            clock.advance(seconds)

        spawner = FakeSpawner()
        ports = _make_ports(
            spawn=spawner,
            process_alive=lambda _pid: True,
            resolve_intent_lock_holder=lambda _p: 9001 if spawner.calls else None,
            read_log_new=lambda _p: "",  # never ready -> RELAUNCH_CHECK fires repeatedly
        )
        iterations = 40
        _run_forever(
            store_path=tmp_path / "state" / "store.sqlite3",
            repo_root=tmp_path,
            node_bin=tmp_path / "node_bin",
            log_dir=tmp_path / "logs",
            clock=clock,
            sleep=counting_sleep,
            ports=ports,
            max_iterations=iterations,
        )
        # Every one of the 40 iterations -- NONE waits AND every dispatched
        # phase (including a repeatedly-due RELAUNCH_CHECK) -- called sleep
        # exactly once. No zero-delay busy-loop iteration exists.
        assert sleep_calls["n"] == iterations

    def test_stub_sleep_called_once_per_real_time_iteration(self, tmp_path):
        calls = {"n": 0}

        def stub_sleep(_seconds: float) -> None:
            calls["n"] += 1

        ports = _make_ports()
        _run_forever(
            store_path=tmp_path / "state" / "store.sqlite3",
            repo_root=tmp_path,
            node_bin=tmp_path / "node_bin",
            log_dir=tmp_path / "logs",
            clock=lambda: dt.datetime.now(dt.UTC),
            sleep=stub_sleep,
            ports=ports,
            max_iterations=3,
        )
        assert calls["n"] == 3


class TestD2AdoptionMidWindow:
    def _run(self, *, clock: FakeClock, ports: SupervisorPorts, max_iterations: int, tmp_path):
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

    def test_1655_restart_with_live_holder_adopts_never_spawns_passes_at_1705(self, tmp_path):
        clock = FakeClock(_utc(16, 55, 0))
        spawner = FakeSpawner()
        sink = _RecordingAlertSink()
        ports = _make_ports(
            spawn=spawner,
            find_node_pid=lambda: 777,
            intent_lock_free=lambda _p: False,
            resolve_intent_lock_holder=lambda _p: 777,
            count_intent_lock_holders=lambda _p: 1,
            process_alive=lambda _pid: True,
            find_adopted_log=lambda _log_dir, _pid: None,
            alert_sink=sink,
        )
        self._run(clock=clock, ports=ports, max_iterations=80, tmp_path=tmp_path)
        assert spawner.calls == []  # never spawned a second node
        fail_alerts = [p for p in sink.payloads if "SELF_CHECK_FAIL" in p.event]
        assert fail_alerts == []

    def test_1706_restart_with_live_holder_adopts_at_self_check_passes(self, tmp_path):
        clock = FakeClock(_utc(17, 6, 0))
        spawner = FakeSpawner()
        sink = _RecordingAlertSink()
        ports = _make_ports(
            spawn=spawner,
            find_node_pid=lambda: 888,
            resolve_intent_lock_holder=lambda _p: 888,
            count_intent_lock_holders=lambda _p: 1,
            process_alive=lambda _pid: True,
            find_adopted_log=lambda _log_dir, _pid: None,
            alert_sink=sink,
        )
        self._run(clock=clock, ports=ports, max_iterations=5, tmp_path=tmp_path)
        assert spawner.calls == []
        fail_alerts = [p for p in sink.payloads if "SELF_CHECK_FAIL" in p.event]
        assert fail_alerts == []


class TestD3SpawnExceptionRetriesWithinBudget:
    def _run(self, *, clock: FakeClock, ports: SupervisorPorts, max_iterations: int, tmp_path):
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

    def test_first_spawn_raises_second_succeeds_after_gap_exactly_two_calls(self, tmp_path):
        clock = FakeClock(_utc(16, 49, 30))
        calls = {"n": 0}

        def flaky_spawn(**_kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise OSError("synthetic spawn failure")
            return FakePopen(9999)

        ports = _make_ports(spawn=flaky_spawn)
        self._run(clock=clock, ports=ports, max_iterations=40, tmp_path=tmp_path)
        assert calls["n"] == 2  # day not forfeited -- the retry actually ran

    def test_two_spawn_raises_refuses_and_alerts_no_third_attempt(self, tmp_path):
        clock = FakeClock(_utc(16, 49, 30))
        sink = _RecordingAlertSink()
        calls = {"n": 0}

        def always_raise(**_kwargs):
            calls["n"] += 1
            raise OSError("synthetic spawn failure")

        ports = _make_ports(spawn=always_raise, alert_sink=sink)
        self._run(clock=clock, ports=ports, max_iterations=60, tmp_path=tmp_path)
        assert calls["n"] == 2
        assert any(p.detail == AlertDetail.LAUNCH_SPAWN_FAILED.value for p in sink.payloads)


class TestFindAdoptedNodeLog:
    def test_returns_none_when_process_start_time_unknown(self, tmp_path):
        # PID 0 owns no /proc/0 directory readable this way in practice;
        # use a PID that cannot possibly exist to force the "unknown" path.
        assert find_adopted_node_log(tmp_path, 2**30) is None

    def test_returns_the_newest_qualifying_log_for_the_current_process(self, tmp_path):
        old_log = tmp_path / "breezy-trade-20260101T000000Z.log"
        old_log.write_text("old")
        import os
        import time

        # Backdate the old log well before this process's own start time so
        # it is correctly excluded as stale.
        past = time.time() - 3600
        os.utime(old_log, (past, past))

        new_log = tmp_path / "breezy-trade-20260904T165000Z.log"
        new_log.write_text("new")

        result = find_adopted_node_log(tmp_path, os.getpid())
        assert result == new_log


# ===========================================================================
# Production observation: launched with argv/RLIMIT_CORE/lock all correct,
# but `main` never configured logging, so every INFO `log_decision` line
# (including the 17:05 PASS/FAIL line) was silently dropped by Python's
# WARNING-only "lastResort" handler. Fixed in `configure_supervisor_logging`,
# called from `main` after argv validation and before the lock.
# ===========================================================================


def _logger_under_test() -> logging.Logger:
    return logging.getLogger("breezy.runtime.trade_supervisor")


def _count_supervisor_handlers() -> int:
    """This module's logger is process-global and pytest's own log-capture
    plugin attaches its OWN handler(s) to every named logger (to support
    ``caplog`` even when the logger under test sets ``propagate = False``,
    which :func:`configure_supervisor_logging` deliberately does) --
    unrelated to this module's own idempotency. Count only the two marker
    subclasses this module itself ever adds."""
    return sum(
        isinstance(h, _SupervisorFileHandler | _SupervisorStreamHandler)
        for h in _logger_under_test().handlers
    )


def _reset_supervisor_logging_handlers() -> None:
    """Test-only teardown: this module's logger is process-global, so tests
    that configure it must not leak ITS OWN handlers (or a stale target
    path) into a later test. Never touches a handler this module didn't
    add (e.g. pytest's own capture handler) -- that is pytest's to manage."""
    logger = _logger_under_test()
    for handler in list(logger.handlers):
        if isinstance(handler, _SupervisorFileHandler | _SupervisorStreamHandler):
            handler.close()
            logger.removeHandler(handler)


class TestSupervisorLoggingConfiguration:
    def teardown_method(self) -> None:
        _reset_supervisor_logging_handlers()

    def _run_main_with_fake_loop(self, *, monkeypatch, tmp_path, home: Path):
        monkeypatch.setenv("HOME", str(home))
        store_path = tmp_path / "state" / "store.sqlite3"
        store_path.parent.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv(EXEC_STATE_DB_ENV_VAR, str(store_path))
        monkeypatch.setattr("breezy.runtime.trade_supervisor._run_forever", lambda **_kwargs: None)
        return main([SUPERVISOR_ARGV_TOKEN])

    def test_main_writes_supervisor_started_into_the_log_file(self, monkeypatch, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        exit_code = self._run_main_with_fake_loop(
            monkeypatch=monkeypatch, tmp_path=tmp_path, home=home
        )
        assert exit_code == EXIT_OK

        log_dir = home / ".local" / "share" / "breezy" / "logs"
        log_path = supervisor_log_path(log_dir)
        assert log_path.exists()
        content = log_path.read_text()
        assert "supervisor_started" in content
        # UTC-formatted timestamp prefix, per line -- e.g. "2026-09-05T...Z".
        assert "Z INFO breezy.runtime.trade_supervisor supervisor_started" in content

    def test_supervisor_started_logs_a_revision_field(self, monkeypatch, tmp_path):
        """AUD-14a: the supervisor records the build revision it is running
        so a restart's motive (deploy vs not) is inferable after the fact by
        diffing consecutive `revision=` values -- see
        docs/plans/backlog/AUDIT_2026-09-21/AUD-14-...md, §6/§7 14a."""
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv(BUILD_REVISION_ENV_VAR, "deadbeef123")
        self._run_main_with_fake_loop(monkeypatch=monkeypatch, tmp_path=tmp_path, home=home)

        log_path = supervisor_log_path(home / ".local" / "share" / "breezy" / "logs")
        content = log_path.read_text()
        assert "supervisor_started" in content
        assert "revision=deadbeef123" in content

    def test_an_absent_revision_logs_unknown_rather_than_omitting_the_field(
        self, monkeypatch, tmp_path
    ):
        """When the env var, the git-file lookup, AND package metadata all
        come up empty, the field is still present -- `revision=unknown`,
        never omitted (an absent field is indistinguishable from an old
        binary)."""
        import importlib.metadata

        import breezy.runtime.trade_supervisor as ts_module

        def _raise_not_found(_name: str) -> str:
            raise importlib.metadata.PackageNotFoundError

        monkeypatch.delenv(BUILD_REVISION_ENV_VAR, raising=False)
        monkeypatch.setattr(ts_module, "_read_source_tree_head_sha", lambda: None)
        monkeypatch.setattr(importlib.metadata, "version", _raise_not_found)

        home = tmp_path / "home"
        home.mkdir()
        self._run_main_with_fake_loop(monkeypatch=monkeypatch, tmp_path=tmp_path, home=home)

        log_path = supervisor_log_path(home / ".local" / "share" / "breezy" / "logs")
        content = log_path.read_text()
        assert "revision=unknown" in content

    def test_the_revision_field_is_never_read_from_an_operator_reserved_variable(self):
        """The resolver's ENV lookup consults only `BUILD_REVISION_ENV_VAR`
        -- never one of the two operator-reserved caps -- regardless of
        what the git-file/metadata fallbacks resolve to."""
        from breezy.adapters.polymarket_us.operator_controls import (
            OPERATOR_RESERVED_CONTROL_ENV_VARS,
        )

        class _RecordingEnv(dict):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.accessed_keys: list[str] = []

            def get(self, key, default=None):
                self.accessed_keys.append(key)
                return super().get(key, default)

        env = _RecordingEnv(
            {var: "sentinel-operator-value" for var in OPERATOR_RESERVED_CONTROL_ENV_VARS}
        )

        revision = _resolve_build_revision(env)

        assert revision != "sentinel-operator-value"
        for reserved_var in OPERATOR_RESERVED_CONTROL_ENV_VARS:
            assert reserved_var not in env.accessed_keys

    def test_resolve_build_revision_falls_through_to_metadata_when_the_git_head_sha_is_unavailable(
        self, monkeypatch
    ):
        """`_read_source_tree_head_sha` returning `None` (an ordinary,
        anticipated "this isn't resolvable from .git" outcome, e.g. a
        non-editable install) is NOT an exception -- it is a clean
        fall-through to `importlib.metadata.version`, never straight to
        "unknown"."""
        import importlib.metadata

        import breezy.runtime.trade_supervisor as ts_module

        monkeypatch.setattr(ts_module, "_read_source_tree_head_sha", lambda: None)
        expected = importlib.metadata.version("breezy")

        revision = _resolve_build_revision({})

        assert revision == expected
        assert revision != "unknown"

    def test_resolve_build_revision_truncates_a_resolved_sha_to_twelve_characters(
        self, monkeypatch
    ):
        """No `-dirty` suffix, no full 40-char sha -- exactly the first 12
        hex characters, per the coordinator's explicit ruling."""
        import breezy.runtime.trade_supervisor as ts_module

        full_sha = "abcdef0123456789abcdef0123456789abcdef01"
        monkeypatch.setattr(ts_module, "_read_source_tree_head_sha", lambda: full_sha)

        revision = _resolve_build_revision({})

        assert revision == full_sha[:12]
        assert len(revision) == 12

    def test_resolve_build_revision_returns_unknown_and_logs_a_warning_on_any_unexpected_exception(
        self, monkeypatch, caplog
    ):
        """The WHOLE resolution is wrapped in `except Exception`: a genuine,
        unanticipated failure (as opposed to the ordinary `None`
        fall-through above) never crashes supervisor startup -- it logs one
        WARNING and returns "unknown"."""
        import breezy.runtime.trade_supervisor as ts_module

        def _boom() -> str | None:
            raise RuntimeError("simulated unexpected failure reading .git")

        monkeypatch.setattr(ts_module, "_read_source_tree_head_sha", _boom)

        with caplog.at_level("WARNING"):
            revision = _resolve_build_revision({})

        assert revision == "unknown"
        assert any(
            record.levelname == "WARNING" and "build revision" in record.getMessage()
            for record in caplog.records
        )

    def test_sentinel_env_value_never_appears_in_the_log_file(self, monkeypatch, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("BREEZY_TOTALLY_SECRET_SENTINEL", "sentinel-value-should-never-leak")
        self._run_main_with_fake_loop(monkeypatch=monkeypatch, tmp_path=tmp_path, home=home)

        log_path = supervisor_log_path(home / ".local" / "share" / "breezy" / "logs")
        assert "sentinel-value-should-never-leak" not in log_path.read_text()

    def test_handlers_are_not_duplicated_on_a_second_main_call(self, monkeypatch, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        self._run_main_with_fake_loop(monkeypatch=monkeypatch, tmp_path=tmp_path, home=home)
        count_after_first = _count_supervisor_handlers()

        self._run_main_with_fake_loop(monkeypatch=monkeypatch, tmp_path=tmp_path, home=home)
        count_after_second = _count_supervisor_handlers()

        assert count_after_first == count_after_second
        assert count_after_first == 2  # file + stderr, exactly once each

    def test_configure_supervisor_logging_is_idempotent_for_the_same_target(self, tmp_path):
        log_dir = tmp_path / "logs"
        configure_supervisor_logging(log_dir)
        configure_supervisor_logging(log_dir)
        assert _count_supervisor_handlers() == 2

    def test_configure_supervisor_logging_replaces_handlers_for_a_new_target(self, tmp_path):
        configure_supervisor_logging(tmp_path / "logs-a")
        configure_supervisor_logging(tmp_path / "logs-b")
        handlers = _logger_under_test().handlers
        assert _count_supervisor_handlers() == 2
        file_handlers = [h for h in handlers if isinstance(h, _SupervisorFileHandler)]
        assert len(file_handlers) == 1
        assert Path(file_handlers[0].baseFilename) == supervisor_log_path(tmp_path / "logs-b")

    def test_configured_logger_actually_emits_at_info_level(self, tmp_path):
        log_dir = tmp_path / "logs"
        configure_supervisor_logging(log_dir)
        log_decision("a_test_decision", pid=123)
        content = supervisor_log_path(log_dir).read_text()
        assert "a_test_decision pid=123" in content

    def test_main_accepts_an_explicit_log_dir_override_independent_of_home(
        self, monkeypatch, tmp_path
    ):
        """The root fix for the production incident: `main` must not be
        forced to derive its log directory from `Path.home()` -- it must
        accept an explicit override, so a caller (including a test) can
        always pin exactly where logging goes instead of relying on every
        one of them remembering to isolate `Path.home()` first. This test
        proves the override wins even when `Path.home()` (here the
        module's own decoy, never the real one) points somewhere else
        entirely -- no file appears there.
        """
        decoy_home = tmp_path / "decoy-home"
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: decoy_home))
        decoy_home_log_dir = decoy_home / ".local" / "share" / "breezy" / "logs"

        override_log_dir = tmp_path / "override-logs"
        store_path = tmp_path / "state" / "store.sqlite3"
        store_path.parent.mkdir(parents=True)
        monkeypatch.setenv(EXEC_STATE_DB_ENV_VAR, str(store_path))
        monkeypatch.setattr("breezy.runtime.trade_supervisor._run_forever", lambda **_kwargs: None)

        exit_code = main([SUPERVISOR_ARGV_TOKEN], log_dir=override_log_dir)

        assert exit_code == EXIT_OK
        assert supervisor_log_path(override_log_dir).exists()
        assert not decoy_home_log_dir.exists()


# ===========================================================================
# AUD-14a (coordinator REQUEST_CHANGES): `_read_git_head_sha` reads `.git`
# files directly -- no `git` subprocess, no GitPython -- to resolve the
# commit of the source tree actually imported. Each shape it must handle is
# pinned independently: an ordinary symbolic HEAD, a detached HEAD, the
# packed-refs fallback, and a linked worktree's `.git` FILE + `commondir`
# indirection (this repo's own backlog worktrees have exactly this shape).
# ===========================================================================


_FAKE_SHA = "abcdef0123456789abcdef0123456789abcdef01"


class TestReadGitHeadSha:
    def test_resolves_a_symbolic_head_via_a_loose_ref(self, tmp_path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "HEAD").write_text("ref: refs/heads/main\n")
        refs_dir = git_dir / "refs" / "heads"
        refs_dir.mkdir(parents=True)
        (refs_dir / "main").write_text(f"{_FAKE_SHA}\n")

        assert _read_git_head_sha(git_dir) == _FAKE_SHA

    def test_resolves_a_detached_head(self, tmp_path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "HEAD").write_text(f"{_FAKE_SHA}\n")

        assert _read_git_head_sha(git_dir) == _FAKE_SHA

    def test_falls_back_to_packed_refs_when_the_loose_ref_is_missing(self, tmp_path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "HEAD").write_text("ref: refs/heads/main\n")
        # No refs/heads/main loose ref file -- only packed-refs carries it,
        # exactly as happens once a branch has been packed.
        (git_dir / "packed-refs").write_text(
            "# pack-refs with: peeled fully-peeled sorted \n"
            f"{_FAKE_SHA} refs/heads/main\n"
        )

        assert _read_git_head_sha(git_dir) == _FAKE_SHA

    def test_follows_a_linked_worktree_gitdir_file_and_its_commondir(self, tmp_path):
        # Mirrors this repo's own real layout: <worktree>/.git is a FILE
        # pointing at <main>/.git/worktrees/<name>, which carries its own
        # HEAD but a `commondir` back to the shared refs.
        main_git_dir = tmp_path / "main" / ".git"
        worktree_git_dir = main_git_dir / "worktrees" / "linked"
        worktree_git_dir.mkdir(parents=True)
        (worktree_git_dir / "commondir").write_text("../..\n")
        (worktree_git_dir / "HEAD").write_text("ref: refs/heads/feature\n")
        refs_dir = main_git_dir / "refs" / "heads"
        refs_dir.mkdir(parents=True)
        (refs_dir / "feature").write_text(f"{_FAKE_SHA}\n")

        linked_git_file = tmp_path / "linked" / ".git"
        linked_git_file.parent.mkdir(parents=True)
        linked_git_file.write_text(f"gitdir: {worktree_git_dir}\n")

        assert _read_git_head_sha(linked_git_file) == _FAKE_SHA

    def test_returns_none_for_a_missing_git_directory(self, tmp_path):
        assert _read_git_head_sha(tmp_path / "nonexistent" / ".git") is None

    def test_returns_none_when_head_is_missing(self, tmp_path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        # No HEAD file at all.
        assert _read_git_head_sha(git_dir) is None

    def test_returns_none_when_the_ref_is_unresolvable(self, tmp_path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "HEAD").write_text("ref: refs/heads/ghost\n")
        # Neither a loose ref file nor packed-refs names "ghost".
        assert _read_git_head_sha(git_dir) is None

    def test_returns_none_for_a_git_file_with_unrecognised_content(self, tmp_path):
        git_file = tmp_path / ".git"
        git_file.write_text("not-a-gitdir-line\n")
        assert _read_git_head_sha(git_file) is None


# ===========================================================================
# [2026-09-15] Mid-day watch (plan §3/§4 step 6): `_do_midday_watch` mirrors
# `_do_relaunch_check` with an INDEPENDENT budget/window, a never-null
# `tracked_pid` decline contract (opposite of boot's), and NO per-poll
# flock probe outside the bounded post-relaunch readiness re-check.
# ===========================================================================


def _midday_watch_common_kwargs(tmp_path) -> dict:
    return {
        "store_path": tmp_path / "state" / "store.sqlite3",
        "repo_root": tmp_path,
        "node_bin": tmp_path / "node_bin",
        "log_dir": tmp_path / "logs",
    }


class TestDoMiddayWatch:
    def test_do_midday_watch_relaunches_a_dead_transient_child(self, tmp_path):
        node_log = tmp_path / "node.log"
        node_log.write_text(_TRADING_NODE_FAILED_LINE)
        spawner = FakeSpawner()
        ports = _make_ports(
            process_alive=lambda _pid: False,
            spawn=spawner,
            read_log_new=lambda p: p.read_text(),
        )
        state = record_readiness_observed(initial_scheduler_state(_DAY), _utc(17, 10))

        new_pid, new_log, state = _do_midday_watch(
            ports=ports,
            state=state,
            now=_utc(20, 0),
            tracked_pid=1001,
            node_log=node_log,
            **_midday_watch_common_kwargs(tmp_path),
        )

        assert len(spawner.calls) == 1
        assert new_pid != 1001
        assert new_log != node_log
        assert state.midday_relaunch_attempts == 1
        assert state.last_midday_relaunch_attempt_at == _utc(20, 0)

    def test_do_midday_watch_declines_and_alerts_on_exhaustion_exactly_once(self, tmp_path):
        from breezy.runtime.trade_supervisor_core import record_midday_relaunch_attempt

        node_log = tmp_path / "node.log"
        node_log.write_text(_TRADING_NODE_FAILED_LINE)
        sink = _RecordingAlertSink()
        ports = _make_ports(
            process_alive=lambda _pid: False,
            alert_sink=sink,
            read_log_new=lambda p: p.read_text(),
        )
        state = record_readiness_observed(initial_scheduler_state(_DAY), _utc(17, 10))
        for i in range(MIDDAY_MAX_RELAUNCH_ATTEMPTS):
            state = record_midday_relaunch_attempt(state, _utc(19, 40 + i * 6))
        assert state.midday_relaunch_attempts == MIDDAY_MAX_RELAUNCH_ATTEMPTS

        tracked_pid, _, state = _do_midday_watch(
            ports=ports,
            state=state,
            now=_utc(20, 0),
            tracked_pid=1001,
            node_log=node_log,
            **_midday_watch_common_kwargs(tmp_path),
        )

        assert state.midday_alert_sent is True
        assert [p.detail for p in sink.payloads] == [AlertDetail.MIDDAY_RELAUNCH_EXHAUSTED.value]

        # A second poll (same day) must short-circuit before ANY log read
        # or re-decision -- never re-alert.
        tracked_pid_2, _, _state_2 = _do_midday_watch(
            ports=ports,
            state=state,
            now=_utc(20, 1),
            tracked_pid=tracked_pid,
            node_log=node_log,
            **_midday_watch_common_kwargs(tmp_path),
        )
        assert len(sink.payloads) == 1
        assert tracked_pid_2 == tracked_pid

    def test_do_midday_watch_keeps_tracked_pid_after_exhaustion(self, tmp_path):
        from breezy.runtime.trade_supervisor_core import record_midday_relaunch_attempt

        node_log = tmp_path / "node.log"
        node_log.write_text(_TRADING_NODE_FAILED_LINE)
        ports = _make_ports(process_alive=lambda _pid: False)
        state = record_readiness_observed(initial_scheduler_state(_DAY), _utc(17, 10))
        for i in range(MIDDAY_MAX_RELAUNCH_ATTEMPTS):
            state = record_midday_relaunch_attempt(state, _utc(19, 40 + i * 6))

        tracked_pid, _, _state = _do_midday_watch(
            ports=ports,
            state=state,
            now=_utc(20, 0),
            tracked_pid=1001,
            node_log=node_log,
            **_midday_watch_common_kwargs(tmp_path),
        )

        # Never None on decline -- opposite of `_do_relaunch_check`'s own
        # boot-time contract -- so the dead PID stays visible in every
        # subsequent `log_decision` line for operator diagnosis.
        assert tracked_pid == 1001

    def test_do_midday_watch_noop_while_child_alive(self, tmp_path):
        node_log = tmp_path / "node.log"
        node_log.write_text("")
        holder_calls: list[Path] = []
        ports = _make_ports(
            process_alive=lambda _pid: True,
            resolve_intent_lock_holder=lambda p: (holder_calls.append(p), None)[1],
        )
        state = record_readiness_observed(initial_scheduler_state(_DAY), _utc(17, 10))

        result = _do_midday_watch(
            ports=ports,
            state=state,
            now=_utc(18, 0),
            tracked_pid=1001,
            node_log=node_log,
            **_midday_watch_common_kwargs(tmp_path),
        )

        assert result == (1001, node_log, state)
        # The steady-state "still alive" poll never needs the flock probe --
        # only the bounded post-relaunch readiness re-check does.
        assert holder_calls == []

    def test_do_midday_watch_alerts_when_relaunched_child_never_readies(self, tmp_path):
        from breezy.runtime.trade_supervisor_core import record_midday_relaunch_attempt

        node_log = tmp_path / "node.log"
        node_log.write_text("")
        sink = _RecordingAlertSink()
        ports = _make_ports(
            process_alive=lambda _pid: True,
            resolve_intent_lock_holder=lambda _p: None,  # never took the flock
            alert_sink=sink,
        )
        state = record_readiness_observed(initial_scheduler_state(_DAY), _utc(17, 10))
        relaunch_at = _utc(20, 0)
        state = record_midday_relaunch_attempt(state, relaunch_at)

        past_timeout = relaunch_at + MIDDAY_READINESS_RECHECK_TIMEOUT + dt.timedelta(seconds=1)
        tracked_pid, _, state = _do_midday_watch(
            ports=ports,
            state=state,
            now=past_timeout,
            tracked_pid=2002,
            node_log=node_log,
            **_midday_watch_common_kwargs(tmp_path),
        )

        assert tracked_pid == 2002
        assert state.midday_not_ready_alert_sent is True
        assert [p.detail for p in sink.payloads] == [
            AlertDetail.MIDDAY_RELAUNCHED_CHILD_NOT_READY.value
        ]

        # A later poll must not re-alert -- observability only, once.
        _, _, _state_2 = _do_midday_watch(
            ports=ports,
            state=state,
            now=past_timeout + dt.timedelta(seconds=60),
            tracked_pid=2002,
            node_log=node_log,
            **_midday_watch_common_kwargs(tmp_path),
        )
        assert len(sink.payloads) == 1

    def test_do_midday_watch_stops_probing_the_flock_once_relaunched_child_is_ready(
        self, tmp_path
    ):
        from breezy.runtime.trade_supervisor_core import record_midday_relaunch_attempt

        node_log = tmp_path / "node.log"
        node_log.write_text(_STRATEGY_SUBSCRIBED_LINE + _PERMIT_ISSUED_LINE)
        holder_calls: list[Path] = []
        ports = _make_ports(
            process_alive=lambda _pid: True,
            resolve_intent_lock_holder=lambda p: (holder_calls.append(p), 2002)[1],
            read_log_new=lambda p: p.read_text(),
        )
        state = record_readiness_observed(initial_scheduler_state(_DAY), _utc(17, 10))
        relaunch_at = _utc(20, 0)
        state = record_midday_relaunch_attempt(state, relaunch_at)

        # Poll where readiness becomes satisfied -- the probe fires once here.
        tracked_pid, _, state = _do_midday_watch(
            ports=ports,
            state=state,
            now=relaunch_at + dt.timedelta(seconds=30),
            tracked_pid=2002,
            node_log=node_log,
            **_midday_watch_common_kwargs(tmp_path),
        )
        assert tracked_pid == 2002
        assert len(holder_calls) == 1

        # Every later alive poll must NOT re-probe the flock.
        for i in range(1, 5):
            _, _, state = _do_midday_watch(
                ports=ports,
                state=state,
                now=relaunch_at + dt.timedelta(seconds=30 + i * 60),
                tracked_pid=2002,
                node_log=node_log,
                **_midday_watch_common_kwargs(tmp_path),
            )
        assert len(holder_calls) == 1

    def test_relaunched_child_markers_are_read_from_the_new_log(self, tmp_path):
        (tmp_path / "logs").mkdir(parents=True, exist_ok=True)
        old_log = tmp_path / "child1.log"
        old_log.write_text(_TRADING_NODE_FAILED_LINE)
        reader = IncrementalLogReader()
        session: dict = {"alive": set()}
        ports = _make_ports(
            process_alive=lambda pid: pid in session["alive"],
            read_log_new=reader.read_new,
            spawn=FakeSpawner(),
        )
        state = record_readiness_observed(initial_scheduler_state(_DAY), _utc(17, 10))

        new_pid, new_log, state = _do_midday_watch(
            ports=ports,
            state=state,
            now=_utc(20, 0),
            tracked_pid=1001,
            node_log=old_log,
            **_midday_watch_common_kwargs(tmp_path),
        )
        assert new_log != old_log
        assert state.strategy_subscribed_seen is False

        new_log.write_text("CurrentRungHoldStrategy subscribed instrument=X\n")
        session["alive"].add(new_pid)

        _, _, state = _do_midday_watch(
            ports=ports,
            state=state,
            now=_utc(20, 1),
            tracked_pid=new_pid,
            node_log=new_log,
            **_midday_watch_common_kwargs(tmp_path),
        )
        # `node_log_path` is second-granular, so the new child's own
        # `IncrementalLogReader` offset naturally starts at 0 for the new
        # path -- this marker is read from CHILD 2's log, never a stale
        # offset into child 1's.
        assert state.strategy_subscribed_seen is True

    def test_a_fatal_marker_drained_before_death_still_relaunches(self, tmp_path):
        node_log = tmp_path / "node.log"
        node_log.write_text(_TRADING_NODE_FAILED_LINE)
        reader = IncrementalLogReader()
        spawner = FakeSpawner()
        session: dict = {"alive": True}
        ports = _make_ports(
            process_alive=lambda _pid: session["alive"],
            read_log_new=reader.read_new,
            spawn=spawner,
        )
        state = record_readiness_observed(initial_scheduler_state(_DAY), _utc(17, 10))

        # Poll N: the fatal marker is present in THIS poll's delta, but the
        # process is still alive -- the death-detecting poll may be a
        # later one whose own delta no longer holds the marker text.
        tracked_pid, node_log, state = _do_midday_watch(
            ports=ports,
            state=state,
            now=_utc(20, 0),
            tracked_pid=1001,
            node_log=node_log,
            **_midday_watch_common_kwargs(tmp_path),
        )
        assert state.midday_cause_seen is RelaunchCause.TRANSIENT
        assert len(spawner.calls) == 0

        # Push the marker text out of the reader's 256-byte carry with
        # later, unrelated noise -- the exact 09-05/09-06 drain shape
        # (§3/§7): >256 bytes evicts the short marker line from the next
        # delta in a single append.
        noise = "order book tick " + ("x" * 300) + "\n"
        with node_log.open("a") as fh:
            fh.write(noise)
        _, node_log, state = _do_midday_watch(
            ports=ports,
            state=state,
            now=_utc(20, 0, 30),
            tracked_pid=tracked_pid,
            node_log=node_log,
            **_midday_watch_common_kwargs(tmp_path),
        )

        # Poll N+1: process now dead, and this poll's OWN delta no longer
        # holds the marker text -- already drained by the poll above.
        session["alive"] = False
        leftover = reader.read_new(node_log)
        assert "trading node failed" not in leftover  # sanity: genuinely drained

        new_pid, _new_log, state = _do_midday_watch(
            ports=ports,
            state=state,
            now=_utc(20, 1),
            tracked_pid=tracked_pid,
            node_log=node_log,
            **_midday_watch_common_kwargs(tmp_path),
        )

        assert len(spawner.calls) == 1
        assert new_pid != tracked_pid


# ===========================================================================
# [2026-09-15] Plan §4 step 7: `_run_forever`'s dispatch must route
# `Phase.MIDDAY_WATCH` into `_do_midday_watch`, never fall through the bare
# `else` into `_do_self_check`.
# ===========================================================================


class TestRunForeverDispatchesMiddayWatch:
    def test_run_forever_dispatches_midday_watch_phase(self, tmp_path):
        clock = FakeClock(_utc(16, 49, 30))
        spawn_calls: list[int] = []
        session: dict = {"tracked_pid": None}
        dead_pids: set[int] = set()
        kill_time = _utc(19, 57)
        killed_once = {"done": False}

        def fake_sleep(seconds: float) -> None:
            clock.advance(seconds)

        def fake_spawn(**_kwargs) -> FakePopen:
            pid = 9000 + len(spawn_calls) + 1
            spawn_calls.append(pid)
            session["tracked_pid"] = pid
            return FakePopen(pid)

        def read_log_new(_path: Path) -> str:
            if not killed_once["done"] and clock.current >= kill_time:
                killed_once["done"] = True
                dead_pids.add(session["tracked_pid"])
                return _TRADING_NODE_FAILED_LINE
            return _READY_LOG_LINES

        ports = _make_ports(
            spawn=fake_spawn,
            resolve_intent_lock_holder=lambda _p: session["tracked_pid"],
            process_alive=lambda pid: pid not in dead_pids,
            read_log_new=read_log_new,
        )

        _run_forever(
            store_path=tmp_path / "state" / "store.sqlite3",
            repo_root=tmp_path,
            node_bin=tmp_path / "node_bin",
            log_dir=tmp_path / "logs",
            clock=clock,
            sleep=fake_sleep,
            ports=ports,
            max_iterations=300,
        )

        # LAUNCH's own spawn, plus MIDDAY_WATCH's relaunch of the
        # dead-at-19:57Z child.
        assert len(spawn_calls) == 2

    def test_run_forever_never_routes_midday_watch_into_self_check(self, tmp_path, caplog):
        clock = FakeClock(_utc(16, 49, 30))
        session: dict = {"tracked_pid": None}
        spawn_calls: list[int] = []
        holder_count_calls = {"n": 0}

        def fake_sleep(seconds: float) -> None:
            clock.advance(seconds)

        def fake_spawn(**_kwargs) -> FakePopen:
            pid = 9500 + len(spawn_calls) + 1
            spawn_calls.append(pid)
            session["tracked_pid"] = pid
            return FakePopen(pid)

        def count_holders(_p: Path) -> int:
            holder_count_calls["n"] += 1
            return 1

        ports = _make_ports(
            spawn=fake_spawn,
            resolve_intent_lock_holder=lambda _p: session["tracked_pid"],
            count_intent_lock_holders=count_holders,
            process_alive=lambda _pid: True,
            read_log_new=lambda _p: _READY_LOG_LINES,
        )

        with caplog.at_level("INFO"):
            _run_forever(
                store_path=tmp_path / "state" / "store.sqlite3",
                repo_root=tmp_path,
                node_bin=tmp_path / "node_bin",
                log_dir=tmp_path / "logs",
                clock=clock,
                sleep=fake_sleep,
                ports=ports,
                max_iterations=250,  # well past 17:10Z, deep into MIDDAY_WATCH
            )

        self_check_lines = [r for r in caplog.records if "self_check" in r.getMessage()]
        # Exactly the one real 17:05Z SELF_CHECK line -- MIDDAY_WATCH never
        # produces another, because it never routes into `_do_self_check`.
        assert len(self_check_lines) == 1
        # `count_intent_lock_holders` is read ONLY by `_do_self_check` --
        # exactly one call proves MIDDAY_WATCH never dispatched there.
        assert holder_count_calls["n"] == 1


# ===========================================================================
# WP-0a: live-family subscribe marker + retained Popen so zombies are reaped.
# ===========================================================================

_CONTINUOUS_READY_LOG_LINES = (
    "live-trading permit issued issued_at_ns=1 expires_at_ns=4102444800000000000 ttl_s=1\n"
    "ContinuousRungHoldStrategy subscribed X\n"
)


class TestWp0aLiveFamilyMiddayWatchAndReap:
    def test_midday_watch_is_reachable_for_a_live_family_child(self, tmp_path):
        """A continuous-family subscribe line must latch readiness so
        ``next_due`` enters MIDDAY_WATCH after 17:10Z. Today the wrong
        marker leaves ``readiness_observed`` false and gates the watch off."""
        node_log = tmp_path / "node.log"
        node_log.write_text(_CONTINUOUS_READY_LOG_LINES)
        tracked_pid = 4242
        ports = _make_ports(
            process_alive=lambda _pid: True,
            resolve_intent_lock_holder=lambda _p: tracked_pid,
            read_log_new=lambda p: p.read_text(),
        )
        state = mark_phase_fired(initial_scheduler_state(_DAY), Phase.LAUNCH, _utc(16, 50))
        _, _, state = _do_relaunch_check(
            ports=ports,
            state=state,
            now=_utc(16, 55),
            tracked_pid=tracked_pid,
            node_log=node_log,
            store_path=tmp_path / "state" / "store.sqlite3",
            repo_root=tmp_path,
            node_bin=tmp_path / "node_bin",
            log_dir=tmp_path / "logs",
        )
        assert state.strategy_subscribed_seen is True
        assert state.readiness_observed is True
        state = mark_phase_fired(state, Phase.SELF_CHECK, _utc(17, 5))
        phase, fire_at = next_due(_utc(18, 0), state)
        assert phase is Phase.MIDDAY_WATCH
        assert fire_at == _utc(17, 10)

    def test_a_zombie_child_is_reaped_and_relaunched_not_stuck_fail_node_not_ready(
        self, tmp_path, caplog
    ):
        """``_do_launch`` must keep the Popen so a state-Z child is reaped
        via ``poll``/``waitpid``, and MIDDAY_WATCH then takes the relaunch
        path."""
        proc = subprocess.Popen(
            [sys.executable, "-c", "import os; os._exit(0)"],
            start_new_session=True,
        )
        try:
            _wait_for_zombie(proc.pid)
            assert _read_proc_stat_state(proc.pid) == "Z"

            ports = _make_ports(
                spawn=lambda **_kw: proc,
                intent_lock_free=lambda _p: True,
                process_alive=process_is_alive,
            )
            pid, _log, state, done = _do_launch(
                ports=ports,
                state=initial_scheduler_state(_DAY),
                now=_utc(16, 50),
                store_path=tmp_path / "state" / "store.sqlite3",
                repo_root=tmp_path,
                node_bin=tmp_path / "node_bin",
                log_dir=tmp_path / "logs",
            )
            assert (pid, done) == (proc.pid, True)
            assert process_is_alive(pid) is False
            # Reaped: the pid is gone, not left sitting in state Z.
            assert _read_proc_stat_state(pid) is None

            node_log = tmp_path / "node.log"
            node_log.write_text("trading node failed\n")
            relaunch_spawner = FakeSpawner()
            watch_ports = _make_ports(
                process_alive=process_is_alive,
                spawn=relaunch_spawner,
                read_log_new=lambda p: p.read_text(),
            )
            state = record_readiness_observed(state, _utc(16, 55))
            new_pid, _new_log, state = _do_midday_watch(
                ports=watch_ports,
                state=state,
                now=_utc(20, 0),
                tracked_pid=pid,
                node_log=node_log,
                **_midday_watch_common_kwargs(tmp_path),
            )
            assert len(relaunch_spawner.calls) == 1
            assert new_pid != pid
            assert state.midday_relaunch_attempts == 1
        finally:
            try:
                os.waitpid(proc.pid, os.WNOHANG)
            except ChildProcessError:
                pass

    def test_a_retained_zombie_is_reaped_when_another_pid_is_probed(self):
        """Sweep the whole retain table: a dead child we are not currently
        asking about must still be waitpid'd, otherwise it sits
        ``<defunct>`` until the supervisor exits."""
        from breezy.runtime.trade_supervisor import _retain_spawned_child

        proc = subprocess.Popen(
            [sys.executable, "-c", "import os; os._exit(0)"],
            start_new_session=True,
        )
        try:
            _wait_for_zombie(proc.pid)
            assert _read_proc_stat_state(proc.pid) == "Z"
            _retain_spawned_child(proc)
            other_pid = proc.pid + 1
            assert process_is_alive(other_pid) is False
            assert _read_proc_stat_state(proc.pid) is None
        finally:
            try:
                os.waitpid(proc.pid, os.WNOHANG)
            except ChildProcessError:
                pass

    def test_run_forever_live_family_self_check_passes_and_midday_relaunches(
        self, tmp_path, caplog
    ):
        """End-to-end: continuous-family log → 17:05Z PASS (not
        FAIL_NODE_NOT_READY) and a dead child after 17:10Z is relaunched
        by MIDDAY_WATCH."""
        clock = FakeClock(_utc(16, 49, 30))
        spawn_calls: list[int] = []
        session: dict = {"tracked_pid": None}
        dead_pids: set[int] = set()
        kill_time = _utc(19, 57)
        killed_once = {"done": False}

        def fake_sleep(seconds: float) -> None:
            clock.advance(seconds)

        def fake_spawn(**_kwargs) -> FakePopen:
            pid = 9000 + len(spawn_calls) + 1
            spawn_calls.append(pid)
            session["tracked_pid"] = pid
            return FakePopen(pid)

        def read_log_new(_path: Path) -> str:
            if not killed_once["done"] and clock.current >= kill_time:
                killed_once["done"] = True
                dead_pids.add(session["tracked_pid"])
                return "trading node failed\n"
            return _CONTINUOUS_READY_LOG_LINES

        ports = _make_ports(
            spawn=fake_spawn,
            resolve_intent_lock_holder=lambda _p: session["tracked_pid"],
            count_intent_lock_holders=lambda _p: 1,
            process_alive=lambda pid: pid not in dead_pids,
            read_log_new=read_log_new,
        )

        with caplog.at_level("INFO"):
            _run_forever(
                store_path=tmp_path / "state" / "store.sqlite3",
                repo_root=tmp_path,
                node_bin=tmp_path / "node_bin",
                log_dir=tmp_path / "logs",
                clock=clock,
                sleep=fake_sleep,
                ports=ports,
                max_iterations=300,
            )

        self_check_lines = [
            r.getMessage() for r in caplog.records if "self_check" in r.getMessage()
        ]
        assert len(self_check_lines) == 1
        assert "FAIL_NODE_NOT_READY" not in self_check_lines[0]
        assert "PASS" in self_check_lines[0]
        assert len(spawn_calls) == 2
