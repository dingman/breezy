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
import subprocess
import sys
from pathlib import Path

import pytest

from breezy.adapters.polymarket_us.factories import EXEC_STATE_DB_ENV_VAR
from breezy.runtime.health import AlertPayload
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import RetirementReason, open_submit_intent_latch
from breezy.runtime.trade_supervisor import (
    EXIT_CONFIG_ERROR,
    EXIT_OK,
    NODE_CONSOLE_SCRIPT,
    IncrementalLogReader,
    StopPriorRaceRefused,
    SupervisorPorts,
    _do_launch,
    _do_self_check,
    _do_stop_prior,
    _run_forever,
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
    resolve_lock_holder_pid,
    spawn_node,
    supervisor_lock_path,
    supervisor_log_path,
    terminate,
    terminate_after_toctou_recheck,
)
from breezy.runtime.trade_supervisor_core import (
    MAX_RELAUNCH_ATTEMPTS,
    MIN_RELAUNCH_GAP,
    RELAUNCH_CUTOFF_UTC,
    SUPERVISOR_ARGV_TOKEN,
    AlertDetail,
    ExitConfigErrorCause,
    LaunchAction,
    Phase,
    PreLaunchProbeInvariantError,
    RelaunchCause,
    SelfCheckResult,
    StopPriorAction,
    assert_no_live_node_before_intent_probe,
    classify_exit1_cause,
    decide_launch_action,
    decide_relaunch,
    decide_stop_prior_action,
    disambiguate_exit_config_error,
    initial_scheduler_state,
    mark_phase_fired,
    next_due,
    parse_permit_expiry_ns,
    readiness_observed,
    record_readiness_observed,
    record_relaunch_attempt,
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

    def test_restart_at_2350_nothing_until_tomorrow_1640(self):
        state = initial_scheduler_state(_DAY)
        state = mark_phase_fired(state, Phase.STOP_PRIOR, _utc(16, 40))
        state = mark_phase_fired(state, Phase.LAUNCH, _utc(16, 50))
        state = record_readiness_observed(state, _utc(16, 52))
        state = mark_phase_fired(state, Phase.SELF_CHECK, _utc(17, 5))
        phase, fire_at = next_due(_utc(23, 50), state)
        assert phase is Phase.NONE
        assert fire_at == _utc(16, 40, day=_DAY + dt.timedelta(days=1))

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
