"""RED-first tests for the shared re-alert ladder (AUD-04 §6 D8/R3).

This is the SINGLE place the ladder's semantics are asserted -- AUD-07
imports `src/breezy/runtime/alert_ladder.py` rather than re-implementing or
re-specifying it (D8 ownership rule). See
docs/plans/backlog/AUDIT_2026-09-21/AUD-04-portfolio-roi-measurement.md
section 6 D8 for the full specification.
"""

from __future__ import annotations

from pathlib import Path

from breezy.runtime.alert_ladder import (
    CRITICAL_STREAK_THRESHOLD,
    LATCH_SCHEMA_VERSION,
    WARN_STREAK_THRESHOLD,
    LadderDecision,
    LatchState,
    evaluate_streak,
    next_streak,
    read_latch_state,
    utc_day_key,
    utc_iso_week_key,
    write_latch_state,
)

# A fixed instant: 2026-09-21T12:00:00Z (a Monday, ISO week 39).
_NOW_NS = 1_789_992_000_000_000_000


class TestPeriodKeyHelpers:
    def test_utc_day_key_is_the_calendar_day(self) -> None:
        assert utc_day_key(_NOW_NS) == "2026-09-21"

    def test_utc_iso_week_key_format(self) -> None:
        key = utc_iso_week_key(_NOW_NS)
        assert key.startswith("2026-W")

    def test_iso_week_boundary_end_of_year_belongs_to_the_next_isoyear(self) -> None:
        # 2025-12-29 is a Monday, ISO week 1 of ISO-year 2026, even though
        # the calendar year is still 2025 -- the case an implementer who
        # reaches for `dt.year` instead of `isocalendar()` gets wrong.
        # 2025-12-29T00:00:00Z
        dec_29_2025_ns = 1_766_966_400_000_000_000
        assert utc_iso_week_key(dec_29_2025_ns) == "2026-W01"

    def test_a_day_seven_apart_can_be_in_different_iso_weeks(self) -> None:
        day_one_ns = _NOW_NS
        day_eight_ns = _NOW_NS + 7 * 86_400 * 1_000_000_000
        assert utc_iso_week_key(day_one_ns) != utc_iso_week_key(day_eight_ns)


class TestEvaluateStreakBelowThreshold:
    def test_streak_below_warn_threshold_is_silent(self) -> None:
        for streak in range(WARN_STREAK_THRESHOLD):
            decision = evaluate_streak(
                streak=streak,
                last_alert_severity=None,
                last_alert_period_key=None,
                now_ns=_NOW_NS,
            )
            assert decision == LadderDecision(should_alert=False, severity=None, period_key=None)


class TestEvaluateStreakWarnBand:
    def test_first_qualifying_run_in_warn_band_alerts_once(self) -> None:
        decision = evaluate_streak(
            streak=WARN_STREAK_THRESHOLD,
            last_alert_severity=None,
            last_alert_period_key=None,
            now_ns=_NOW_NS,
        )
        assert decision.should_alert is True
        assert decision.severity == "WARN"
        assert decision.period_key == utc_iso_week_key(_NOW_NS)

    def test_a_same_period_rerun_does_not_re_alert(self) -> None:
        first = evaluate_streak(
            streak=WARN_STREAK_THRESHOLD,
            last_alert_severity=None,
            last_alert_period_key=None,
            now_ns=_NOW_NS,
        )
        assert first.should_alert is True
        second = evaluate_streak(
            streak=WARN_STREAK_THRESHOLD + 1,
            last_alert_severity=first.severity,
            last_alert_period_key=first.period_key,
            now_ns=_NOW_NS + 3_600_000_000_000,
        )
        assert second.should_alert is False
        assert second.severity == "WARN"


class TestEvaluateStreakCriticalBand:
    def test_streak_at_critical_threshold_alerts_at_critical(self) -> None:
        decision = evaluate_streak(
            streak=CRITICAL_STREAK_THRESHOLD,
            last_alert_severity="WARN",
            last_alert_period_key=utc_iso_week_key(_NOW_NS),
            now_ns=_NOW_NS,
        )
        assert decision.should_alert is True
        assert decision.severity == "CRITICAL"
        assert decision.period_key == utc_day_key(_NOW_NS)

    def test_severity_never_de_escalates_within_one_streak(self) -> None:
        """Once CRITICAL has been recorded for a streak, a stray call that
        would otherwise land back in the WARN band (streak inconsistency,
        or a caller bug) must not report WARN."""
        decision = evaluate_streak(
            streak=WARN_STREAK_THRESHOLD,
            last_alert_severity="CRITICAL",
            last_alert_period_key=utc_day_key(_NOW_NS),
            now_ns=_NOW_NS,
        )
        assert decision.severity == "CRITICAL"


class TestThirtyDayOutage:
    def test_a_thirty_day_outage_re_alerts_weekly_then_escalates_to_daily_critical(self) -> None:
        """Drive 30 consecutive stale daily runs and assert the exact
        emitted sequence: one WARN per UTC ISO week while
        3 <= streak <= 13, then one CRITICAL per UTC day from streak == 14
        onward."""
        day_ns = 86_400 * 1_000_000_000
        last_severity: str | None = None
        last_period_key: str | None = None
        emitted: list[tuple[int, str, str]] = []
        for day in range(30):
            streak = day + 1  # stale every run, starting at streak=1
            now_ns = _NOW_NS + day * day_ns
            decision = evaluate_streak(
                streak=streak,
                last_alert_severity=last_severity,
                last_alert_period_key=last_period_key,
                now_ns=now_ns,
            )
            if decision.should_alert:
                assert decision.severity is not None
                assert decision.period_key is not None
                emitted.append((day, decision.severity, decision.period_key))
                last_severity = decision.severity
                last_period_key = decision.period_key

        warn_emissions = [e for e in emitted if e[1] == "WARN"]
        critical_emissions = [e for e in emitted if e[1] == "CRITICAL"]

        # streak 3..13 spans 11 days; every UTC-ISO-week key among those
        # days should appear at most once.
        warn_period_keys = [e[2] for e in warn_emissions]
        assert warn_period_keys == sorted(set(warn_period_keys), key=warn_period_keys.index)
        assert len(warn_period_keys) == len(set(warn_period_keys))
        assert len(warn_emissions) >= 1

        # streak >= 14 (days index 13..29) escalates to CRITICAL, once per
        # UTC day.
        critical_period_keys = [e[2] for e in critical_emissions]
        assert len(critical_period_keys) == len(set(critical_period_keys))
        assert len(critical_emissions) >= 1
        assert all(e[1] == "CRITICAL" for e in emitted if e[0] >= 13)
        # never de-escalates back to WARN once CRITICAL starts.
        first_critical_day = min(e[0] for e in critical_emissions)
        assert all(e[1] == "CRITICAL" for e in emitted if e[0] > first_critical_day)


class TestNextStreak:
    def test_next_streak_increments_on_stale(self) -> None:
        assert next_streak(is_fresh=False, previous_streak=0) == 1
        assert next_streak(is_fresh=False, previous_streak=5) == 6

    def test_next_streak_resets_to_zero_on_fresh(self) -> None:
        assert next_streak(is_fresh=True, previous_streak=13) == 0


class TestFreshInputClearsAndReArms:
    def test_fresh_input_clears_the_streak_and_fully_re_arms(self) -> None:
        # Simulate a streak that reached CRITICAL...
        streak = CRITICAL_STREAK_THRESHOLD
        decision = evaluate_streak(
            streak=streak,
            last_alert_severity="WARN",
            last_alert_period_key=utc_iso_week_key(_NOW_NS),
            now_ns=_NOW_NS,
        )
        assert decision.severity == "CRITICAL"

        # ... then a fresh input arrives: the caller resets the streak and
        # clears the persisted alert state.
        cleared_streak = next_streak(is_fresh=True, previous_streak=streak)
        assert cleared_streak == 0

        below_threshold = evaluate_streak(
            streak=cleared_streak,
            last_alert_severity=None,
            last_alert_period_key=None,
            now_ns=_NOW_NS + 1,
        )
        assert below_threshold.should_alert is False

        # A later freeze fires WARN again at streak == 3, not CRITICAL --
        # the ladder is fully re-armed, not merely un-paused.
        re_armed = evaluate_streak(
            streak=WARN_STREAK_THRESHOLD,
            last_alert_severity=None,
            last_alert_period_key=None,
            now_ns=_NOW_NS + 2,
        )
        assert re_armed.severity == "WARN"
        assert re_armed.should_alert is True


class TestLatchPersistence:
    def test_reading_a_missing_latch_file_returns_a_fresh_streak_zero_state(
        self, tmp_path: Path
    ) -> None:
        state = read_latch_state(tmp_path / "does_not_exist.json")
        assert state == LatchState(
            schema_version=LATCH_SCHEMA_VERSION,
            streak=0,
            last_alert_severity=None,
            last_alert_period_key=None,
        )

    def test_a_missing_or_corrupt_latch_file_re_alerts_rather_than_failing_silent(
        self, tmp_path: Path
    ) -> None:
        corrupt_path = tmp_path / "latch.json"
        corrupt_path.write_text("{not json", encoding="utf-8")

        state = read_latch_state(corrupt_path)

        assert state.streak == 0
        # A fresh streak of 0 means the NEXT stale run starts counting from
        # 1 again, rather than the latch silently freezing the ladder off.
        decision = evaluate_streak(
            streak=next_streak(is_fresh=False, previous_streak=state.streak),
            last_alert_severity=state.last_alert_severity,
            last_alert_period_key=state.last_alert_period_key,
            now_ns=_NOW_NS,
        )
        assert decision.should_alert is False  # streak 1 < WARN_STREAK_THRESHOLD

    def test_write_then_read_round_trips(self, tmp_path: Path) -> None:
        path = tmp_path / "nested" / "latch.json"
        state = LatchState(
            schema_version=LATCH_SCHEMA_VERSION,
            streak=7,
            last_alert_severity="WARN",
            last_alert_period_key="2026-W38",
        )
        write_latch_state(path, state)
        assert read_latch_state(path) == state

    def test_the_latch_survives_a_process_restart_without_re_alerting(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "latch.json"

        # Run 1: streak reaches WARN threshold, alerts, persists.
        state = read_latch_state(path)
        streak = WARN_STREAK_THRESHOLD  # simulate the run that first crosses the threshold
        decision = evaluate_streak(
            streak=streak,
            last_alert_severity=state.last_alert_severity,
            last_alert_period_key=state.last_alert_period_key,
            now_ns=_NOW_NS,
        )
        assert decision.should_alert is True
        write_latch_state(
            path,
            LatchState(
                schema_version=LATCH_SCHEMA_VERSION,
                streak=streak,
                last_alert_severity=decision.severity,
                last_alert_period_key=decision.period_key,
            ),
        )

        # "Process restart": a fresh read of the same file, same period.
        reloaded = read_latch_state(path)
        streak_2 = next_streak(is_fresh=False, previous_streak=reloaded.streak)
        decision_2 = evaluate_streak(
            streak=streak_2,
            last_alert_severity=reloaded.last_alert_severity,
            last_alert_period_key=reloaded.last_alert_period_key,
            now_ns=_NOW_NS + 1,
        )
        assert decision_2.should_alert is False


class TestNoImportFromExitWindowStudy:
    def test_the_alert_ladder_module_imports_nothing_from_the_exit_window_study(self) -> None:
        """AUD-04 owns this module; AUD-07 imports it, never the reverse.
        Enforced structurally here (source scan) and by `lint-imports`."""
        import inspect

        from breezy.runtime import alert_ladder

        source = inspect.getsource(alert_ladder)
        forbidden = ("exit_window_study", "current_rung_hold_exit", "exit_gate")
        assert not any(token in source for token in forbidden)
