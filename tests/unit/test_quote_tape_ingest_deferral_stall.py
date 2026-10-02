"""RED-first tests wiring the EDGE-6 6f deferral-stall streak into
`quote_tape_ingest_cli` -- `EXIT_DEFERRAL_STALLED`, `_instance_has_pending_work`
(AC-6f-5), `_count_pending_deferral_units` (AM-1/AM-2), and the exit-3
interaction (AC-6f-4/C-5).

Plan: `docs/plans/backlog/EDGE_2026-09-27/EDGE-6_ops_reliability_plan_r2_2026-09-27.md`,
r2 final amendment, §1 6f, §2.6, §3 6f, §4 6f, §6 6f.

The pure state-machine cadence (crossing, 16-run re-alert, reset) is
covered in `test_ingest_deferral_streak.py`; this module only pins the
CLI-level wiring: what counts as "pending" (AM-1/AM-2/AC-6f-5), the exit
code and precedence, and the printed line / file-location / dry-run /
corrupt-file contracts.
"""

from __future__ import annotations

import io
import logging
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from nautilus_trader.model.data import QuoteTick

import breezy.runtime.quote_tape_ingest_core as ingest_core_module
from breezy.runtime.ingest_deferral_streak import (
    STATE_FILENAME,
    DeferralStreakState,
    load_state,
    save_state,
)
from breezy.runtime.quote_tape_ingest_cli import (
    DEFAULT_DATA_TYPES,
    DEFAULT_LIVE_GRACE_MINUTES,
    EXIT_CONVERSION_FAILED,
    EXIT_DEFERRAL_STALLED,
    EXIT_OK,
    FILE_MARKER_PREFIX,
    MARKER_PREFIX,
    InstanceIngestResult,
    TypeConversionResult,
    _count_pending_deferral_units,
    _instance_dir,
    _instance_has_pending_work,
    run,
)
from breezy.runtime.quote_tape_salvage import (
    SALVAGE_MARKER_PREFIX,
    SALVAGE_UNSUPPORTED_PREFIX,
)
from tests.unit.test_quote_tape_ingest_cli import (
    INSTANCE,
    _never_active,
    _quote_tick,
    _touch,
    _write_typed_ipc_stream,
)

_INACTIVE_SERVICE_UNIT = "definitely-not-a-real-unit.service"


class _TickingClock:
    """Same shape as `test_quote_tape_ingest_deadline.py`'s own helper: a
    monotonic-ns clock that advances on every read, so a tiny
    `--deadline-seconds` budget is already exhausted by the first check.
    """

    def __init__(self, step_ns: int) -> None:
        self._value = 0
        self._step = step_ns

    def __call__(self) -> int:
        self._value += self._step
        return self._value


def _run_cli(argv: list[str], **kwargs: object) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = run(argv, stdout=out, stderr=err, **kwargs)  # type: ignore[arg-type]
    return code, out.getvalue(), err.getvalue()


def _tiny_deadline_argv(tmp_path: Path) -> list[str]:
    """`--deadline-seconds 1` plus an inactive service unit, paired with
    `_TickingClock(step_ns=2_000_000_000)` to reliably exhaust the budget
    on the very first loop-top check (mirrors
    `test_quote_tape_ingest_deadline.py`'s own proven fixture)."""
    return [
        "--catalog",
        str(tmp_path),
        "--deadline-seconds",
        "1",
        "--service-unit",
        _INACTIVE_SERVICE_UNIT,
    ]


# ---------------------------------------------------------------------------
# AC-6f-5: `_instance_has_pending_work` is marker-aware, not just blanket-
# marker-aware -- the 7f353f94 shape (plan §2.2.1) must never count.
# ---------------------------------------------------------------------------


class TestInstanceHasPendingWork:
    def test_not_evaluated_per_file_and_salvage_marked_instance_never_counts(
        self, tmp_path: Path
    ) -> None:
        """Mirrors the 7f353f94 marker layout: one blanket-marked type, the
        rest per-file- or salvage-marked, one terminal salvage-unsupported
        marker. Nothing here may ever count as pending (R6)."""
        instance_dir = _instance_dir(tmp_path, INSTANCE, "live")
        instance_dir.mkdir(parents=True)

        per_file = instance_dir / "quote_tick_0.feather"
        per_file.touch()
        (instance_dir / f"{FILE_MARKER_PREFIX}quote_tick_0.feather").touch()

        salvaged = instance_dir / "trade_tick_0.feather"
        salvaged.touch()
        (instance_dir / f"{SALVAGE_MARKER_PREFIX}trade_tick_0.feather").touch()

        unsupported = instance_dir / "order_book_depths_0.feather"
        unsupported.touch()
        (instance_dir / f"{SALVAGE_UNSUPPORTED_PREFIX}order_book_depths_0.feather").touch()

        # The blanket marker itself, for a type with no feather file left
        # unaccounted for.
        (instance_dir / f"{MARKER_PREFIX}binary_option").touch()

        assert _instance_has_pending_work(instance_dir, frozenset()) is False

    def test_not_evaluated_fully_converted_instance_never_counts(self, tmp_path: Path) -> None:
        instance_dir = _instance_dir(tmp_path, INSTANCE, "live")
        instance_dir.mkdir(parents=True)
        (instance_dir / "quote_tick_0.feather").touch()
        (instance_dir / f"{MARKER_PREFIX}quote_tick").touch()

        assert _instance_has_pending_work(instance_dir, frozenset()) is False

    def test_not_evaluated_instance_with_unmarked_closed_file_counts(self, tmp_path: Path) -> None:
        instance_dir = _instance_dir(tmp_path, INSTANCE, "live")
        instance_dir.mkdir(parents=True)
        (instance_dir / "quote_tick_0.feather").touch()

        assert _instance_has_pending_work(instance_dir, frozenset()) is True

    def test_an_open_unmarked_file_never_counts(self, tmp_path: Path) -> None:
        instance_dir = _instance_dir(tmp_path, INSTANCE, "live")
        instance_dir.mkdir(parents=True)
        path = instance_dir / "quote_tick_0.feather"
        path.touch()

        assert _instance_has_pending_work(instance_dir, frozenset({path})) is False


# ---------------------------------------------------------------------------
# AM-1 / AM-2: `_count_pending_deferral_units` reads `salvage_deferred`
# directly (never the outcome string) and calls `_open_files_for_instance`
# itself for a "not evaluated" instance.
# ---------------------------------------------------------------------------


class TestCountPendingDeferralUnits:
    def _probe(self, results, catalog_root: Path) -> int:
        return _count_pending_deferral_units(
            results,
            catalog_root,
            "live",
            DEFAULT_DATA_TYPES,
            now_ns=None,
            grace_minutes=30.0,
            service_active_probe=_never_active,
        )

    def test_a_per_type_deferred_deadline_outcome_counts(self, tmp_path: Path) -> None:
        results = (
            InstanceIngestResult(
                "instance-a",
                "converted",
                type_results=(TypeConversionResult(object, "deferred-deadline"),),
            ),
        )
        assert self._probe(results, tmp_path) == 1

    def test_salvage_deferred_counts_pending(self, tmp_path: Path) -> None:
        """AM-2: a salvage-deferred instance's OUTCOME is "skipped-truncated"
        (unresolved truncation always wins the outcome, see
        `_ingest_instance_per_file`) -- never "deferred-deadline". A count
        that reads `result.outcome` instead of `result.salvage_deferred`
        would silently miss this and never alert on a real, live-observed
        stall shape."""
        results = (
            InstanceIngestResult(
                "instance-a",
                "skipped-truncated",
                reason="1 truncated, 0 unreadable file(s)",
                type_results=(),
                salvage_deferred=True,
            ),
        )
        assert self._probe(results, tmp_path) == 1

    def test_a_plain_skip_with_no_deferral_never_counts(self, tmp_path: Path) -> None:
        results = (
            InstanceIngestResult("instance-a", "skipped-live", reason="live"),
            InstanceIngestResult("instance-a", "converted"),
        )
        assert self._probe(results, tmp_path) == 0

    def test_not_evaluated_instance_calls_open_files_for_instance_itself(
        self, tmp_path: Path
    ) -> None:
        """AM-1: a "not evaluated" instance never had `open_files` computed
        (the loop-top deadline peek defers it before that), so the pending
        count must derive it fresh -- proven here by an UNMARKED closed
        file counting as pending with zero extra setup beyond the instance
        directory itself."""
        _touch(tmp_path, INSTANCE, "quote_tick_0.feather", age_minutes=60)
        results = (InstanceIngestResult(INSTANCE, "deferred-deadline", reason="not evaluated"),)
        assert self._probe(results, tmp_path) == 1

    def test_not_evaluated_but_marker_complete_instance_never_counts(self, tmp_path: Path) -> None:
        """The AC-6f-5 marker-aware predicate applies here too: a
        "not evaluated" instance whose only file is already blanket-marked
        must not count, even though it was never given `open_files`
        directly by `run_ingest`."""
        instance_dir = _instance_dir(tmp_path, INSTANCE, "live")
        instance_dir.mkdir(parents=True)
        (instance_dir / "quote_tick_0.feather").touch()
        (instance_dir / f"{MARKER_PREFIX}quote_tick").touch()
        results = (InstanceIngestResult(INSTANCE, "deferred-deadline", reason="not evaluated"),)
        assert self._probe(results, tmp_path) == 0


# ---------------------------------------------------------------------------
# CLI wiring: exit code, the streak file, the printed line.
# ---------------------------------------------------------------------------


class TestStreakFileAndDryRun:
    def test_streak_file_lives_at_catalog_root_not_live(self, tmp_path: Path) -> None:
        _touch(tmp_path, INSTANCE, "quote_tick_0.feather", age_minutes=60)
        _code, _out, _err = _run_cli(
            _tiny_deadline_argv(tmp_path),
            clock_ns=_TickingClock(step_ns=2_000_000_000),
        )
        streak_path = tmp_path / STATE_FILENAME
        assert streak_path.is_file()
        assert streak_path.parent == tmp_path
        assert not (tmp_path / "live" / STATE_FILENAME).exists()

    def test_dry_run_never_touches_streak_file(self, tmp_path: Path) -> None:
        _touch(tmp_path, INSTANCE, "quote_tick_0.feather", age_minutes=60)
        code, _out, _err = _run_cli(
            ["--catalog", str(tmp_path), "--dry-run", "--service-unit", _INACTIVE_SERVICE_UNIT],
        )
        assert code == EXIT_OK
        assert not (tmp_path / STATE_FILENAME).exists()

    def test_streak_below_threshold_exits_zero(self, tmp_path: Path) -> None:
        _touch(tmp_path, INSTANCE, "quote_tick_0.feather", age_minutes=60)
        code, out, _err = _run_cli(
            _tiny_deadline_argv(tmp_path),
            clock_ns=_TickingClock(step_ns=2_000_000_000),
        )
        assert code == EXIT_OK
        assert "DEFERRAL_STALLED" not in out
        state = load_state(tmp_path / STATE_FILENAME)
        assert state.consecutive_runs == 1

    def test_corrupt_streak_file_resets_and_warns(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        (tmp_path / STATE_FILENAME).write_text("{not json")
        _touch(tmp_path, INSTANCE, "quote_tick_0.feather", age_minutes=60)
        with caplog.at_level(logging.WARNING, logger="breezy.runtime.ingest_deferral_streak"):
            code, _out, _err = _run_cli(
                _tiny_deadline_argv(tmp_path),
                clock_ns=_TickingClock(step_ns=2_000_000_000),
            )
        assert code == EXIT_OK
        assert any("corrupt" in r.message.lower() for r in caplog.records)
        # A fresh streak starts counting from THIS run, not a poisoned value.
        state = load_state(tmp_path / STATE_FILENAME)
        assert state.consecutive_runs == 1


class TestFourthConsecutiveDeferralExitsFour:
    def test_fourth_consecutive_pending_deferral_after_60min_exits_4(self, tmp_path: Path) -> None:
        _touch(tmp_path, INSTANCE, "quote_tick_0.feather", age_minutes=60)
        base_ns = time.time_ns()
        codes = []
        for i in range(4):
            code, out, _err = _run_cli(
                _tiny_deadline_argv(tmp_path),
                clock_ns=_TickingClock(step_ns=2_000_000_000),
                now_ns=base_ns + i * 20 * 60 * 1_000_000_000,
            )
            codes.append(code)
        assert codes[:3] == [EXIT_OK, EXIT_OK, EXIT_OK]
        assert codes[3] == EXIT_DEFERRAL_STALLED
        assert "DEFERRAL_STALLED runs=4" in out
        assert "age_s=3600" in out

    def test_stall_line_is_value_free(self, tmp_path: Path) -> None:
        """No instrument id, price, or other market-sensitive value -- only
        counts, matching every other outcome/summary line in this module."""
        _touch(tmp_path, INSTANCE, "quote_tick_0.feather", age_minutes=60)
        base_ns = time.time_ns()
        out = ""
        for i in range(4):
            _, out, _err = _run_cli(
                _tiny_deadline_argv(tmp_path),
                clock_ns=_TickingClock(step_ns=2_000_000_000),
                now_ns=base_ns + i * 20 * 60 * 1_000_000_000,
            )
        line = next(line for line in out.splitlines() if "DEFERRAL_STALLED" in line)
        assert line == (
            f"breezy-quote-tape-ingest: DEFERRAL_STALLED runs=4 age_s=3600 "
            f"pending_units={line.rsplit('pending_units=', 1)[1]}"
        )
        # Every token is `key=digits`; no instrument-id-shaped or
        # price-shaped token (a dot or a letter outside the keys) appears.
        tail = line.split("DEFERRAL_STALLED ", 1)[1]
        for token in tail.split():
            key, _, value = token.partition("=")
            assert key in {"runs", "age_s", "pending_units"}
            assert value.isdigit()


class TestStreakResets:
    def test_streak_resets_on_a_run_with_no_pending_deferral(self, tmp_path: Path) -> None:
        save_state(
            tmp_path / STATE_FILENAME,
            DeferralStreakState(
                consecutive_runs=10,
                first_deferred_utc=(datetime.now(UTC) - timedelta(hours=3)).isoformat(),
                runs_since_alert=5,
            ),
        )
        # A dead instance already fully converted: nothing pending this run.
        instance_dir = _instance_dir(tmp_path, INSTANCE, "live")
        instance_dir.mkdir(parents=True)
        (instance_dir / "quote_tick_0.feather").touch()
        (instance_dir / f"{MARKER_PREFIX}quote_tick").touch()
        for data_cls in DEFAULT_DATA_TYPES:
            (instance_dir / f"{MARKER_PREFIX}{data_cls.__name__}").touch()

        code, _out, _err = _run_cli(
            ["--catalog", str(tmp_path), "--service-unit", _INACTIVE_SERVICE_UNIT],
        )
        assert code == EXIT_OK
        state = load_state(tmp_path / STATE_FILENAME)
        assert state.consecutive_runs == 0
        assert state.first_deferred_utc is None


# ---------------------------------------------------------------------------
# AC-6f-4 / C-5: exit precedence when a conversion failure and a stall
# alert land on the SAME run. `_count_pending_deferral_units` is mocked
# here to isolate the precedence logic itself from how "pending" gets
# computed (covered exhaustively above) -- the real `step()`/save path
# still runs.
# ---------------------------------------------------------------------------


def _seed_almost_due_streak(tmp_path: Path, *, runs_since_alert: int) -> None:
    save_state(
        tmp_path / STATE_FILENAME,
        DeferralStreakState(
            consecutive_runs=20,
            first_deferred_utc=(datetime.now(UTC) - timedelta(hours=5)).isoformat(),
            runs_since_alert=runs_since_alert,
        ),
    )


def _seed_failing_instance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The exact fixture `test_a_failed_outcome_exits_conversion_failed`
    uses: an open sibling file forces the per-file path, and the patched
    reader turns the closed file's read into a hard per-file failure."""
    instance_dir = tmp_path / "live" / INSTANCE
    quote_path = instance_dir / "quote_tick_0.feather"
    open_path = instance_dir / "quote_tick_1.feather"
    _write_typed_ipc_stream(quote_path, [_quote_tick(i) for i in range(10)], QuoteTick, close=True)
    _write_typed_ipc_stream(
        open_path, [_quote_tick(100 + i) for i in range(5)], QuoteTick, close=False
    )
    stamp = time.time() - (DEFAULT_LIVE_GRACE_MINUTES + 5) * 60
    os.utime(quote_path, (stamp, stamp))
    monkeypatch.setattr(ingest_core_module, "read_feather_coalesced", lambda fs, path, **kw: None)


class TestExitPrecedenceWithAConversionFailure:
    def test_exit3_run_with_pending_increments_streak(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_failing_instance(tmp_path, monkeypatch)
        _seed_almost_due_streak(tmp_path, runs_since_alert=5)
        monkeypatch.setattr(ingest_core_module, "_count_pending_deferral_units", lambda *a, **kw: 3)

        code, _out, _err = _run_cli(
            ["--catalog", str(tmp_path), "--service-unit", _INACTIVE_SERVICE_UNIT],
        )

        assert code == EXIT_CONVERSION_FAILED
        state = load_state(tmp_path / STATE_FILENAME)
        assert state.consecutive_runs == 21  # incremented despite the exit-3

    def test_exit3_run_with_due_stall_prints_line_and_exits_3(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_failing_instance(tmp_path, monkeypatch)
        _seed_almost_due_streak(tmp_path, runs_since_alert=15)  # one more run is due
        monkeypatch.setattr(ingest_core_module, "_count_pending_deferral_units", lambda *a, **kw: 2)

        code, out, _err = _run_cli(
            ["--catalog", str(tmp_path), "--service-unit", _INACTIVE_SERVICE_UNIT],
        )

        # (ii): exit is still 3 (failure beats stall), but the stall line
        # still prints in THIS invocation's own journal.
        assert code == EXIT_CONVERSION_FAILED
        assert "DEFERRAL_STALLED" in out
        state = load_state(tmp_path / STATE_FILENAME)
        assert state.runs_since_alert == 0  # reset by the alert firing

    def test_exit3_run_not_due_increments_runs_since_alert(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_failing_instance(tmp_path, monkeypatch)
        _seed_almost_due_streak(tmp_path, runs_since_alert=5)
        monkeypatch.setattr(ingest_core_module, "_count_pending_deferral_units", lambda *a, **kw: 1)

        code, out, _err = _run_cli(
            ["--catalog", str(tmp_path), "--service-unit", _INACTIVE_SERVICE_UNIT],
        )

        assert code == EXIT_CONVERSION_FAILED
        assert "DEFERRAL_STALLED" not in out
        state = load_state(tmp_path / STATE_FILENAME)
        assert state.runs_since_alert == 6

    def test_exit3_run_without_pending_resets_streak(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_failing_instance(tmp_path, monkeypatch)
        _seed_almost_due_streak(tmp_path, runs_since_alert=15)
        monkeypatch.setattr(ingest_core_module, "_count_pending_deferral_units", lambda *a, **kw: 0)

        code, out, _err = _run_cli(
            ["--catalog", str(tmp_path), "--service-unit", _INACTIVE_SERVICE_UNIT],
        )

        assert code == EXIT_CONVERSION_FAILED
        assert "DEFERRAL_STALLED" not in out
        state = load_state(tmp_path / STATE_FILENAME)
        assert state.consecutive_runs == 0
        assert state.first_deferred_utc is None
