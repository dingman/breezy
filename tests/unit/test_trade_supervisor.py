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
    NODE_CONSOLE_SCRIPT,
    ExecStateDbNotConfiguredError,
    count_lock_holders,
    hold_supervisor_lock,
    intent_lock_is_free,
    intent_lock_path,
    log_decision,
    main,
    node_log_path,
    probe_open_intent,
    resolve_lock_holder_pid,
    resolve_store_path,
    spawn_node,
    supervisor_lock_path,
    terminate,
)
from breezy.runtime.trade_supervisor_core import (
    MAX_RELAUNCH_ATTEMPTS,
    MIN_RELAUNCH_GAP,
    RELAUNCH_CUTOFF_UTC,
    SUPERVISOR_ARGV_TOKEN,
    AlertDetail,
    ExitConfigErrorCause,
    LaunchAction,
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
    readiness_observed,
    self_check,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

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


def test_resolve_store_path_requires_the_env_var(monkeypatch):
    monkeypatch.delenv(EXEC_STATE_DB_ENV_VAR, raising=False)
    with pytest.raises(ExecStateDbNotConfiguredError):
        resolve_store_path({})


def test_resolve_store_path_reads_the_configured_path():
    path = resolve_store_path({EXEC_STATE_DB_ENV_VAR: "/tmp/x/store.sqlite3"})
    assert path == Path("/tmp/x/store.sqlite3")


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
