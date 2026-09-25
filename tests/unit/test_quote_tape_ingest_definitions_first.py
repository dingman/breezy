"""RED-first tests for ING-2 S1: a killed ingest run must still leave every
instrument definition it reached resolvable in the catalog.

Forensics (591ab80b, 2026-09-25 16:50Z): a run instance that died mid-way
through tick conversion left only a ``.converted-quote_tick`` marker on
disk -- no instrument definitions had landed, because the previous
``ingest_instance`` converted whatever ``data_types`` order it was given,
type by type, PER INSTANCE ONLY. The node then resolved zero instruments
and could not trade. :func:`run_ingest_definitions_first` closes the gap
at the level a kill actually happens: EVERY instance's instrument
definitions are converted, across the WHOLE run, before ANY instance's
tick types are attempted -- so a process death partway through pass 2
(tick conversion) can never erase definitions pass 1 already committed.

See ``S1_PLAN_r4.md`` (scratchpad) for the AC/amendment numbering (AC1-AC7,
A1-A7) referenced in test names and comments below.
"""

from __future__ import annotations

import io
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from nautilus_trader.model.data import QuoteTick
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

import breezy.runtime.quote_tape_ingest_cli as ingest_cli_module
from breezy.runtime.quote_tape_ingest_cli import (
    DEFAULT_LIVE_GRACE_MINUTES,
    EXIT_OK,
    MARKER_PREFIX,
    InstanceIngestResult,
    default_convert,
    run,
)
from breezy.runtime.quote_tape_preflight_cli import CATALOG_ENV_VAR
from tests.unit.test_quote_tape_ingest_cli import (
    INSTANCE,
    OTHER_INSTANCE,
    T0,
    _binary_option,
    _never_active,
    _recording_convert,
    _touch,
    _write_instrument_feather,
)

_OLD = DEFAULT_LIVE_GRACE_MINUTES + 5


class _FatalDuringConversion(BaseException):
    """Stands in for a SIGKILL/OOM/os._exit -- never caught by ``ingest_instance``'s
    ``except ValueError``, exactly like the real thing."""


# ---------------------------------------------------------------------------
# AC2 / T1: ingest_instance itself is defs-first, per instance.
# ---------------------------------------------------------------------------


class TestIngestInstanceIsDefinitionsFirst:
    def test_ingest_instance_converts_definitions_before_tick_types(
        self, tmp_path: Path
    ) -> None:
        instance_dir = tmp_path / "live" / INSTANCE
        instance_dir.mkdir(parents=True)
        catalog = ParquetDataCatalog(str(tmp_path))
        calls: list[type] = []

        def spy_convert(
            catalog: ParquetDataCatalog, instance_id: str, data_cls: type, subdirectory: str
        ) -> None:
            calls.append(data_cls)

        # Requested tick-before-def; the conversion ATTEMPT order must
        # still be defs-first.
        result = ingest_cli_module.ingest_instance(
            catalog,
            tmp_path,
            INSTANCE,
            "live",
            (QuoteTick, BinaryOption),
            convert_fn=spy_convert,
        )

        assert calls == [BinaryOption, QuoteTick]
        # AC2: type_results stays in the REQUESTED data_types order.
        assert [r.data_cls for r in result.type_results] == [QuoteTick, BinaryOption]


# ---------------------------------------------------------------------------
# AC1 / T2 / T-order: defs-first across the WHOLE run, independent of
# instance naming/ordering.
# ---------------------------------------------------------------------------


def _assert_all_defs_precede_all_ticks(calls: list[tuple[str, type]]) -> None:
    binary_positions = [i for i, (_iid, cls) in enumerate(calls) if cls is BinaryOption]
    quote_positions = [i for i, (_iid, cls) in enumerate(calls) if cls is QuoteTick]
    assert binary_positions and quote_positions, "fixture must exercise both types"
    assert max(binary_positions) < min(quote_positions), (
        "every BinaryOption conversion must precede every QuoteTick "
        f"conversion; call order was {calls!r}"
    )


class TestDefinitionsForEveryInstancePrecedeAnyTickConversion:
    def test_definitions_for_every_instance_precede_any_tick_conversion(
        self, tmp_path: Path
    ) -> None:
        for instance_id in (INSTANCE, OTHER_INSTANCE):
            _touch(tmp_path, instance_id, "binary_option_0.feather", age_minutes=_OLD)
            _touch(tmp_path, instance_id, "quote_tick_0.feather", age_minutes=_OLD)

        calls: list[tuple[str, type]] = []

        def spy_convert(
            catalog: ParquetDataCatalog, instance_id: str, data_cls: type, subdirectory: str
        ) -> None:
            calls.append((instance_id, data_cls))

        ingest_cli_module.run_ingest_definitions_first(
            tmp_path,
            data_types=(BinaryOption, QuoteTick),
            service_active_probe=_never_active,
            convert_fn=spy_convert,
        )

        _assert_all_defs_precede_all_ticks(calls)

    def test_definitions_first_is_independent_of_instance_order(
        self, tmp_path: Path
    ) -> None:
        # Names deliberately NOT in creation order, so a bug keyed to
        # dict/creation order rather than the sorted instance-id list would
        # surface here.
        first_created, second_created = "zzz-instance", "aaa-instance"
        for instance_id in (first_created, second_created):
            _touch(tmp_path, instance_id, "binary_option_0.feather", age_minutes=_OLD)
            _touch(tmp_path, instance_id, "quote_tick_0.feather", age_minutes=_OLD)

        calls: list[tuple[str, type]] = []

        def spy_convert(
            catalog: ParquetDataCatalog, instance_id: str, data_cls: type, subdirectory: str
        ) -> None:
            calls.append((instance_id, data_cls))

        ingest_cli_module.run_ingest_definitions_first(
            tmp_path,
            data_types=(BinaryOption, QuoteTick),
            service_active_probe=_never_active,
            convert_fn=spy_convert,
        )

        _assert_all_defs_precede_all_ticks(calls)


# ---------------------------------------------------------------------------
# AC3 / T3a / T3b: a hard kill mid tick-conversion leaves definitions
# resolvable.
# ---------------------------------------------------------------------------


class TestAKillDuringTickConversionLeavesInstrumentsResolvable:
    def test_kill_during_tick_conversion_leaves_instruments_resolvable(
        self, tmp_path: Path
    ) -> None:
        _write_instrument_feather(
            tmp_path, INSTANCE, "binary_option_0.feather", [_binary_option("MKT-A", T0)]
        )
        _touch(tmp_path, INSTANCE, "quote_tick_0.feather", age_minutes=_OLD)

        def convert_fn(
            catalog: ParquetDataCatalog, instance_id: str, data_cls: type, subdirectory: str
        ) -> str | None:
            if data_cls is QuoteTick:
                raise _FatalDuringConversion("simulated hard kill mid tick conversion")
            return default_convert(catalog, instance_id, data_cls, subdirectory)

        with pytest.raises(_FatalDuringConversion):
            ingest_cli_module.run_ingest_definitions_first(
                tmp_path,
                data_types=(BinaryOption, QuoteTick),
                service_active_probe=_never_active,
                convert_fn=convert_fn,
            )

        instance_dir = tmp_path / "live" / INSTANCE
        assert (instance_dir / f"{MARKER_PREFIX}binary_option").exists()
        catalog = ParquetDataCatalog(str(tmp_path))
        instrument_values = {inst.id.value for inst in catalog.instruments()}
        assert "MKT-A.POLYUS" in instrument_values

    def test_kill_during_tick_conversion_leaves_instruments_resolvable_subprocess_os_exit(
        self, tmp_path: Path
    ) -> None:
        """The in-process BaseException above proves the MECHANISM; this
        proves it survives an actual OS-level process death, in a real
        subprocess -- exactly like ``tests/contract/test_quote_tape_unclean_
        shutdown.py``'s ``_sigkill_a_real_writer`` proves the writer side."""
        _write_instrument_feather(
            tmp_path, INSTANCE, "binary_option_0.feather", [_binary_option("MKT-B", T0)]
        )
        _touch(tmp_path, INSTANCE, "quote_tick_0.feather", age_minutes=_OLD)

        worktree_src = os.environ.get("PYTHONPATH", "")
        assert worktree_src, "PYTHONPATH must be set to the worktree's src/ for this test"
        breezy_python = os.environ.get("BREEZY_PYTHON", sys.executable)

        child = tmp_path / "child_t3b.py"
        child.write_text(_T3B_CHILD)

        child_env = dict(os.environ)
        child_env["PYTHONPATH"] = worktree_src

        completed = subprocess.run(
            [breezy_python, str(child), str(tmp_path), "live", worktree_src],
            capture_output=True,
            text=True,
            timeout=120,
            env=child_env,
            check=False,
        )
        assert completed.returncode == 1, (
            "child must die via os._exit(1) for this test to mean anything; "
            f"rc={completed.returncode} stdout={completed.stdout!r} "
            f"stderr={completed.stderr!r}"
        )
        assert "POSITIVE CONTROL OK" in completed.stdout, (
            f"child never reached its own positive control: {completed.stdout!r} "
            f"{completed.stderr!r}"
        )

        instance_dir = tmp_path / "live" / INSTANCE
        assert (instance_dir / f"{MARKER_PREFIX}binary_option").exists()
        catalog = ParquetDataCatalog(str(tmp_path))
        instrument_values = {inst.id.value for inst in catalog.instruments()}
        assert "MKT-B.POLYUS" in instrument_values


_T3B_CHILD = '''
import os
import sys
from pathlib import Path

import breezy

expected_prefix = sys.argv[3]
assert breezy.__file__.startswith(expected_prefix), (
    f"positive control failed: breezy loaded from {breezy.__file__!r}, "
    f"expected worktree prefix {expected_prefix!r}"
)
print("POSITIVE CONTROL OK", breezy.__file__)
sys.stdout.flush()  # os._exit() below skips the normal atexit flush

from nautilus_trader.model.data import QuoteTick
from nautilus_trader.model.instruments import BinaryOption

from breezy.runtime.quote_tape_ingest_cli import default_convert, run_ingest_definitions_first

catalog_root = Path(sys.argv[1])
subdirectory = sys.argv[2]


def convert_fn(catalog, instance_id, data_cls, subdirectory):
    if data_cls is QuoteTick:
        os._exit(1)
    return default_convert(catalog, instance_id, data_cls, subdirectory)


run_ingest_definitions_first(
    catalog_root,
    subdirectory=subdirectory,
    data_types=(BinaryOption, QuoteTick),
    service_active_probe=lambda: False,
    convert_fn=convert_fn,
)
'''


# ---------------------------------------------------------------------------
# AC4 / T-E2E: a dead instance A's kill does not hide instance B's defs.
# ---------------------------------------------------------------------------


class TestDeadInstanceAKillDoesNotHideInstanceBDefinitions:
    def test_dead_instance_a_kill_does_not_hide_instance_b_definitions(
        self, tmp_path: Path
    ) -> None:
        _write_instrument_feather(
            tmp_path, INSTANCE, "binary_option_0.feather", [_binary_option("MKT-A", T0)]
        )
        _touch(tmp_path, INSTANCE, "quote_tick_0.feather", age_minutes=_OLD)
        _write_instrument_feather(
            tmp_path, OTHER_INSTANCE, "binary_option_0.feather", [_binary_option("MKT-B", T0)]
        )
        _touch(tmp_path, OTHER_INSTANCE, "quote_tick_0.feather", age_minutes=_OLD)

        def convert_fn(
            catalog: ParquetDataCatalog, instance_id: str, data_cls: type, subdirectory: str
        ) -> str | None:
            if instance_id == INSTANCE and data_cls is QuoteTick:
                raise _FatalDuringConversion("instance A dies mid tick conversion")
            return default_convert(catalog, instance_id, data_cls, subdirectory)

        with pytest.raises(_FatalDuringConversion):
            ingest_cli_module.run_ingest_definitions_first(
                tmp_path,
                data_types=(BinaryOption, QuoteTick),
                service_active_probe=_never_active,
                convert_fn=convert_fn,
            )

        catalog = ParquetDataCatalog(str(tmp_path))
        instrument_values = {inst.id.value for inst in catalog.instruments()}
        assert "MKT-A.POLYUS" in instrument_values, "A's own defs landed before it died"
        assert "MKT-B.POLYUS" in instrument_values, "B's defs are untouched by A's death"


# ---------------------------------------------------------------------------
# AC5 / A6 / T-live / T-newest-subset: one shared snapshot, never
# recomputed from a narrowed pass-1 subset.
# ---------------------------------------------------------------------------


class TestOpenDefinitionsFileStaysSkippedAcrossBothPasses:
    def test_open_definitions_file_stays_skipped_across_both_passes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        live_instance = "live-instance"
        _touch(tmp_path, live_instance, "binary_option_0.feather", age_minutes=0.0)

        probe_calls: list[bool] = []

        def spy_probe() -> bool:
            probe_calls.append(True)
            return True

        newest_calls: list[Any] = []
        real_newest = ingest_cli_module._newest_started_instance_id

        def spy_newest(*args: Any, **kwargs: Any) -> str | None:
            newest_calls.append(1)
            return real_newest(*args, **kwargs)

        monkeypatch.setattr(ingest_cli_module, "_newest_started_instance_id", spy_newest)

        calls: list[tuple[str, type]] = []

        def convert_fn(
            catalog: ParquetDataCatalog, instance_id: str, data_cls: type, subdirectory: str
        ) -> None:
            calls.append((instance_id, data_cls))

        results = ingest_cli_module.run_ingest_definitions_first(
            tmp_path,
            data_types=(BinaryOption,),
            service_active_probe=spy_probe,
            convert_fn=convert_fn,
        )

        assert len(probe_calls) == 1, "the recorder probe must be queried once for the run"
        assert len(newest_calls) == 1, "the newest-instance scan must run once for the run"
        assert calls == [], "an open definitions file must never be converted, either pass"
        assert len(results) == 1
        assert results[0].instance_id == live_instance
        assert results[0].outcome == "skipped-live"


class TestNewestInstanceIsComputedOverAllIdsNotTheSelection:
    def test_newest_instance_is_computed_over_all_ids_not_the_selection(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        live_newest = "z-live-newest"
        dead_selected = "a-dead-selected"
        _touch(tmp_path, live_newest, "binary_option_0.feather", age_minutes=0.0)
        _touch(tmp_path, dead_selected, "binary_option_0.feather", age_minutes=_OLD)

        seen_newest: list[str | None] = []
        real_open_files = ingest_cli_module._open_files_for_instance

        def spy_open_files(*args: Any, **kwargs: Any) -> frozenset[Path]:
            seen_newest.append(kwargs.get("newest_instance_id"))
            return real_open_files(*args, **kwargs)

        monkeypatch.setattr(ingest_cli_module, "_open_files_for_instance", spy_open_files)

        results = ingest_cli_module.run_ingest_definitions_first(
            tmp_path,
            data_types=(BinaryOption,),
            service_active_probe=lambda: True,
            convert_fn=_recording_convert([]),
        )

        assert seen_newest, "expected _open_files_for_instance to be exercised"
        assert set(seen_newest) == {live_newest}, (
            "every liveness check -- pass 1's narrowed call included -- must "
            f"use the newest id computed over ALL instances; saw {seen_newest!r}"
        )
        by_id = {r.instance_id: r for r in results}
        # The dead, correctly-non-current instance actually converts.
        assert by_id[dead_selected].type_results[0].outcome != "skipped-open"


# ---------------------------------------------------------------------------
# A5 / T-scan-count: pass 1 scans only instances that genuinely need it.
# ---------------------------------------------------------------------------


class TestDefinitionPassScansOnlyInstancesNeedingDefinitions:
    def test_definition_pass_scans_only_instances_needing_definitions(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        defs_marked = "defs-marked"
        live_open_defs = "live-open-defs"
        dead_unconverted = "dead-unconverted"
        grace_tick = "grace-tick"

        _touch(tmp_path, defs_marked, "binary_option_0.feather", age_minutes=_OLD)
        _touch(tmp_path, defs_marked, "quote_tick_0.feather", age_minutes=_OLD)
        (tmp_path / "live" / defs_marked / f"{MARKER_PREFIX}binary_option").touch()

        _touch(tmp_path, live_open_defs, "binary_option_0.feather", age_minutes=0.0)

        _touch(tmp_path, dead_unconverted, "binary_option_0.feather", age_minutes=_OLD)
        _touch(tmp_path, dead_unconverted, "quote_tick_0.feather", age_minutes=_OLD)

        _touch(tmp_path, grace_tick, "binary_option_0.feather", age_minutes=_OLD)
        (tmp_path / "live" / grace_tick / f"{MARKER_PREFIX}binary_option").touch()
        grace_tick_path = tmp_path / "live" / grace_tick / "quote_tick_0.feather"

        def _touch_fresh(path: Path) -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()

        scans: list[str] = []
        real_scan = ingest_cli_module.scan_instance

        def spy_scan(*args: Any, **kwargs: Any) -> Any:
            scans.append(args[1] if len(args) > 1 else kwargs["instance_id"])
            return real_scan(*args, **kwargs)

        monkeypatch.setattr(ingest_cli_module, "scan_instance", spy_scan)

        calls: list[tuple[str, type]] = []
        _touch_fresh(grace_tick_path)

        ingest_cli_module.run_ingest_definitions_first(
            tmp_path,
            data_types=(BinaryOption, QuoteTick),
            service_active_probe=lambda: True,  # only live_open_defs is newest+active
            convert_fn=_recording_convert(calls),
        )

        run1_counts = {
            instance_id: scans.count(instance_id)
            for instance_id in (defs_marked, live_open_defs, dead_unconverted, grace_tick)
        }
        assert run1_counts[defs_marked] == 1
        assert run1_counts[live_open_defs] == 1
        assert run1_counts[dead_unconverted] == 2
        assert run1_counts[grace_tick] == 1

        scans.clear()
        _touch_fresh(grace_tick_path)

        ingest_cli_module.run_ingest_definitions_first(
            tmp_path,
            data_types=(BinaryOption, QuoteTick),
            service_active_probe=lambda: True,
            convert_fn=_recording_convert(calls),
        )

        run2_counts = {
            instance_id: scans.count(instance_id)
            for instance_id in (dead_unconverted, grace_tick)
        }
        assert run2_counts[dead_unconverted] == 0, "fully converted -- must skip the rescan"
        assert run2_counts[grace_tick] == 1, "still open -- scanned once, only in pass 2"


# ---------------------------------------------------------------------------
# T-pass1-kill: a BaseException in the definitions pass skips pass 2
# entirely and is cleanly retried next run.
# ---------------------------------------------------------------------------


class TestBaseExceptionInDefinitionPassSkipsPassTwo:
    def test_base_exception_in_definition_pass_skips_pass_two_and_retries_next_run(
        self, tmp_path: Path
    ) -> None:
        _touch(tmp_path, INSTANCE, "binary_option_0.feather", age_minutes=_OLD)
        _touch(tmp_path, INSTANCE, "quote_tick_0.feather", age_minutes=_OLD)

        calls: list[type] = []

        def dying_convert(
            catalog: ParquetDataCatalog, instance_id: str, data_cls: type, subdirectory: str
        ) -> None:
            calls.append(data_cls)
            if data_cls is BinaryOption:
                raise _FatalDuringConversion("simulated fatal kill during definitions pass")

        with pytest.raises(_FatalDuringConversion):
            ingest_cli_module.run_ingest_definitions_first(
                tmp_path,
                data_types=(BinaryOption, QuoteTick),
                service_active_probe=_never_active,
                convert_fn=dying_convert,
            )

        assert calls == [BinaryOption], "pass 2 must never run once pass 1 dies"
        instance_dir = tmp_path / "live" / INSTANCE
        assert not (instance_dir / f"{MARKER_PREFIX}binary_option").exists()
        assert not (instance_dir / f"{MARKER_PREFIX}quote_tick").exists()

        calls.clear()

        def ok_convert(
            catalog: ParquetDataCatalog, instance_id: str, data_cls: type, subdirectory: str
        ) -> None:
            calls.append(data_cls)

        ingest_cli_module.run_ingest_definitions_first(
            tmp_path,
            data_types=(BinaryOption, QuoteTick),
            service_active_probe=_never_active,
            convert_fn=ok_convert,
        )

        assert calls[0] is BinaryOption, "the unmarked instance is reselected next run"
        assert (instance_dir / f"{MARKER_PREFIX}binary_option").exists()
        assert (instance_dir / f"{MARKER_PREFIX}quote_tick").exists()


# ---------------------------------------------------------------------------
# T-dry-run: dry-run is a single pass, output identical to plain run_ingest.
# ---------------------------------------------------------------------------


class TestDryRunIsSinglePassAndOutputIdentical:
    def test_dry_run_is_single_pass_and_output_identical(self, tmp_path: Path) -> None:
        _touch(tmp_path, INSTANCE, "binary_option_0.feather", age_minutes=_OLD)
        _touch(tmp_path, INSTANCE, "quote_tick_0.feather", age_minutes=_OLD)

        direct = ingest_cli_module.run_ingest(
            tmp_path,
            data_types=(BinaryOption, QuoteTick),
            service_active_probe=_never_active,
            dry_run=True,
        )
        wrapped = ingest_cli_module.run_ingest_definitions_first(
            tmp_path,
            data_types=(BinaryOption, QuoteTick),
            service_active_probe=_never_active,
            dry_run=True,
        )

        assert wrapped == direct
        # No side effects: dry-run must never write a marker either way.
        instance_dir = tmp_path / "live" / INSTANCE
        assert not (instance_dir / f"{MARKER_PREFIX}binary_option").exists()
        assert not (instance_dir / f"{MARKER_PREFIX}quote_tick").exists()


# ---------------------------------------------------------------------------
# T-exit3: a failure confined to pass 1 still reports "failed", one line
# per instance, even if pass 2's own retry of that type succeeds.
# ---------------------------------------------------------------------------


class TestFailureOnlyInPassOneStillReportsFailed:
    def test_failure_only_in_pass_one_exits_3_with_one_line_per_instance(
        self, tmp_path: Path
    ) -> None:
        _touch(tmp_path, INSTANCE, "binary_option_0.feather", age_minutes=_OLD)
        _touch(tmp_path, OTHER_INSTANCE, "binary_option_0.feather", age_minutes=_OLD)

        attempts: dict[str, int] = {}

        def flaky_then_ok(
            catalog: ParquetDataCatalog, instance_id: str, data_cls: type, subdirectory: str
        ) -> None:
            attempts[instance_id] = attempts.get(instance_id, 0) + 1
            if instance_id == INSTANCE and attempts[instance_id] == 1:
                raise ValueError("simulated definitions-pass failure")

        results = ingest_cli_module.run_ingest_definitions_first(
            tmp_path,
            data_types=(BinaryOption,),
            service_active_probe=_never_active,
            convert_fn=flaky_then_ok,
        )

        assert len(results) == 2, "one line per instance"
        by_id = {r.instance_id: r for r in results}
        assert by_id[INSTANCE].outcome == "failed"
        assert "definitions pass failed" in by_id[INSTANCE].reason
        assert by_id[OTHER_INSTANCE].outcome == "converted"
        assert any(r.outcome == "failed" for r in results), "drives EXIT_CONVERSION_FAILED"


# ---------------------------------------------------------------------------
# T-merge: the merge function in isolation.
# ---------------------------------------------------------------------------


class TestMergePassResults:
    def test_pass_two_wins_except_when_pass_one_failed(self) -> None:
        p1_ok = InstanceIngestResult(INSTANCE, "converted")
        p1_failed = InstanceIngestResult(OTHER_INSTANCE, "failed", reason="boom")
        p2_a = InstanceIngestResult(INSTANCE, "converted")
        p2_b = InstanceIngestResult(OTHER_INSTANCE, "converted")

        merged = ingest_cli_module._merge_pass_results((p1_ok, p1_failed), (p2_a, p2_b))

        assert merged == (
            p2_a,
            InstanceIngestResult(
                OTHER_INSTANCE,
                "failed",
                reason="definitions pass failed; boom",
                type_results=p2_b.type_results,
            ),
        )

    def test_pass_two_empty_type_results_fall_back_to_pass_one(self) -> None:
        from breezy.runtime.quote_tape_ingest_cli import TypeConversionResult

        p1_failed = InstanceIngestResult(
            INSTANCE,
            "failed",
            reason="boom",
            type_results=(TypeConversionResult(BinaryOption, "failed", "boom"),),
        )
        p2_empty = InstanceIngestResult(INSTANCE, "converted", type_results=())

        merged = ingest_cli_module._merge_pass_results((p1_failed,), (p2_empty,))

        assert merged[0].type_results == p1_failed.type_results


# ---------------------------------------------------------------------------
# T-run: run() routes through run_ingest_definitions_first.
# ---------------------------------------------------------------------------


class TestRunRoutesThroughDefinitionsFirst:
    def test_run_routes_through_definitions_first(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        called: list[Any] = []

        def spy(*args: Any, **kwargs: Any) -> tuple[InstanceIngestResult, ...]:
            called.append((args, kwargs))
            return ()

        monkeypatch.setattr(ingest_cli_module, "run_ingest_definitions_first", spy)

        out, err = io.StringIO(), io.StringIO()
        code = run([], env={CATALOG_ENV_VAR: str(tmp_path)}, stdout=out, stderr=err)

        assert called, "run() must dispatch through run_ingest_definitions_first"
        assert code == EXIT_OK


# ---------------------------------------------------------------------------
# A3: snapshot and now_ns are mutually exclusive.
# ---------------------------------------------------------------------------


class TestSnapshotAndNowNsAreMutuallyExclusive:
    def test_run_ingest_with_both_snapshot_and_now_ns_raises_value_error(
        self, tmp_path: Path
    ) -> None:
        _touch(tmp_path, INSTANCE, "quote_tick_0.feather", age_minutes=_OLD)
        snap = ingest_cli_module.take_liveness_snapshot(
            tmp_path, "live", service_active_probe=_never_active
        )

        with pytest.raises(ValueError, match="mutually exclusive"):
            ingest_cli_module.run_ingest(
                tmp_path,
                data_types=(QuoteTick,),
                snapshot=snap,
                now_ns=1,
            )
