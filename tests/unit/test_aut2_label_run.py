"""AUT-2 r7 WP6 / sections 3.7.3 and 3.12: the label run, its marker, exits and the unit guards."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from breezy.analysis.labeling import label_core
from breezy.analysis.labeling.constants import SLOT_GUARD_REFUSED_RC  # noqa: F401 - pin import
from breezy.analysis.labeling.label_core import FamilyInfo, InputPlan, run_labels
from breezy.analysis.labeling.label_run import (
    LABEL_UNIT,
    UnitContext,
    default_paths,
    main,
    read_cgroup_memory_peak,
    run_unit,
)
from breezy.analysis.labeling.memory_gate import Aut6Reading
from breezy.persistence.autonomy.label_store import RunOutcome, read_labels, read_newest_marker
from breezy.persistence.autonomy.plugin import RefusingPlugin
from tests.support.aut2_fixtures import HOUR_NS
from tests.support.aut2_run_fixtures import (
    FAMILY,
    FQ_KIND,
    NOW_NS,
    DroppingPlugin,
    FqPlugin,
    RecordingPlugin,
    Sink,
    make_deps,
    marker_files,
    verdict_wires,
)

_IN_UNIT = UnitContext(invocation_id="inv-1", cgroup_path=f"/user.slice/{LABEL_UNIT}.service")


def _summary(lines: tuple[str, ...]) -> str:
    (line,) = [ln for ln in lines if ln.startswith("LABEL_OUTCOMES run_outcome=")]
    return line


# -- the plug-in registry and the refusal rule -----------------------------------------------------


def test_iterates_offline_plugins_not_family_list(tmp_path: Path) -> None:
    first, second = RecordingPlugin(), RecordingPlugin()
    deps = make_deps(
        tmp_path,
        registry={"kind_a": first, "kind_b": second},
        families=lambda: (FamilyInfo("fam_a", "kind_a", retired=False),),
        plan=lambda fills: InputPlan(inputs_by_kind={"kind_a": ()}, fill_kinds={}),
    )

    run_labels(deps)

    assert len(first.batches) == 1 and len(second.batches) == 1  # every registered plug-in runs


def test_refusing_plugin_for_non_retired_family_fails_run_no_marker(tmp_path: Path) -> None:
    sink = Sink()
    deps = make_deps(tmp_path, registry={FQ_KIND: RefusingPlugin()}, deliver=sink)

    result = run_labels(deps)

    assert result.exit_code == 1 and result.run_outcome is None
    assert marker_files(deps.data_root) == []
    assert not (deps.data_root / "derived" / "labels").exists()
    assert "aut2.refusing_scorer" in sink.events


def test_a_refusing_plugin_may_refuse_for_a_retired_family_with_nothing_unlabelled(
    tmp_path: Path,
) -> None:
    deps = make_deps(
        tmp_path,
        n_fills=0,
        registry={"current_rung_hold": RefusingPlugin()},
        families=lambda: (FamilyInfo("old_crh", "current_rung_hold", retired=True),),
        plan=lambda fills: InputPlan(inputs_by_kind={}, fill_kinds={}),
    )

    result = run_labels(deps)

    assert result.exit_code == 0 and result.run_outcome is RunOutcome.NO_INPUT


def test_a_retired_family_with_an_unlabelled_fill_keeps_its_real_scorer_requirement(
    tmp_path: Path,
) -> None:
    deps = make_deps(
        tmp_path,
        registry={"current_rung_hold": RefusingPlugin()},
        families=lambda: (FamilyInfo("old_crh", "current_rung_hold", retired=True),),
        plan=lambda fills: InputPlan(
            inputs_by_kind={}, fill_kinds={f.client_order_id: "current_rung_hold" for f in fills}
        ),
    )

    result = run_labels(deps)

    assert result.exit_code == 1 and marker_files(deps.data_root) == []


# -- outcome and marker ---------------------------------------------------------------------------


def test_labelled_run_writes_rows_then_the_marker_with_counts(tmp_path: Path) -> None:
    deps = make_deps(tmp_path)

    result = run_labels(deps)

    assert result.exit_code == 0 and result.run_outcome is RunOutcome.LABELLED
    marker = read_newest_marker(deps.data_root)
    assert marker is not None
    assert (marker.durable_fill_count, marker.labelled_final) == (2, 2)
    assert (marker.pending, marker.unresolved, marker.missing_label) == (0, 0, 0)
    assert marker.durable_fill_count_prev is None and marker.written_at_ns == NOW_NS
    assert len(read_labels(deps.data_root, FAMILY)) == 2


def test_marker_carries_counts(tmp_path: Path) -> None:
    result = run_labels(make_deps(tmp_path, settled=False))

    marker = read_newest_marker(tmp_path / "data")
    assert marker is not None
    assert (marker.pending, marker.open, marker.labelled_final) == (2, 0, 0)
    assert (marker.p_null_count, marker.non_c1_post_epoch_count) == (0, 0)
    assert result.run_outcome is RunOutcome.LABELLED  # rows were written, so not PENDING


def test_no_input_only_when_pending_unresolved_missing_zero(tmp_path: Path) -> None:
    result = run_labels(make_deps(tmp_path, n_fills=0, plan=lambda f: InputPlan({}, {})))

    assert result.exit_code == 0 and result.run_outcome is RunOutcome.NO_INPUT
    marker = read_newest_marker(tmp_path / "data")
    assert marker is not None and marker.run_outcome is RunOutcome.NO_INPUT


def test_zero_rows_with_pending_is_pending_not_no_input(tmp_path: Path) -> None:
    run_labels(make_deps(tmp_path, settled=False))
    again = make_deps(tmp_path, n_fills=None, settled=False, now_ns=NOW_NS + HOUR_NS)

    result = run_labels(again)

    assert result.run_outcome is RunOutcome.PENDING
    marker = read_newest_marker(tmp_path / "data")
    assert marker is not None and marker.pending == 2 and marker.durable_fill_count_prev == 2


def test_identity_breach_writes_failed_identity_marker(tmp_path: Path) -> None:
    from breezy.analysis.labeling.attribution import unresolved_row_of
    from tests.support.aut2_run_fixtures import fq_planner

    sink = Sink()

    def planner(fills: Any) -> InputPlan:
        kept = [f for f in fills if f.venue_order_id != "vo-2"]
        lost = [f for f in fills if f.venue_order_id == "vo-2"]
        return replace(
            fq_planner(kept),
            unresolved=tuple(unresolved_row_of(f, None, ["no_order_link"]) for f in lost),
            unresolved_fill_keys=frozenset(f.venue_order_id for f in lost),
        )

    result = run_labels(make_deps(tmp_path, deliver=sink, plan=planner))

    assert result.exit_code == 0 and result.run_outcome is RunOutcome.FAILED_IDENTITY
    marker = read_newest_marker(tmp_path / "data")
    assert marker is not None and marker.unresolved == 1
    assert "aut2.unresolved_fill" in sink.events and "aut2.identity_breach" in sink.events
    journal = list(
        (tmp_path / "data" / "evidence" / "aut2" / "unresolved").rglob("*_label_run.json")
    )
    assert len(journal) == 1


def test_scorer_silently_dropping_a_fill_is_missing_label(tmp_path: Path) -> None:
    sink = Sink()
    deps = make_deps(tmp_path, registry={FQ_KIND: DroppingPlugin()}, deliver=sink)

    result = run_labels(deps)

    assert result.run_outcome is RunOutcome.FAILED_IDENTITY
    marker = read_newest_marker(deps.data_root)
    assert marker is not None and marker.missing_label == 1
    assert "aut2.identity_breach" in sink.events


def test_durable_fill_count_decrease_is_failed_identity(tmp_path: Path) -> None:
    run_labels(make_deps(tmp_path))
    (tmp_path / "exec.sqlite").unlink()
    smaller = make_deps(tmp_path, n_fills=1, now_ns=NOW_NS + HOUR_NS)

    result = run_labels(smaller)

    assert result.run_outcome is RunOutcome.FAILED_IDENTITY
    marker = read_newest_marker(tmp_path / "data")
    assert marker is not None and marker.durable_fill_count_prev == 2


def test_unresolved_and_missing_label_fail_reconciliation(tmp_path: Path) -> None:
    run_labels(make_deps(tmp_path, registry={FQ_KIND: DroppingPlugin()}))

    recon = [
        v for v in verdict_wires(tmp_path / "data") if v.get("detector") == "aut2.reconciliation"
    ]

    assert recon and all(v["outcome"] == "FAIL" for v in recon)


def test_marker_written_last_and_write_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    order: list[str] = []
    real_marker = label_core.write_marker  # type: ignore[attr-defined]
    real_labels = label_core.write_labels  # type: ignore[attr-defined]

    def _marker(*args: Any, **kwargs: Any) -> Any:
        data_root = args[0]
        order.append("marker")
        assert list(data_root.joinpath("derived", "labels").rglob("*.parquet"))
        assert list(data_root.joinpath("derived", "verdicts").rglob("*.json"))
        return real_marker(*args, **kwargs)

    def _labels(*args: Any, **kwargs: Any) -> Any:
        order.append("labels")
        return real_labels(*args, **kwargs)

    monkeypatch.setattr(label_core, "write_marker", _marker)
    monkeypatch.setattr(label_core, "write_labels", _labels)
    deps = make_deps(tmp_path)

    run_labels(deps)
    (marker,) = marker_files(deps.data_root)
    before = marker.read_bytes()
    again = run_labels(deps)  # the same clock tick again: a write-once marker is never overwritten

    assert order[-1] == "marker" and order.index("labels") < order.index("marker")
    assert again.exit_code == 1 and marker.read_bytes() == before
    assert marker_files(deps.data_root) == [marker]


def test_stdout_carries_label_outcomes_summary_line(tmp_path: Path) -> None:
    result = run_labels(make_deps(tmp_path))

    assert _summary(result.lines) == (
        "LABEL_OUTCOMES run_outcome=LABELLED durable_fill_count=2 labelled_final=2 "
        "pending=0 unresolved=0 missing_label=0"
    )


# -- unreadable inputs ----------------------------------------------------------------------------


def test_unreadable_exec_store_exits_nonzero_without_marker(tmp_path: Path) -> None:
    sink = Sink()
    deps = make_deps(tmp_path, n_fills=None, deliver=sink)

    result = run_labels(deps)

    assert result.exit_code == 1 and marker_files(deps.data_root) == []
    assert "aut2.label_input_unreadable" in sink.events


def test_unreadable_label_store_exits_nonzero(tmp_path: Path) -> None:
    deps = make_deps(tmp_path)
    run_labels(deps)
    labels = next((deps.data_root / "derived" / "labels" / FAMILY).glob("labels_*.parquet"))
    labels.chmod(0o600)
    labels.write_bytes(b"not parquet")
    later = make_deps(tmp_path, n_fills=None, now_ns=NOW_NS + HOUR_NS)

    result = run_labels(later)

    assert result.exit_code == 1
    assert len(marker_files(deps.data_root)) == 1  # no second marker


def test_a_corrupt_prior_marker_exits_nonzero_without_a_new_marker(tmp_path: Path) -> None:
    deps = make_deps(tmp_path)
    run_labels(deps)
    marker = marker_files(deps.data_root)[0]
    marker.write_bytes(b"{")

    result = run_labels(make_deps(tmp_path, n_fills=None, now_ns=NOW_NS + HOUR_NS))

    assert result.exit_code == 1 and len(marker_files(deps.data_root)) == 1


# -- lag, delivery -----------------------------------------------------------------------------


def test_label_lag_fail_exits_zero_with_verdict_and_critical(tmp_path: Path) -> None:
    sink = Sink()
    old = NOW_NS - 30 * HOUR_NS
    deps = make_deps(tmp_path, settled=False, deliver=sink, lag_start_ns=lambda _f: old)

    result = run_labels(deps)

    assert result.exit_code == 0
    lag = [v for v in verdict_wires(deps.data_root) if v.get("detector") == "aut2.label_lag"]
    assert lag and lag[0]["outcome"] == "FAIL"
    assert "aut2.label_lag" in sink.events


def test_label_run_delivery_failure_exits_nonzero(tmp_path: Path) -> None:
    deps = make_deps(tmp_path, registry={FQ_KIND: DroppingPlugin()}, deliver=Sink(fail=True))

    result = run_labels(deps)

    assert result.exit_code == 4
    assert any(ln.startswith("AUT2 DELIVERY_FAILED event=") for ln in result.lines)
    assert len(marker_files(deps.data_root)) == 1  # every durable write happened first


def test_a_repeated_critical_is_delivered_once_per_day(tmp_path: Path) -> None:
    sink = Sink()
    deps = make_deps(tmp_path, registry={FQ_KIND: DroppingPlugin()}, deliver=sink)
    run_labels(deps)
    first = len(sink.payloads)

    run_labels(replace(deps, now_ns=NOW_NS + 1))

    assert first >= 1 and len(sink.payloads) == first


# -- the unit: lock, hold, guards -----------------------------------------------------------------


class _Lock:
    def __init__(self, timed_out: bool) -> None:
        self.timed_out = timed_out
        self.acquired = 0

    def acquire(self, wait_s: float) -> bool:
        self.acquired += 1
        return not self.timed_out

    def release(self) -> None:
        pass


def _unit(deps: Any, **over: Any) -> Any:
    args: dict[str, Any] = {
        "lock": _Lock(False),
        "unit_max_bytes": 2 * 1024**3,
        "aut6": Aut6Reading("pass", "v" * 64),
        "measured_peak_bytes": None,
        "proof_window": None,
        "slot_ns": NOW_NS,
    }
    args.update(over)
    return run_unit(deps, **args)


def test_label_flock_timeout_skips_exit_zero_and_second_consecutive_is_critical(
    tmp_path: Path,
) -> None:
    sink = Sink()
    deps = make_deps(tmp_path, deliver=sink)

    first = _unit(deps, lock=_Lock(True))
    second = _unit(replace(deps, now_ns=NOW_NS + HOUR_NS), lock=_Lock(True))

    assert first.exit_code == 0 and second.exit_code == 0
    assert "LABEL_OUTCOMES SKIPPED reason=lock" in first.lines
    assert marker_files(deps.data_root) == []
    assert sink.events.count("aut2.lock_skips_consecutive") == 1  # only the second slot
    skips = list(
        (deps.data_root / "evidence" / "aut2" / "skips").rglob("*_breezy-label-outcomes.json")
    )
    assert len(skips) == 2


def test_marker_after_skip_resets_consecutive(tmp_path: Path) -> None:
    sink = Sink()
    deps = make_deps(tmp_path, deliver=sink)
    _unit(deps, lock=_Lock(True))
    ran = _unit(replace(deps, now_ns=NOW_NS + HOUR_NS))  # a run with a marker breaks the streak
    third = _unit(replace(deps, now_ns=NOW_NS + 2 * HOUR_NS), lock=_Lock(True))

    assert ran.exit_code == 0 and third.exit_code == 0
    assert "aut2.lock_skips_consecutive" not in sink.events


def test_record_skip_write_failure_exits_nonzero(tmp_path: Path) -> None:
    deps = make_deps(tmp_path)
    blocker = deps.data_root / "evidence"
    blocker.write_text("a file where the journal directory must be")

    result = _unit(deps, lock=_Lock(True))

    assert result.exit_code == 1
    assert "AUT2 SKIP_JOURNAL_WRITE_FAILED unit=breezy-label-outcomes" in result.lines
    assert marker_files(deps.data_root) == []


class _Boom(FqPlugin):
    def label(self, capture_day: Any, batch: Any, settlements: Any) -> Any:
        raise AssertionError("the scorer must not start while the slot is held")


def test_held_slot_writes_hold_journal_delivers_health_line_and_skips_scorer(
    tmp_path: Path,
) -> None:
    sink = Sink()
    deps = make_deps(tmp_path, registry={FQ_KIND: _Boom()}, deliver=sink)

    result = _unit(deps, unit_max_bytes=6 * 1024**3, aut6=Aut6Reading("missing"))

    assert result.exit_code == 0
    line = "AUT2 HEALTH label_timer_held cause=memory_gate unit=breezy-label-outcomes"
    assert line in result.lines
    assert sink.payloads and sink.payloads[0]["event"] == "aut2.label_timer_held"
    holds = list((deps.data_root / "evidence" / "aut2" / "holds").rglob("*_label-outcomes.json"))
    assert len(holds) == 1
    assert json.loads(holds[0].read_text())["reason"] == "verdict_missing"


def test_held_slot_writes_no_marker(tmp_path: Path) -> None:
    deps = make_deps(tmp_path)

    _unit(deps, unit_max_bytes=6 * 1024**3, aut6=Aut6Reading("not_pass", "n" * 64))

    assert marker_files(deps.data_root) == []
    assert not (deps.data_root / "derived" / "labels").exists()


def test_held_slot_delivery_failure_exits_four_after_the_journal(tmp_path: Path) -> None:
    deps = make_deps(tmp_path, deliver=Sink(fail=True))

    result = _unit(deps, unit_max_bytes=6 * 1024**3, aut6=Aut6Reading("missing"))

    assert result.exit_code == 4
    assert list((deps.data_root / "evidence" / "aut2" / "holds").rglob("*.json"))


def test_sizing_above_cap_hold_delivers_the_named_critical(tmp_path: Path) -> None:
    sink = Sink()
    deps = make_deps(tmp_path, deliver=sink)

    _unit(deps, measured_peak_bytes=int(9.5 * 1024**3), unit_max_bytes=14 * 1024**3)

    assert "aut2.label_memory_sizing_exceeds_cap" in sink.events


def test_label_wrapper_invokes_proof_window_after_marker(tmp_path: Path) -> None:
    order: list[str] = []
    hook_args: list[Any] = []

    def proof(data_root: Path, now_ns: int) -> None:
        order.append("proof")
        hook_args.append(read_newest_marker(data_root))

    deps = make_deps(tmp_path)

    result = _unit(deps, proof_window=proof)

    assert result.exit_code == 0 and order == ["proof"]
    assert hook_args[0] is not None  # the marker exists before the proof window runs
    held = _unit(
        make_deps(tmp_path / "h"),
        proof_window=proof,
        unit_max_bytes=6 * 1024**3,
        aut6=Aut6Reading("missing"),
    )
    skipped = _unit(make_deps(tmp_path / "s"), proof_window=proof, lock=_Lock(True))
    assert held.exit_code == 0 and skipped.exit_code == 0
    assert order == ["proof"]  # never after a hold or a skip


def test_a_failing_run_never_invokes_the_proof_window(tmp_path: Path) -> None:
    called: list[int] = []

    result = _unit(
        make_deps(tmp_path, n_fills=None), proof_window=lambda root, now: called.append(1)
    )

    assert result.exit_code == 1 and called == []


def test_proof_window_hook_failure_is_a_nonzero_exit_not_a_swallowed_error(tmp_path: Path) -> None:
    def proof(data_root: Path, now_ns: int) -> None:
        raise OSError("artefact write failed")

    result = _unit(make_deps(tmp_path), proof_window=proof)

    assert result.exit_code == 1
    assert any(ln.startswith("AUT2 PROOF_WINDOW_FAILED") for ln in result.lines)


# -- the not_under_unit guard and the CLI -------------------------------------------------------


def test_label_run_refuses_production_write_outside_label_unit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing_db = tmp_path / "nope.sqlite"
    argv = ["--data-root", str(tmp_path / "data"), "--exec-db", str(missing_db)]

    no_invocation = main(argv, unit_context=UnitContext(None, f"/x/{LABEL_UNIT}.service"))
    wrong_cgroup = main(argv, unit_context=UnitContext("inv", "/user.slice/other.service"))

    out = capsys.readouterr().out
    assert no_invocation == 2 and wrong_cgroup == 2
    assert out.count("LABEL_OUTCOMES REFUSED reason=not_under_unit") == 2
    assert not (tmp_path / "data").exists()  # refused before any read or write


@pytest.mark.parametrize(
    "flags",
    [
        ["--record-skip"],
        ["--proof-window", "--start-day", "2026-10-02"],
        ["--canary", "--day", "2026-10-02"],
    ],
)
def test_every_production_write_mode_is_refused_outside_the_unit(
    tmp_path: Path, flags: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main([*flags, "--data-root", str(tmp_path)], unit_context=UnitContext(None, ""))

    assert rc == 2 and "reason=not_under_unit" in capsys.readouterr().out
    assert list(tmp_path.iterdir()) == []


def test_proof_window_refuses_outside_label_unit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(
        ["--proof-window", "--data-root", str(tmp_path), "--start-day", "2026-10-02"],
        unit_context=UnitContext("inv", "/user.slice/other.service"),
    )

    assert rc == 2 and "REFUSED reason=not_under_unit" in capsys.readouterr().out


def test_real_default_paths_on_tmp_home(tmp_path: Path) -> None:
    paths = default_paths(tmp_path)

    assert paths.data_root == tmp_path / ".local" / "share" / "breezy"
    assert paths.exec_db == paths.data_root / "state" / "exec_polymarket_us.sqlite"
    assert paths.studies_lock_name == "breezy-studies.lock"


def test_record_skip_cli_writes_the_journal_and_exits_zero(tmp_path: Path) -> None:
    rc = main(
        [
            "--record-skip",
            "--data-root",
            str(tmp_path),
            "--now-ns",
            str(NOW_NS),
            "--slot-ns",
            str(NOW_NS - 5),
        ],
        unit_context=_IN_UNIT,
    )

    assert rc == 0
    assert list(tmp_path.joinpath("evidence", "aut2", "skips").rglob("*.json"))


def test_record_skip_cli_write_failure_exits_one(tmp_path: Path) -> None:
    tmp_path.joinpath("evidence").write_text("blocked")

    rc = main(
        ["--record-skip", "--data-root", str(tmp_path), "--now-ns", str(NOW_NS), "--slot-ns", "1"],
        unit_context=_IN_UNIT,
    )

    assert rc == 1


def test_default_mode_without_a_deps_wiring_fails_closed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The production planner and settlement source are wired by the coordinator at promotion;
    until then the default run refuses with exit 2 rather than label from a guess."""
    rc = main(
        ["--data-root", str(tmp_path / "d"), "--exec-db", str(tmp_path / "e")],
        unit_context=_IN_UNIT,
    )

    assert rc == 2 and "LABEL_OUTCOMES REFUSED reason=not_wired" in capsys.readouterr().out


# -- measure-peak ----------------------------------------------------------------------------------


def _cgroup_tree(tmp_path: Path, peak: str) -> tuple[str, Path]:
    cg = tmp_path / "cg" / "user.slice" / "run-x.service"
    cg.mkdir(parents=True)
    (cg / "memory.peak").write_text(peak)
    return "0::/user.slice/run-x.service\n", tmp_path / "cg"


def test_measure_peak_reads_own_cgroup_memory_peak(tmp_path: Path) -> None:
    proc_cgroup, root = _cgroup_tree(tmp_path, "2147483648\n")

    assert read_cgroup_memory_peak(proc_cgroup, root) == (2147483648, "/user.slice/run-x.service")


@pytest.mark.parametrize("peak", ["", "max\n", "-1\n", "abc\n"])
def test_a_malformed_memory_peak_is_an_error(tmp_path: Path, peak: str) -> None:
    proc_cgroup, root = _cgroup_tree(tmp_path, peak)

    with pytest.raises(ValueError):
        read_cgroup_memory_peak(proc_cgroup, root)


def test_a_missing_memory_peak_file_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        read_cgroup_memory_peak("0::/nowhere\n", tmp_path)


def test_measure_peak_aborts_below_memavailable_floor(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from breezy.analysis.labeling.label_run import MeasureSeams

    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemAvailable:   17000000 kB\n")  # ~16.2 GiB: under 16 GiB + 3 GiB RSS
    seams = MeasureSeams(
        meminfo_path=meminfo,
        rss_bytes=lambda: 3 * 1024**3,
        proc_cgroup_text="0::/x\n",
        cgroup_root=tmp_path,
    )
    out_root = tmp_path / "out"

    rc = main(
        ["--measure-peak", "--output-root", str(out_root), "--exec-db", str(tmp_path / "e")],
        unit_context=_IN_UNIT,
        measure_seams=seams,
    )

    assert rc == 2
    assert "LABEL_OUTCOMES MEASURE_ABORTED reason=memavailable" in capsys.readouterr().out
    assert not out_root.exists()


def test_measure_peak_delivery_is_dry_run_and_writes_no_real_dedup_journal(tmp_path: Path) -> None:
    sink = Sink()
    real_root = tmp_path / "real"
    real_root.mkdir(mode=0o700)
    out_root = tmp_path / "out"
    out_root.mkdir(mode=0o700)
    deps = make_deps(
        tmp_path, registry={FQ_KIND: DroppingPlugin()}, deliver=sink, dry_run_root=out_root
    )

    result = run_labels(replace(deps, data_root=out_root))

    assert result.exit_code == 0 and sink.payloads == []  # nothing was sent
    assert not (real_root / "evidence").exists()
    assert not list(out_root.rglob("critical_dedup/*/*.json"))
    assert list(out_root.rglob("measure_dry_run/*.json"))


def test_measure_peak_writes_only_the_artefact_under_the_real_stores(tmp_path: Path) -> None:
    from breezy.analysis.labeling.label_run import MeasureSeams, measure_peak

    proc_cgroup, root = _cgroup_tree(tmp_path, "1073741824\n")
    out_root = tmp_path / "out"
    out_root.mkdir(mode=0o700)
    deps = make_deps(tmp_path, deliver=Sink())
    seams = MeasureSeams(
        meminfo_path=_meminfo(tmp_path, 30 * 1024**2),
        rss_bytes=lambda: 0,
        proc_cgroup_text=proc_cgroup,
        cgroup_root=root,
    )

    result = measure_peak(
        deps, output_root=out_root, seams=seams, invocation_id="inv-9", git_sha="g" * 40
    )

    assert result.exit_code == 0
    artefacts = list(out_root.rglob("label_run_peak_*.json"))
    assert len(artefacts) == 1
    body = json.loads(artefacts[0].read_text())
    assert body["schema"] == "aut2_memory_peak/v1" and body["memory_peak_bytes"] == 1073741824
    assert body["durable_fill_count"] == 2 and body["invocation_id"] == "inv-9"
    assert not list(deps.data_root.rglob("*"))  # the injected data root was never written


def _meminfo(tmp_path: Path, kib: int) -> Path:
    path = tmp_path / "meminfo2"
    path.write_text(f"MemAvailable:   {kib} kB\n")
    return path


def test_unit_context_reads_env_and_proc_cgroup() -> None:
    ctx = UnitContext.from_environment(
        {"INVOCATION_ID": "i"}, "0::/user.slice/breezy-label-outcomes.service\n"
    )

    assert ctx == UnitContext("i", "/user.slice/breezy-label-outcomes.service")
    assert ctx.is_label_unit() is True
    assert UnitContext("i", "/user.slice/x-breezy-label-outcomes.service").is_label_unit() is False
    assert UnitContext("", f"/a/{LABEL_UNIT}.service").is_label_unit() is False


def test_canary_without_exec_db_reads_through_exec_snapshot_without_flock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from breezy.analysis.labeling import label_run
    from breezy.runtime.autonomy_sandbox.wal_snapshot import EXEC_STORE_FILENAME
    from tests.support.aut2_fixtures import durable_fill, seed_fills

    root = tmp_path / "data"
    (root / "state").mkdir(parents=True, mode=0o700)
    seed_fills(root / "state" / EXEC_STORE_FILENAME, [durable_fill(ts_event=1)])
    seen: list[bool] = []
    real = label_run.exec_snapshot  # type: ignore[attr-defined]

    def _spy(**kwargs: Any) -> Any:
        seen.append(kwargs["take_flock"])
        return real(**kwargs)

    monkeypatch.setattr(label_run, "exec_snapshot", _spy)

    rc = main(
        [
            "--canary",
            "--data-root",
            str(root),
            "--day",
            "2026-10-02",
            "--now-ns",
            str(NOW_NS + 400 * HOUR_NS),
        ],
        unit_context=_IN_UNIT,
    )

    assert rc == 0 and seen == [False]  # the exec store is read through a snapshot, never a flock
    assert list(root.joinpath("derived", "canary").rglob("*.jsonl"))
    assert (root / "cache" / "label_run_snapshot").is_dir()
