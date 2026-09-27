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
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from nautilus_trader.model.data import QuoteTick, TradeTick
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

import breezy.runtime.quote_tape_ingest_cli as ingest_cli_module
from breezy.persistence.feather_preflight import inspect_feather_file
from breezy.runtime.ingest_deadline import (
    DEFAULT_DEADLINE_SECONDS,
    DEFERRED_DEADLINE,
    RunDeadline,
    count_deferred,
)
from breezy.runtime.quote_tape_ingest_cli import (
    ATTEMPT_PREFIX,
    EXIT_CONVERSION_FAILED,
    EXIT_OK,
    EXIT_USAGE,
    MARKER_PREFIX,
    InstanceIngestResult,
    TypeConversionResult,
    _instance_is_poisoned,
    _merge_pass_results,
    _poison_first_order,
    default_convert,
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
    _trade_tick,
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

        def boom(*args, **kwargs):  # type: ignore[no-untyped-def]
            raise ValueError("boom -- not the non-disjoint refusal text")

        monkeypatch.setattr(ingest_cli_module, "_convert_stream_natively", boom)
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


# ---------------------------------------------------------------------------
# T-sticky: a hypothesis property over random clock/call sequences (audit gap).
# ---------------------------------------------------------------------------

_ADMIT_CALL = "admit"
_CAN_ADMIT_CALL = "can_admit"
_NOTE_SCAN_CALL = "note_scan"

_CALL_KIND = st.sampled_from([_ADMIT_CALL, _CAN_ADMIT_CALL, _NOTE_SCAN_CALL])
#: Deliberately allows NEGATIVE steps too -- a clock quirk (see
#: `test_the_first_false_is_sticky_forever` above) is exactly the case that
#: distinguishes genuine stickiness from "budget never un-expires because the
#: clock never runs backward in this test".
_CLOCK_STEP = st.integers(min_value=-500, max_value=1000)


class TestStickyPropertyOverRandomCallSequences:
    @given(
        budget_ns=st.integers(min_value=0, max_value=5000),
        steps=st.lists(st.tuples(_CALL_KIND, _CLOCK_STEP), min_size=1, max_size=50),
    )
    @settings(max_examples=200, deadline=None)
    def test_after_the_first_false_every_later_call_is_false_and_admitted_freezes(
        self, budget_ns: int, steps: list[tuple[str, int]]
    ) -> None:
        clock = FakeClock()
        deadline = RunDeadline(budget_ns=budget_ns, clock_ns=clock)
        seen_false = False
        admitted_at_first_false: int | None = None
        for kind, step in steps:
            clock.advance(step)
            if kind == _NOTE_SCAN_CALL:
                deadline.note_scan()
                continue
            result = deadline.admit() if kind == _ADMIT_CALL else deadline.can_admit()
            if seen_false:
                assert result is False, "a call after the first False must stay False"
                assert deadline.admitted == admitted_at_first_false, (
                    "admitted must never grow once the deadline has closed"
                )
            elif result is False:
                seen_false = True
                admitted_at_first_false = deadline.admitted


# ---------------------------------------------------------------------------
# T7b: ONE RunDeadline shared across pass 1 and pass 2, not one per pass.
# ---------------------------------------------------------------------------


class TestSharedDeadlineAcrossBothPasses:
    def test_pass_two_never_converts_once_pass_one_has_closed_the_shared_deadline(
        self, tmp_path: Path
    ) -> None:
        _touch(tmp_path, INSTANCE, "binary_option_0.feather", age_minutes=60)
        _touch(tmp_path, INSTANCE, "quote_tick_0.feather", age_minutes=60)
        # budget_ns=0: the guarantee (pass 1's BinaryOption) always succeeds,
        # but the very next admit() call anywhere -- even with a clock that
        # never advances -- is instantly expired (0 < 0 is False).
        clock = FakeClock()
        deadline = RunDeadline(budget_ns=0, clock_ns=clock)
        calls: list[type] = []

        def spy_convert(catalog, instance_id, data_cls, subdirectory):  # type: ignore[no-untyped-def]
            calls.append(data_cls)

        results = run_ingest_definitions_first(
            tmp_path,
            data_types=(BinaryOption, QuoteTick),
            service_active_probe=_never_active,
            convert_fn=spy_convert,
            deadline=deadline,
        )

        assert calls == [BinaryOption], (
            "pass 1 must spend the run's ONE guarantee on the definitions type; "
            "sharing one RunDeadline means pass 2 must make ZERO convert calls "
            "once it is closed -- a per-pass deadline or a guarantee reset "
            "would let QuoteTick convert too"
        )
        merged = results[0]
        assert merged.outcome == DEFERRED_DEADLINE
        assert merged.type_results == (TypeConversionResult(BinaryOption, "converted"),)


# ---------------------------------------------------------------------------
# T7a-tail: N>=3 no-work instances ahead of the one with work, run starts
# expired -- the scan tail is bounded to exactly ONE no-work scan.
# ---------------------------------------------------------------------------


class TestExpiredStartWithManyNoWorkInstancesAhead:
    def test_scan_tail_bounded_to_one_scan_defers_every_other_instance_too(
        self, tmp_path: Path
    ) -> None:
        no_work_ids = ["instance-a", "instance-b", "instance-c"]
        for iid in no_work_ids:
            # age_minutes=0: within the live-grace window -- genuinely LIVE,
            # nothing convertible, but still requires a real preflight scan
            # (it is not on the fully-converted fast path).
            _touch(tmp_path, iid, "quote_tick_0.feather", age_minutes=0)
        work_id = "instance-z"
        _touch(tmp_path, work_id, "quote_tick_0.feather", age_minutes=60)

        clock = _TickingClock(step_ns=2_000_000_000)  # every read jumps 2s
        deadline = RunDeadline(budget_ns=1_000_000_000, clock_ns=clock)

        results = run_ingest(
            tmp_path,
            data_types=(QuoteTick,),
            service_active_probe=_never_active,
            convert_fn=lambda *a: None,
            deadline=deadline,
        )

        assert deadline.scans_started == 1
        assert deadline.admitted == 0
        by_id = {r.instance_id: r for r in results}
        assert by_id[no_work_ids[0]].outcome == "skipped-live"
        for iid in (*no_work_ids[1:], work_id):
            assert by_id[iid].outcome == DEFERRED_DEADLINE
            assert by_id[iid].reason == "not evaluated"
        _units, instances = count_deferred(results)
        assert instances == len(no_work_ids)

    def test_the_run_still_exits_zero(self, tmp_path: Path) -> None:
        for iid in ("instance-a", "instance-b", "instance-c"):
            _touch(tmp_path, iid, "quote_tick_0.feather", age_minutes=0)
        _touch(tmp_path, "instance-z", "quote_tick_0.feather", age_minutes=60)

        out, _err = _run_cli(
            ["--catalog", str(tmp_path), "--deadline-seconds", "1"],
        )
        # No monkeypatched clock here -- a real, generous wall clock still
        # lands well within budget for four empty-file scans, so this leg
        # only pins the exit code, never the deferral counts themselves.
        assert "breezy-quote-tape-ingest: deadline budget=1s" in out


# ---------------------------------------------------------------------------
# T-n1-survive / T-n1-noop: the per-file poison breadcrumb is written only
# after admit()->True and cleared ONLY on a terminal outcome -- a no-op
# (skipped-open, skipped-unclosed, skipped-definitions-pending) never
# touches it (N1/N6, r3 amendment).
# ---------------------------------------------------------------------------


class TestPerFileBreadcrumbSurvivesNoOps:
    def test_a_stale_definition_breadcrumb_survives_a_skipped_open_no_op(
        self, tmp_path: Path
    ) -> None:
        instance_dir = tmp_path / "live" / INSTANCE
        path = instance_dir / "binary_option_0.feather"
        path.parent.mkdir(parents=True)
        path.touch()  # age 0 -- inside the live-grace window, so "open"
        attempt = instance_dir / f"{ATTEMPT_PREFIX}binary_option"
        attempt.touch()  # stale, as if an earlier gated run was killed
        catalog = ParquetDataCatalog(str(tmp_path))
        deadline = RunDeadline(budget_ns=1_000_000_000_000)

        result, converted, is_open = ingest_cli_module._convert_one_definition_type(
            catalog,
            instance_dir,
            INSTANCE,
            "live",
            BinaryOption,
            frozenset({path}),
            convert_fn=lambda *a: None,
            dry_run=False,
            deadline=deadline,
        )

        assert result.outcome == "skipped-open"
        assert not converted
        assert is_open
        assert attempt.is_file()

    def test_a_stale_tick_breadcrumb_survives_an_all_unclosed_no_op(
        self, tmp_path: Path
    ) -> None:
        instance_dir = tmp_path / "live" / INSTANCE
        path = instance_dir / "quote_tick_0.feather"
        _write_typed_ipc_stream(path, [_quote_tick(i) for i in range(5)], QuoteTick, close=False)
        stamp = time.time() - 60 * 60
        os.utime(path, (stamp, stamp))
        report = inspect_feather_file(path)
        assert not report.end_of_stream_marker
        attempt = instance_dir / f"{ATTEMPT_PREFIX}quote_tick"
        attempt.touch()
        catalog = ParquetDataCatalog(str(tmp_path))
        deadline = RunDeadline(budget_ns=1_000_000_000_000)

        result, converted, is_open = ingest_cli_module._convert_one_tick_type_per_file(
            catalog,
            instance_dir,
            INSTANCE,
            QuoteTick,
            frozenset(),
            {path: report},
            instance_is_dead=False,
            dry_run=False,
            deadline=deadline,
        )

        assert "skipped-unclosed" in result.outcome
        assert not converted
        assert not is_open
        assert attempt.is_file()


class TestPerFileBreadcrumbSurvivesAKillThenTheNextRunConverts:
    def test_survives_a_definitions_pending_skip_then_is_cleared_by_a_later_conversion(
        self, tmp_path: Path
    ) -> None:
        instance_dir = tmp_path / "live" / INSTANCE
        # The genuinely-convertible file, sibling to an OPEN file in the same
        # type group -- open_files non-empty forces the per-file route
        # without needing an unrelated truncated file at all.
        quote_0 = instance_dir / "quote_tick_0.feather"
        _write_typed_ipc_stream(quote_0, [_quote_tick(i) for i in range(5)], QuoteTick, close=True)
        stamp = time.time() - 60 * 60
        os.utime(quote_0, (stamp, stamp))
        quote_1 = instance_dir / "quote_tick_1.feather"
        quote_1.touch()  # age 0 -- open sibling in the SAME group

        attempt = instance_dir / f"{ATTEMPT_PREFIX}quote_tick"
        raised = {"count": 0}
        real_read = ingest_cli_module.read_feather_coalesced  # type: ignore[attr-defined]

        def flaky_read(fs, path, *a, **kw):  # type: ignore[no-untyped-def]
            if raised["count"] == 0:
                raised["count"] += 1
                raise KeyboardInterrupt("simulated hard kill on the first read")
            return real_read(fs, path, *a, **kw)

        # Run 1: a hard kill mid-conversion leaves the breadcrumb, no marker.
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(ingest_cli_module, "read_feather_coalesced", flaky_read)
            deadline = RunDeadline(budget_ns=1_000_000_000_000)
            with pytest.raises(KeyboardInterrupt):
                run_ingest(
                    tmp_path,
                    data_types=(QuoteTick,),
                    service_active_probe=_never_active,
                    deadline=deadline,
                )
        assert attempt.is_file()
        assert not (instance_dir / ".converted-file-quote_tick_0.feather").exists()

        # Run 2: an OPEN instrument-definition file makes every tick type
        # `skipped-definitions-pending` -- a pure no-op that never touches
        # the tick breadcrumb (N1).
        binary_path = instance_dir / "binary_option_0.feather"
        binary_path.touch()  # age 0 -- open
        deadline_2 = RunDeadline(budget_ns=1_000_000_000_000)
        run_ingest(
            tmp_path,
            data_types=(BinaryOption, QuoteTick),
            service_active_probe=_never_active,
            convert_fn=lambda *a: None,
            deadline=deadline_2,
        )
        assert attempt.is_file(), "a skipped-definitions-pending no-op must never clear it"

        # Run 3: the definitions gate is gone (BinaryOption not requested),
        # the earlier kill is fixed -- the file finally converts and the
        # breadcrumb clears.
        deadline_3 = RunDeadline(budget_ns=1_000_000_000_000)
        third = run_ingest(
            tmp_path,
            data_types=(QuoteTick,),
            service_active_probe=_never_active,
            deadline=deadline_3,
        )
        assert not attempt.exists()
        assert (instance_dir / ".converted-file-quote_tick_0.feather").is_file()
        assert third[0].outcome != "failed"


# ---------------------------------------------------------------------------
# T-n6: a marker touched with a kill before the breadcrumb unlink (simulated
# here directly, since the real window is two Python statements wide) --
# verified against the ACTUAL shipped code (not the r3 amendment's summary
# prose): the marked-skip path unlinks a stale breadcrumb UNCONDITIONALLY,
# whether or not a deadline is set this run. `_mark_converted`'s own
# docstring calls this "harmless no-op (missing_ok) when no deadline was
# ever set -- AC-D10", and R9 in the r3 amendment separately confirms a
# stale breadcrumb under `deadline=None` is "inert (no reorder)" either way
# -- reordering, the only consumer of breadcrumb state, never runs when
# `deadline` is `None`. (NOTE: the r3 amendment's own test-list prose says
# "deadline=None leaves it"; that is NOT what the shipped code does, and
# this test pins the code's actual, safer, documented behavior instead.)
# ---------------------------------------------------------------------------


class TestMarkedSkipUnlinksAStaleBreadcrumbEitherWay:
    def test_a_marker_touched_with_a_kill_before_the_unlink_is_swept_by_the_next_runs_skip(
        self, tmp_path: Path
    ) -> None:
        instance_dir = tmp_path / "live" / INSTANCE
        _touch(tmp_path, INSTANCE, "quote_tick_0.feather", age_minutes=60)
        # Simulate a kill landing between `_mark_converted`'s marker `.touch()`
        # and its breadcrumb `.unlink()` -- both files present at once.
        (instance_dir / f"{MARKER_PREFIX}quote_tick").touch()
        attempt = instance_dir / f"{ATTEMPT_PREFIX}quote_tick"
        attempt.touch()

        run_ingest(
            tmp_path, data_types=(QuoteTick,), service_active_probe=_never_active, deadline=None
        )

        assert not attempt.exists(), (
            "the marked-skip path must sweep a stale breadcrumb even with "
            "deadline=None -- it is a harmless no-op by construction (AC-D10)"
        )

    def test_the_same_kill_is_swept_when_a_deadline_is_set(self, tmp_path: Path) -> None:
        instance_dir = tmp_path / "live" / INSTANCE
        _touch(tmp_path, INSTANCE, "quote_tick_0.feather", age_minutes=60)
        (instance_dir / f"{MARKER_PREFIX}quote_tick").touch()
        attempt = instance_dir / f"{ATTEMPT_PREFIX}quote_tick"
        attempt.touch()

        run_ingest(
            tmp_path,
            data_types=(QuoteTick,),
            service_active_probe=_never_active,
            deadline=RunDeadline(budget_ns=1_000_000_000_000),
        )

        assert not attempt.exists()


# ---------------------------------------------------------------------------
# T-n2-marked: an expired run over fully-marked definition types is a pure
# no-op -- it must never consult the deadline at all.
# ---------------------------------------------------------------------------


class TestExpiredRunOverFullyMarkedTypesIsANoOp:
    def test_expired_run_over_a_fully_marked_definition_type(self, tmp_path: Path) -> None:
        instance_dir = tmp_path / "live" / INSTANCE
        _touch(tmp_path, INSTANCE, "binary_option_0.feather", age_minutes=60)
        (instance_dir / f"{MARKER_PREFIX}binary_option").touch()
        deadline = RunDeadline(budget_ns=0)  # expired from the first check onward

        results = run_ingest(
            tmp_path,
            data_types=(BinaryOption,),
            service_active_probe=_never_active,
            deadline=deadline,
        )

        assert results[0].type_results[0].outcome == "skipped-already-converted"
        assert deadline.admitted == 0
        assert not any(instance_dir.glob(f"{ATTEMPT_PREFIX}*"))
        units, instances = count_deferred(results)
        assert units == 0
        assert instances == 0


# ---------------------------------------------------------------------------
# T-n2-lazy: the per-file tick gate is consulted lazily, exactly once per
# type per call -- never for a type with nothing convertible.
# ---------------------------------------------------------------------------


class TestPerFileLazyGateTiming:
    def test_an_open_unclosed_only_type_never_calls_admit(self, tmp_path: Path) -> None:
        instance_dir = tmp_path / "live" / INSTANCE
        path = instance_dir / "quote_tick_0.feather"
        _write_typed_ipc_stream(path, [_quote_tick(i) for i in range(3)], QuoteTick, close=False)
        stamp = time.time() - 60 * 60
        os.utime(path, (stamp, stamp))
        report = inspect_feather_file(path)
        catalog = ParquetDataCatalog(str(tmp_path))
        deadline = RunDeadline(budget_ns=1_000_000_000_000)

        _result, converted, is_open = ingest_cli_module._convert_one_tick_type_per_file(
            catalog, instance_dir, INSTANCE, QuoteTick, frozenset(), {path: report},
            instance_is_dead=False, dry_run=False, deadline=deadline,
        )

        assert deadline.admitted == 0
        assert not converted
        assert not is_open

    def test_a_type_whose_first_convertible_file_is_its_third_admits_exactly_once(
        self, tmp_path: Path
    ) -> None:
        instance_dir = tmp_path / "live" / INSTANCE
        marked_path = instance_dir / "quote_tick_0.feather"
        _write_typed_ipc_stream(
            marked_path, [_quote_tick(i) for i in range(3)], QuoteTick, close=True
        )
        ingest_cli_module._mark_file_converted(instance_dir, marked_path)  # no-op #1

        unreported_path = instance_dir / "quote_tick_1.feather"
        unreported_path.touch()  # present on disk but absent from reports_by_path -- no-op #2

        convertible_a = instance_dir / "quote_tick_2.feather"
        _write_typed_ipc_stream(
            convertible_a, [_quote_tick(100 + i) for i in range(3)], QuoteTick, close=True
        )
        convertible_b = instance_dir / "quote_tick_3.feather"
        _write_typed_ipc_stream(
            convertible_b, [_quote_tick(200 + i) for i in range(3)], QuoteTick, close=True
        )
        for path in (marked_path, unreported_path, convertible_a, convertible_b):
            stamp = time.time() - 60 * 60
            os.utime(path, (stamp, stamp))

        reports_by_path = {
            marked_path: inspect_feather_file(marked_path),
            convertible_a: inspect_feather_file(convertible_a),
            convertible_b: inspect_feather_file(convertible_b),
        }
        catalog = ParquetDataCatalog(str(tmp_path))
        deadline = RunDeadline(budget_ns=1_000_000_000_000)

        _result, converted, _is_open = ingest_cli_module._convert_one_tick_type_per_file(
            catalog, instance_dir, INSTANCE, QuoteTick, frozenset(), reports_by_path,
            instance_is_dead=False, dry_run=False, deadline=deadline,
        )

        # ONE admit() call gates the whole type; both convertible files in
        # THIS call then proceed without a second check (lazy, per-type).
        assert deadline.admitted == 1
        assert converted
        assert (instance_dir / f".converted-file-{convertible_a.name}").is_file()
        assert (instance_dir / f".converted-file-{convertible_b.name}").is_file()

    def test_a_convertible_file_after_expiry_is_deferred_and_earlier_files_are_not_re_read(
        self, tmp_path: Path
    ) -> None:
        instance_dir = tmp_path / "live" / INSTANCE
        marked_path = instance_dir / "quote_tick_0.feather"
        _write_typed_ipc_stream(
            marked_path, [_quote_tick(i) for i in range(3)], QuoteTick, close=True
        )
        ingest_cli_module._mark_file_converted(instance_dir, marked_path)
        convertible_path = instance_dir / "quote_tick_1.feather"
        _write_typed_ipc_stream(
            convertible_path, [_quote_tick(50 + i) for i in range(3)], QuoteTick, close=True
        )
        for path in (marked_path, convertible_path):
            stamp = time.time() - 60 * 60
            os.utime(path, (stamp, stamp))
        reports_by_path = {
            marked_path: inspect_feather_file(marked_path),
            convertible_path: inspect_feather_file(convertible_path),
        }
        catalog = ParquetDataCatalog(str(tmp_path))
        # Already closed BEFORE this call: the guarantee spent, and time has
        # since moved on.
        deadline = RunDeadline(budget_ns=0)
        deadline.admit()
        deadline.admit()
        assert deadline.admitted == 1

        read_calls: list[Path] = []
        real_read = ingest_cli_module.read_feather_coalesced  # type: ignore[attr-defined]

        def counting_read(fs, path, *a, **kw):  # type: ignore[no-untyped-def]
            read_calls.append(Path(path))
            return real_read(fs, path, *a, **kw)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(ingest_cli_module, "read_feather_coalesced", counting_read)
            result, converted, _is_open = ingest_cli_module._convert_one_tick_type_per_file(
                catalog, instance_dir, INSTANCE, QuoteTick, frozenset(), reports_by_path,
                instance_is_dead=False, dry_run=False, deadline=deadline,
            )

        assert result.outcome == DEFERRED_DEADLINE
        assert not converted
        assert read_calls == [], "neither the marked nor the deferred file may be read"
        assert not (instance_dir / f"{ATTEMPT_PREFIX}quote_tick").exists()


# ---------------------------------------------------------------------------
# T-newest-skip: a live instance with nothing convertible must never burn the
# run's one guarantee -- the next instance still gets it.
# ---------------------------------------------------------------------------


class TestALiveInstanceWithNothingConvertibleNeverBurnsTheGuarantee:
    def test_the_next_instance_consumes_the_guarantee_instead(self, tmp_path: Path) -> None:
        newest_id, next_id = "instance-a", "instance-b"
        _touch(tmp_path, newest_id, "quote_tick_0.feather", age_minutes=0)
        _touch(tmp_path, next_id, "quote_tick_0.feather", age_minutes=60)
        deadline = RunDeadline(budget_ns=1_000_000_000_000)

        results = run_ingest(
            tmp_path,
            data_types=(QuoteTick,),
            service_active_probe=_never_active,
            convert_fn=lambda *a: None,
            deadline=deadline,
        )

        by_id = {r.instance_id: r for r in results}
        assert by_id[newest_id].outcome == "skipped-live"
        assert by_id[next_id].outcome == "converted"
        assert deadline.admitted == 1


# ---------------------------------------------------------------------------
# T-scan-clock: time spent inside `scan_instance` counts against the SAME
# budget the next instance's loop-top peek reads.
# ---------------------------------------------------------------------------


class TestScanTimeCountsAgainstTheBudget:
    def test_a_slow_scan_closes_the_gate_for_the_next_instance(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _touch(tmp_path, INSTANCE, "quote_tick_0.feather", age_minutes=60)
        _touch(tmp_path, OTHER_INSTANCE, "quote_tick_0.feather", age_minutes=60)
        clock = FakeClock()
        deadline = RunDeadline(budget_ns=5_000, clock_ns=clock)
        real_scan_instance = ingest_cli_module.scan_instance_memoized
        scan_calls: list[str] = []

        def slow_scan_instance(  # type: ignore[no-untyped-def]
            catalog_root, instance_id, subdirectory, *, open_files
        ):
            scan_calls.append(instance_id)
            clock.advance(0.00001)  # 10_000 ns -- more than the whole budget
            return real_scan_instance(
                catalog_root, instance_id, subdirectory, open_files=open_files
            )

        monkeypatch.setattr(ingest_cli_module, "scan_instance_memoized", slow_scan_instance)

        results = run_ingest(
            tmp_path,
            data_types=(QuoteTick,),
            service_active_probe=_never_active,
            convert_fn=lambda *a: None,
            deadline=deadline,
        )

        assert scan_calls == [INSTANCE]
        by_id = {r.instance_id: r for r in results}
        assert by_id[INSTANCE].outcome == "converted"
        assert by_id[OTHER_INSTANCE].outcome == DEFERRED_DEADLINE
        assert by_id[OTHER_INSTANCE].reason == "not evaluated"


# ---------------------------------------------------------------------------
# Rework of T6b / T-partial-whole / T-drain with REAL feather streams and the
# real StreamingFeatherWriter/catalog (L-42): row counts after the drain
# must equal a single no-deadline run's, with no duplicates.
# ---------------------------------------------------------------------------


class TestRealFeatherDrainMatchesANoDeadlineRun:
    @staticmethod
    def _seed(catalog_root: Path, instance_id: str) -> None:
        quote_path = catalog_root / "live" / instance_id / "quote_tick_0.feather"
        trade_path = catalog_root / "live" / instance_id / "trade_tick_0.feather"
        _write_typed_ipc_stream(
            quote_path, [_quote_tick(i) for i in range(30)], QuoteTick, close=True
        )
        _write_typed_ipc_stream(
            trade_path, [_trade_tick(i) for i in range(30)], TradeTick, close=True
        )
        stamp = time.time() - 60 * 60
        for path in (quote_path, trade_path):
            os.utime(path, (stamp, stamp))

    def test_a_type_deferred_mid_instance_lands_identical_rows_to_a_single_no_deadline_run(
        self, tmp_path: Path
    ) -> None:
        deadline_root = tmp_path / "deadline"
        control_root = tmp_path / "control"
        (deadline_root / "live").mkdir(parents=True)
        (control_root / "live").mkdir(parents=True)
        self._seed(deadline_root, INSTANCE)
        self._seed(control_root, INSTANCE)

        clock = FakeClock()

        def counting_convert(catalog, instance_id, data_cls, subdirectory):  # type: ignore[no-untyped-def]
            outcome = default_convert(catalog, instance_id, data_cls, subdirectory)
            clock.advance(1000)  # the first REAL conversion spends the whole budget
            return outcome

        deadline = RunDeadline(budget_ns=1, clock_ns=clock)
        first = run_ingest(
            deadline_root,
            data_types=(QuoteTick, TradeTick),
            service_active_probe=_never_active,
            convert_fn=counting_convert,
            deadline=deadline,
        )
        deferred_types = [
            r.data_cls for r in first[0].type_results if r.outcome == DEFERRED_DEADLINE
        ]
        assert deferred_types, "fixture must actually defer at least one type"
        instance_dir = deadline_root / "live" / INSTANCE
        assert (instance_dir / ".converted-quote_tick").is_file()
        assert not (instance_dir / ".converted-trade_tick").exists()

        second = run_ingest(
            deadline_root, data_types=(QuoteTick, TradeTick), service_active_probe=_never_active
        )
        assert second[0].outcome == "converted"
        assert (instance_dir / ".converted-trade_tick").is_file()

        control = run_ingest(
            control_root, data_types=(QuoteTick, TradeTick), service_active_probe=_never_active
        )
        assert control[0].outcome == "converted"

        deadline_catalog = ParquetDataCatalog(str(deadline_root))
        control_catalog = ParquetDataCatalog(str(control_root))
        for data_cls in (QuoteTick, TradeTick):
            deadline_rows = deadline_catalog.query(data_cls=data_cls)
            control_rows = control_catalog.query(data_cls=data_cls)
            assert len(deadline_rows) == len(control_rows) == 30
            deadline_ts = [t.ts_init for t in deadline_rows]
            assert len(deadline_ts) == len(set(deadline_ts)), "no duplicate rows (L-42)"


# ---------------------------------------------------------------------------
# T-poison end to end across runs: A dies mid-unit, leaving a breadcrumb; the
# NEXT run attempts B and C before A, and A's eventual marker write clears
# the breadcrumb.
# ---------------------------------------------------------------------------


class TestPoisonEndToEndAcrossRuns:
    def test_a_poisoned_instance_runs_last_next_time_and_clears_on_success(
        self, tmp_path: Path
    ) -> None:
        ids = ("instance-a", "instance-b", "instance-c")
        stamp = time.time() - 60 * 60
        for iid in ids:
            path = _touch(tmp_path, iid, "quote_tick_0.feather")
            os.utime(path, (stamp, stamp))  # identical mtimes -- no "newest" tiebreak

        def fail_on_a(catalog, instance_id, data_cls, subdirectory):  # type: ignore[no-untyped-def]
            if instance_id == "instance-a":
                raise KeyboardInterrupt("simulated hard kill on instance-a")

        deadline_1 = RunDeadline(budget_ns=1_000_000_000_000)
        with pytest.raises(KeyboardInterrupt):
            run_ingest_definitions_first(
                tmp_path,
                data_types=(QuoteTick,),
                service_active_probe=_never_active,
                convert_fn=fail_on_a,
                deadline=deadline_1,
            )
        instance_a_dir = tmp_path / "live" / "instance-a"
        assert (instance_a_dir / f"{ATTEMPT_PREFIX}quote_tick").is_file()
        assert not (instance_a_dir / ".converted-quote_tick").exists()

        order_seen: list[str] = []

        def convert_and_record(catalog, instance_id, data_cls, subdirectory):  # type: ignore[no-untyped-def]
            order_seen.append(instance_id)

        deadline_2 = RunDeadline(budget_ns=1_000_000_000_000)
        run_ingest_definitions_first(
            tmp_path,
            data_types=(QuoteTick,),
            service_active_probe=_never_active,
            convert_fn=convert_and_record,
            deadline=deadline_2,
        )

        assert order_seen == ["instance-b", "instance-c", "instance-a"], (
            "B and C must convert before the poisoned A; A still runs LAST, never skipped"
        )
        assert (instance_a_dir / ".converted-quote_tick").is_file()
        assert not (instance_a_dir / f"{ATTEMPT_PREFIX}quote_tick").exists()


# ---------------------------------------------------------------------------
# T-merge raw-count integration: `run_ingest_definitions_first` must record
# deferral counts from the RAW (pre-merge) pass results.
# ---------------------------------------------------------------------------


class TestMergeRawCountIntegration:
    def test_records_counts_from_raw_pass_results_not_the_merged_view(
        self, tmp_path: Path
    ) -> None:
        _touch(tmp_path, INSTANCE, "binary_option_0.feather", age_minutes=60)
        # `_TickingClock` lands the crossing precisely between the loop-top
        # peek and the definitions-type admit() inside pass 1 -- see
        # `TestSalvageGate`'s docstring for the same technique.
        clock = _TickingClock(step_ns=1000)
        deadline = RunDeadline(budget_ns=1500, clock_ns=clock)
        deadline.admit()  # pre-consume this run's one guarantee

        results = run_ingest_definitions_first(
            tmp_path,
            data_types=(BinaryOption,),
            service_active_probe=_never_active,
            convert_fn=lambda *a: None,
            deadline=deadline,
        )

        assert deadline.deferred_units == 1
        assert deadline.deferred_instances == 1
        merged = results[0]
        assert merged.outcome == DEFERRED_DEADLINE
        assert merged.reason == "not evaluated"
        assert merged.type_results == (TypeConversionResult(BinaryOption, DEFERRED_DEADLINE),)


# ---------------------------------------------------------------------------
# T-exit: a deferral-only run (no failures) always exits 0.
# ---------------------------------------------------------------------------


class TestExitZeroOnADeferralOnlyRun:
    def test_run_exits_zero_when_every_non_success_is_a_deferral(self, tmp_path: Path) -> None:
        _touch(tmp_path, "instance-a", "quote_tick_0.feather", age_minutes=60)
        _touch(tmp_path, "instance-b", "quote_tick_0.feather", age_minutes=60)

        code, (out, _err) = _run_cli_with_code(
            ["--catalog", str(tmp_path), "--deadline-seconds", "1"],
            clock_ns=_TickingClock(step_ns=2_000_000_000),
        )

        assert code == EXIT_OK
        assert "failed" not in out
        assert "deferred (deadline; not evaluated)" in out


def _run_cli_with_code(argv: list[str], **kwargs: Any) -> tuple[int, tuple[str, str]]:
    import io

    out, err = io.StringIO(), io.StringIO()
    code = run(argv, stdout=out, stderr=err, **kwargs)
    return code, (out.getvalue(), err.getvalue())
