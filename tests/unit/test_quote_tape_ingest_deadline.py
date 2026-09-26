"""ING-2 S2: a per-run wall-clock deadline for `quote_tape_ingest_cli`.

Plan: `docs/plans/backlog/ING-2_2026-09-25/ING-2_S2_plan_r2.md` +
`ING-2_S2_plan_r3_amendment.md` (r3/r3.1 wins on conflict).

One native conversion unit (a whole-feather read, or a per-type/per-file
conversion) can run long enough to overrun the WHOLE unit's
`TimeoutStartSec`, taking every OTHER instance down with it (S1 residual
R1). `RunDeadline` bounds how many NEW conversion units a single run may
START -- Nautilus Trader's own conversion call is never touched.

AC-D10 is pinned by the UNCHANGED existing ingest test modules (all pass
with `deadline` defaulting to `None` everywhere) plus
`TestDeadlineNoneIsByteIdentical` below.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from nautilus_trader.model.data import QuoteTick, TradeTick
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

import breezy.runtime.quote_tape_ingest_cli as ingest_cli_module
from breezy.runtime.ingest_deadline import (
    DEFAULT_DEADLINE_SECONDS,
    DEFERRED_DEADLINE,
    RunDeadline,
    count_deferred,
)
from breezy.runtime.quote_tape_ingest_cli import (
    ATTEMPT_PREFIX,
    EXIT_CONVERSION_FAILED,
    EXIT_USAGE,
    InstanceIngestResult,
    TypeConversionResult,
    _instance_is_poisoned,
    _merge_pass_results,
    _poison_first_order,
    run,
    run_ingest,
    run_ingest_definitions_first,
)
from tests.unit.test_quote_tape_ingest_cli import (
    INSTANCE,
    OTHER_INSTANCE,
    _never_active,
    _quote_tick,
    _touch,
    _truncate_tail,
    _write_typed_ipc_stream,
)

#: `default_service_active_probe` fails CLOSED (reports "live") when
#: `systemctl --user` cannot answer at all, which this sandboxed dev host
#: hits for the real recorder unit name -- naming an unrelated, definitely
#: absent unit gets a clean, real "inactive" answer instead (verified: a
#: process that runs and returns non-"active" stdout, not an OSError).
_INACTIVE_SERVICE_UNIT = "definitely-not-a-real-unit.service"


class FakeClock:
    """A monotonic-ns clock a test can advance by hand."""

    def __init__(self, start_ns: int = 0) -> None:
        self._now = start_ns

    def __call__(self) -> int:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += int(seconds * 1_000_000_000)


class _TickingClock:
    """A monotonic-ns clock whose value advances by ``step_ns`` on EVERY
    read (including `RunDeadline`'s own start-time read). Used to land a
    budget crossing precisely between two specific gate checks without
    hand-simulating how much real work happened in between.
    """

    def __init__(self, step_ns: int) -> None:
        self._value = 0
        self._step = step_ns

    def __call__(self) -> int:
        self._value += self._step
        return self._value


# ---------------------------------------------------------------------------
# RunDeadline in isolation.
# ---------------------------------------------------------------------------


class TestRunDeadlineUnit:
    def test_first_admit_is_the_guarantee_even_when_already_expired(self) -> None:
        clock = FakeClock()
        deadline = RunDeadline(budget_ns=1, clock_ns=clock)
        clock.advance(10)
        assert deadline.admit() is True
        assert deadline.admitted == 1

    def test_after_the_guarantee_admit_follows_the_budget(self) -> None:
        clock = FakeClock()
        deadline = RunDeadline(budget_ns=5_000_000_000, clock_ns=clock)
        assert deadline.admit() is True  # the guarantee
        clock.advance(1)
        assert deadline.admit() is True  # still within budget
        clock.advance(10)
        assert deadline.admit() is False  # expired

    def test_the_first_false_is_sticky_forever(self) -> None:
        clock = FakeClock()
        deadline = RunDeadline(budget_ns=1, clock_ns=clock)
        assert deadline.admit() is True
        clock.advance(10)
        assert deadline.admit() is False
        clock.advance(-10)  # a clock quirk must never un-close a closed deadline
        assert deadline.admit() is False
        assert deadline.can_admit() is False
        assert deadline.admitted == 1

    def test_can_admit_tolerates_exactly_one_no_work_scan_past_expiry(self) -> None:
        clock = FakeClock()
        deadline = RunDeadline(budget_ns=1, clock_ns=clock)
        clock.advance(10)  # expired before the guarantee was ever used
        assert deadline.can_admit() is True
        deadline.note_scan()
        assert deadline.can_admit() is False
        assert deadline.admitted == 0

    def test_note_scan_never_consumes_the_guarantee(self) -> None:
        clock = FakeClock()
        deadline = RunDeadline(budget_ns=1, clock_ns=clock)
        clock.advance(10)
        deadline.can_admit()
        deadline.note_scan()
        assert deadline.admit() is True  # the guarantee is still there

    def test_default_clock_is_the_wall_monotonic_clock(self) -> None:
        deadline = RunDeadline(budget_ns=1)
        assert deadline.admit() is True


class TestCountDeferred:
    def test_counts_deferred_type_results_and_distinct_not_evaluated_instances(self) -> None:
        results = (
            InstanceIngestResult(
                INSTANCE,
                "converted",
                type_results=(TypeConversionResult(QuoteTick, DEFERRED_DEADLINE),),
            ),
            InstanceIngestResult(OTHER_INSTANCE, DEFERRED_DEADLINE, "not evaluated"),
        )
        units, instances = count_deferred(results)
        assert units == 1
        assert instances == 1

    def test_a_salvage_deferred_row_counts_as_one_unit(self) -> None:
        results = (
            InstanceIngestResult(INSTANCE, "skipped-truncated", "boom", salvage_deferred=True),
        )
        units, instances = count_deferred(results)
        assert units == 1
        assert instances == 0

    def test_the_same_instance_deferred_in_both_passes_is_not_double_counted(self) -> None:
        results = (
            InstanceIngestResult(INSTANCE, DEFERRED_DEADLINE, "not evaluated"),
            InstanceIngestResult(INSTANCE, DEFERRED_DEADLINE, "not evaluated"),
        )
        _, instances = count_deferred(results)
        assert instances == 1


# ---------------------------------------------------------------------------
# The loop-top gate (`run_ingest`).
# ---------------------------------------------------------------------------


class TestLoopTopGate:
    def test_a_second_instance_is_deferred_at_loop_top_once_the_budget_is_spent(
        self, tmp_path: Path
    ) -> None:
        for instance in (INSTANCE, OTHER_INSTANCE):
            _touch(tmp_path, instance, "quote_tick_0.feather", age_minutes=60)
        clock = FakeClock()
        calls: list[str] = []

        def slow_convert(catalog, instance_id, data_cls, subdirectory):  # type: ignore[no-untyped-def]
            calls.append(instance_id)
            clock.advance(1000)

        deadline = RunDeadline(budget_ns=1, clock_ns=clock)  # guarantee-only budget

        results = run_ingest(
            tmp_path,
            data_types=(QuoteTick,),
            service_active_probe=_never_active,
            convert_fn=slow_convert,
            deadline=deadline,
        )

        by_id = {r.instance_id: r for r in results}
        assert len(calls) == 1
        assert by_id[calls[0]].outcome == "converted"
        deferred_id = next(iid for iid in (INSTANCE, OTHER_INSTANCE) if iid not in calls)
        assert by_id[deferred_id].outcome == DEFERRED_DEADLINE
        assert by_id[deferred_id].reason == "not evaluated"
        assert by_id[deferred_id].type_results == ()

    def test_a_deferred_unit_alone_never_drives_a_failure_outcome(self, tmp_path: Path) -> None:
        for instance in (INSTANCE, OTHER_INSTANCE):
            _touch(tmp_path, instance, "quote_tick_0.feather", age_minutes=60)
        deadline = RunDeadline(budget_ns=1)

        results = run_ingest(
            tmp_path,
            data_types=(QuoteTick,),
            service_active_probe=_never_active,
            convert_fn=lambda *a: None,
            deadline=deadline,
        )

        assert not any(r.outcome == "failed" for r in results)
        assert any(r.outcome == DEFERRED_DEADLINE for r in results)


# ---------------------------------------------------------------------------
# The whole-type gate (`ingest_instance` / `_convert_one_definition_type`).
# ---------------------------------------------------------------------------


class TestWholeTypeGate:
    def test_a_type_deferred_by_the_gate_leaves_no_marker_and_no_breadcrumb(
        self, tmp_path: Path
    ) -> None:
        _touch(tmp_path, INSTANCE, "quote_tick_0.feather", age_minutes=60)
        _touch(tmp_path, INSTANCE, "trade_tick_0.feather", age_minutes=60)
        clock = FakeClock()
        calls: list[type] = []

        def slow_convert(catalog, instance_id, data_cls, subdirectory):  # type: ignore[no-untyped-def]
            calls.append(data_cls)
            clock.advance(1000)

        deadline = RunDeadline(budget_ns=1, clock_ns=clock)
        results = run_ingest(
            tmp_path,
            data_types=(QuoteTick, TradeTick),
            service_active_probe=_never_active,
            convert_fn=slow_convert,
            deadline=deadline,
        )

        assert calls == [QuoteTick]
        instance_dir = tmp_path / "live" / INSTANCE
        result = results[0]
        by_cls = {tr.data_cls: tr.outcome for tr in result.type_results}
        assert by_cls[QuoteTick] == "converted"
        assert by_cls[TradeTick] == DEFERRED_DEADLINE
        assert result.outcome == DEFERRED_DEADLINE
        assert not (instance_dir / f"{ATTEMPT_PREFIX}trade_tick").exists()
        assert not (instance_dir / ".converted-trade_tick").exists()
        assert (instance_dir / ".converted-quote_tick").exists()
        assert "partially ingested (deadline)" in result.summary_line()

    def test_expired_at_start_still_converts_exactly_one_type(self, tmp_path: Path) -> None:
        _touch(tmp_path, INSTANCE, "quote_tick_0.feather", age_minutes=60)
        clock = FakeClock()
        clock.advance(1000)  # already past budget before the run even starts
        calls: list[type] = []

        def convert(catalog, instance_id, data_cls, subdirectory):  # type: ignore[no-untyped-def]
            calls.append(data_cls)

        deadline = RunDeadline(budget_ns=1, clock_ns=clock)
        run_ingest(
            tmp_path,
            data_types=(QuoteTick,),
            service_active_probe=_never_active,
            convert_fn=convert,
            deadline=deadline,
        )
        assert calls == [QuoteTick]

    def test_a_baseexception_leaves_a_breadcrumb_without_a_marker(self, tmp_path: Path) -> None:
        _touch(tmp_path, INSTANCE, "quote_tick_0.feather", age_minutes=60)
        instance_dir = tmp_path / "live" / INSTANCE

        def killed(catalog, instance_id, data_cls, subdirectory):  # type: ignore[no-untyped-def]
            raise KeyboardInterrupt("simulated hard kill")

        deadline = RunDeadline(budget_ns=1_000_000_000_000)
        with pytest.raises(KeyboardInterrupt):
            run_ingest(
                tmp_path,
                data_types=(QuoteTick,),
                service_active_probe=_never_active,
                convert_fn=killed,
                deadline=deadline,
            )
        assert (instance_dir / f"{ATTEMPT_PREFIX}quote_tick").is_file()
        assert not (instance_dir / ".converted-quote_tick").exists()
        assert _instance_is_poisoned(instance_dir)

    def test_a_caught_value_error_clears_the_breadcrumb_it_wrote(self, tmp_path: Path) -> None:
        _touch(tmp_path, INSTANCE, "quote_tick_0.feather", age_minutes=60)
        instance_dir = tmp_path / "live" / INSTANCE

        def refused(catalog, instance_id, data_cls, subdirectory):  # type: ignore[no-untyped-def]
            raise ValueError("refused")

        deadline = RunDeadline(budget_ns=1_000_000_000_000)
        run_ingest(
            tmp_path,
            data_types=(QuoteTick,),
            service_active_probe=_never_active,
            convert_fn=refused,
            deadline=deadline,
        )
        assert not (instance_dir / f"{ATTEMPT_PREFIX}quote_tick").exists()
        assert not _instance_is_poisoned(instance_dir)

    def test_a_successful_conversion_clears_a_stale_breadcrumb(self, tmp_path: Path) -> None:
        _touch(tmp_path, INSTANCE, "quote_tick_0.feather", age_minutes=60)
        instance_dir = tmp_path / "live" / INSTANCE
        (instance_dir / f"{ATTEMPT_PREFIX}quote_tick").touch()  # stale, from an earlier kill

        deadline = RunDeadline(budget_ns=1_000_000_000_000)
        run_ingest(
            tmp_path,
            data_types=(QuoteTick,),
            service_active_probe=_never_active,
            convert_fn=lambda *a: None,
            deadline=deadline,
        )
        assert not (instance_dir / f"{ATTEMPT_PREFIX}quote_tick").exists()


# ---------------------------------------------------------------------------
# Poison-first ordering.
# ---------------------------------------------------------------------------


class TestPoisonFirstOrder:
    def test_poisoned_sorts_last_non_poisoned_keeps_newest_first(self, tmp_path: Path) -> None:
        for instance in ("a", "b", "c"):
            _touch(tmp_path, instance, "quote_tick_0.feather", age_minutes=60)
        (tmp_path / "live" / "a" / f"{ATTEMPT_PREFIX}quote_tick").touch()
        snap = ingest_cli_module.LivenessSnapshot(
            now_ns=0,
            grace_ns=0,
            instance_ids=("a", "b", "c"),
            newest_instance_id="c",
            service_active=False,
        )
        ordered = _poison_first_order(("a", "b", "c"), snap, tmp_path, "live")
        assert ordered == ("c", "b", "a")

    def test_a_salvage_attempt_breadcrumb_also_poisons_the_instance(self, tmp_path: Path) -> None:
        _touch(tmp_path, "a", "quote_tick_0.feather", age_minutes=60)
        _touch(tmp_path, "b", "quote_tick_0.feather", age_minutes=60)
        (tmp_path / "live" / "a" / ingest_cli_module._SALVAGE_ATTEMPT_NAME).touch()
        snap = ingest_cli_module.LivenessSnapshot(
            now_ns=0, grace_ns=0, instance_ids=("a", "b"), newest_instance_id=None,
            service_active=False,
        )
        ordered = _poison_first_order(("a", "b"), snap, tmp_path, "live")
        assert ordered == ("b", "a")

    def test_run_ingest_definitions_first_reorders_a_poisoned_instance_last(
        self, tmp_path: Path
    ) -> None:
        for instance in ("a", "b"):
            _touch(tmp_path, instance, "quote_tick_0.feather", age_minutes=60)
        (tmp_path / "live" / "a" / f"{ATTEMPT_PREFIX}quote_tick").touch()
        order_seen: list[str] = []

        def convert(catalog, instance_id, data_cls, subdirectory):  # type: ignore[no-untyped-def]
            order_seen.append(instance_id)

        deadline = RunDeadline(budget_ns=1_000_000_000_000)
        results = run_ingest_definitions_first(
            tmp_path,
            data_types=(QuoteTick,),
            service_active_probe=_never_active,
            convert_fn=convert,
            deadline=deadline,
        )
        assert order_seen == ["b", "a"]
        # the merged output stays in the ORIGINAL (unreordered) order (AC-D5)
        assert [r.instance_id for r in results] == ["a", "b"]


# ---------------------------------------------------------------------------
# The salvage gate.
# ---------------------------------------------------------------------------


class TestSalvageGate:
    def test_salvage_is_deferred_when_the_gate_denies_it(self, tmp_path: Path) -> None:
        # INSTANCE (alphabetically first) legitimately spends the run's ONE
        # guarantee on its own type conversion; OTHER_INSTANCE's truncated
        # file is the run's SECOND admit()-consuming action, so it is the
        # one denied. A `_TickingClock` lands the crossing precisely
        # between the two instances' loop-top peeks and the salvage gate's
        # own `admit()` -- see the class docstring.
        _touch(tmp_path, INSTANCE, "quote_tick_0.feather", age_minutes=60)
        instance_dir = tmp_path / "live" / OTHER_INSTANCE
        quote_path = instance_dir / "quote_tick_0.feather"
        _write_typed_ipc_stream(
            quote_path, [_quote_tick(i) for i in range(20)], QuoteTick, close=False
        )
        _truncate_tail(quote_path)
        stamp = time.time() - 60 * 60
        os.utime(quote_path, (stamp, stamp))

        clock = _TickingClock(step_ns=1000)
        deadline = RunDeadline(budget_ns=2500, clock_ns=clock)

        results = run_ingest(
            tmp_path,
            data_types=(QuoteTick,),
            service_active_probe=_never_active,
            convert_fn=lambda *a: None,
            deadline=deadline,
        )

        by_id = {r.instance_id: r for r in results}
        assert by_id[INSTANCE].outcome == "converted"
        other = by_id[OTHER_INSTANCE]
        catalog = ParquetDataCatalog(str(tmp_path))
        assert len(catalog.query(data_cls=QuoteTick)) == 0
        assert other.salvage_deferred is True
        assert other.outcome == "skipped-truncated"
        assert "salvage deferred (deadline)" in other.summary_line()
        assert not (instance_dir / ingest_cli_module._SALVAGE_ATTEMPT_NAME).exists()

    def test_an_already_salvaged_instance_never_consults_the_gate(self, tmp_path: Path) -> None:
        instance_dir = tmp_path / "live" / INSTANCE
        quote_path = instance_dir / "quote_tick_0.feather"
        _write_typed_ipc_stream(
            quote_path, [_quote_tick(i) for i in range(20)], QuoteTick, close=False
        )
        _truncate_tail(quote_path)
        stamp = time.time() - 60 * 60
        os.utime(quote_path, (stamp, stamp))

        # A prior (deadline=None) run already salvaged the recoverable prefix.
        run_ingest(tmp_path, data_types=(QuoteTick,), service_active_probe=_never_active)

        deadline = RunDeadline(budget_ns=1_000_000_000_000)
        deadline.admit()  # spend the guarantee on something other than salvage
        results = run_ingest(
            tmp_path,
            data_types=(QuoteTick,),
            service_active_probe=_never_active,
            deadline=deadline,
        )
        assert results[0].salvage_deferred is False
        assert not (instance_dir / ingest_cli_module._SALVAGE_ATTEMPT_NAME).exists()
        assert deadline.admitted == 1  # the earlier admit() only -- no second gate consulted


# ---------------------------------------------------------------------------
# The merge ladder.
# ---------------------------------------------------------------------------


class TestMergeLadder:
    def test_truncated_beats_failed(self) -> None:
        p1 = InstanceIngestResult(INSTANCE, "failed", reason="boom")
        p2 = InstanceIngestResult(INSTANCE, "skipped-truncated", reason="1 truncated")
        merged = _merge_pass_results((p1,), (p2,), order=(INSTANCE,))
        assert merged[0].outcome == "skipped-truncated"

    def test_failed_beats_deferred(self) -> None:
        p1 = InstanceIngestResult(INSTANCE, DEFERRED_DEADLINE, "not evaluated")
        p2 = InstanceIngestResult(INSTANCE, "failed", reason="boom")
        merged = _merge_pass_results((p1,), (p2,), order=(INSTANCE,))
        assert merged[0].outcome == "failed"

    def test_deferred_beats_converted_and_falls_back_to_p1_type_results(self) -> None:
        p1 = InstanceIngestResult(
            INSTANCE, "converted", type_results=(TypeConversionResult(QuoteTick, "converted"),)
        )
        p2 = InstanceIngestResult(INSTANCE, DEFERRED_DEADLINE, "not evaluated")
        merged = _merge_pass_results((p1,), (p2,), order=(INSTANCE,))
        assert merged[0].outcome == DEFERRED_DEADLINE
        assert merged[0].type_results == p1.type_results

    def test_converted_beats_live(self) -> None:
        p1 = InstanceIngestResult(INSTANCE, "skipped-live", reason="fresh")
        p2 = InstanceIngestResult(INSTANCE, "converted")
        merged = _merge_pass_results((p1,), (p2,), order=(INSTANCE,))
        assert merged[0].outcome == "converted"

    def test_salvage_deferred_is_the_logical_or_of_both_passes(self) -> None:
        p1 = InstanceIngestResult(INSTANCE, "converted", salvage_deferred=True)
        p2 = InstanceIngestResult(INSTANCE, "converted")
        merged = _merge_pass_results((p1,), (p2,), order=(INSTANCE,))
        assert merged[0].salvage_deferred is True

    def test_a_winning_p1_failed_keeps_the_reason_prefix(self) -> None:
        p1 = InstanceIngestResult(OTHER_INSTANCE, "failed", reason="boom")
        p2 = InstanceIngestResult(OTHER_INSTANCE, "converted")
        merged = _merge_pass_results((p1,), (p2,), order=(OTHER_INSTANCE,))
        assert merged[0].outcome == "failed"
        assert merged[0].reason == "definitions pass failed; boom"

    def test_merge_re_sorts_to_the_given_order_regardless_of_pass_order(self) -> None:
        p2_a = InstanceIngestResult(INSTANCE, "converted")
        p2_b = InstanceIngestResult(OTHER_INSTANCE, "converted")
        merged = _merge_pass_results((), (p2_b, p2_a), order=(INSTANCE, OTHER_INSTANCE))
        assert [r.instance_id for r in merged] == [INSTANCE, OTHER_INSTANCE]


# ---------------------------------------------------------------------------
# AC-D10: `deadline=None` is byte-identical.
# ---------------------------------------------------------------------------


class TestDeadlineNoneIsByteIdentical:
    def test_deadline_none_writes_no_breadcrumb_even_on_a_baseexception(
        self, tmp_path: Path
    ) -> None:
        _touch(tmp_path, INSTANCE, "quote_tick_0.feather", age_minutes=60)
        instance_dir = tmp_path / "live" / INSTANCE

        def killed(catalog, instance_id, data_cls, subdirectory):  # type: ignore[no-untyped-def]
            raise KeyboardInterrupt()

        with pytest.raises(KeyboardInterrupt):
            run_ingest(
                tmp_path,
                data_types=(QuoteTick,),
                service_active_probe=_never_active,
                convert_fn=killed,
            )
        assert not any(instance_dir.glob(f"{ATTEMPT_PREFIX}*"))

    def test_deadline_none_never_reorders_instances(self, tmp_path: Path) -> None:
        for instance in ("z", "a", "m"):
            _touch(tmp_path, instance, "quote_tick_0.feather", age_minutes=60)
        (tmp_path / "live" / "a" / f"{ATTEMPT_PREFIX}quote_tick").touch()
        seen: list[str] = []

        def convert(catalog, instance_id, data_cls, subdirectory):  # type: ignore[no-untyped-def]
            seen.append(instance_id)

        run_ingest(
            tmp_path,
            data_types=(QuoteTick,),
            service_active_probe=_never_active,
            convert_fn=convert,
        )
        assert seen == ["a", "m", "z"]  # list_instance_ids' natural sort, untouched


# ---------------------------------------------------------------------------
# The CLI: argument validation and the summary/count line.
# ---------------------------------------------------------------------------


class TestArgparseDefault:
    def test_default_deadline_seconds_is_the_module_constant(self) -> None:
        parser = ingest_cli_module._build_parser()
        namespace = parser.parse_args([])
        assert namespace.deadline_seconds == DEFAULT_DEADLINE_SECONDS == 600


class TestCLIDeadlineLine:
    def test_deadline_line_printed_with_zero_instances(self, tmp_path: Path) -> None:
        (tmp_path / "live").mkdir()
        out, _err = _run_cli(["--catalog", str(tmp_path)])
        assert "breezy-quote-tape-ingest: deadline budget=600s" in out
        assert "deferred_units=0 deferred_instances=0 instances=0" in out

    def test_dry_run_prints_no_deadline_line(self, tmp_path: Path) -> None:
        (tmp_path / "live").mkdir()
        out, _err = _run_cli(["--catalog", str(tmp_path), "--dry-run"])
        assert "deadline budget=" not in out

    def test_zero_deadline_seconds_exits_usage_with_no_deadline_line(
        self, tmp_path: Path
    ) -> None:
        out, err = _run_cli(["--catalog", str(tmp_path), "--deadline-seconds", "0"])
        assert "deadline budget=" not in out
        assert "--deadline-seconds" in err

    def test_negative_deadline_seconds_exits_usage(self, tmp_path: Path) -> None:
        import io

        code = run(
            ["--catalog", str(tmp_path), "--deadline-seconds", "-5"],
            stdout=io.StringIO(),
            stderr=io.StringIO(),
        )
        assert code == EXIT_USAGE

    def test_a_preflight_error_still_prints_the_deadline_line(self, tmp_path: Path) -> None:
        missing = tmp_path / "does-not-exist"
        out, _err = _run_cli(["--catalog", str(missing)])
        assert "deadline budget=600s" in out
        assert "instances=0" in out

    def test_a_hard_conversion_failure_still_prints_the_deadline_line(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _touch(tmp_path, INSTANCE, "quote_tick_0.feather", age_minutes=60)

        def boom(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            raise ValueError("boom -- not the non-disjoint refusal text")

        monkeypatch.setattr(ParquetDataCatalog, "convert_stream_to_data", boom)
        import io

        out_buf, err_buf = io.StringIO(), io.StringIO()
        code = run(
            ["--catalog", str(tmp_path), "--service-unit", _INACTIVE_SERVICE_UNIT],
            stdout=out_buf,
            stderr=err_buf,
        )
        assert code == EXIT_CONVERSION_FAILED
        assert "deadline budget=600s" in out_buf.getvalue()


def _run_cli(argv: list[str]) -> tuple[str, str]:
    import io

    out, err = io.StringIO(), io.StringIO()
    run(argv, stdout=out, stderr=err)
    return out.getvalue(), err.getvalue()


# ---------------------------------------------------------------------------
# Drain across runs.
# ---------------------------------------------------------------------------


class TestDrainAcrossRuns:
    def test_a_deferred_type_converts_on_the_next_run_with_no_duplicates(
        self, tmp_path: Path
    ) -> None:
        _touch(tmp_path, INSTANCE, "quote_tick_0.feather", age_minutes=60)
        _touch(tmp_path, INSTANCE, "trade_tick_0.feather", age_minutes=60)
        clock = FakeClock()

        def slow_convert(catalog, instance_id, data_cls, subdirectory):  # type: ignore[no-untyped-def]
            clock.advance(1000)

        deadline = RunDeadline(budget_ns=1, clock_ns=clock)
        first = run_ingest(
            tmp_path,
            data_types=(QuoteTick, TradeTick),
            service_active_probe=_never_active,
            convert_fn=slow_convert,
            deadline=deadline,
        )
        by_cls = {r.data_cls: r.outcome for r in first[0].type_results}
        assert by_cls[TradeTick] == DEFERRED_DEADLINE

        second = run_ingest(
            tmp_path, data_types=(QuoteTick, TradeTick), service_active_probe=_never_active
        )
        instance_dir = tmp_path / "live" / INSTANCE
        assert (instance_dir / ".converted-trade_tick").is_file()
        assert second[0].outcome == "converted"
