"""AUT-2 r7 WP6 / section 6: the proof-window evidence is read from the stores, never from memory.

``collect_day_evidence`` assembles one UTC day's ``DayEvidence`` from the marker, the labels, the
verdict journal, the hold journal and the canary store. Anything unreadable raises (a day is never
guessed), and the store-backed hook refuses until WP7 and the capture epoch exist.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from breezy.analysis.labeling.label_core import LabelRunDeps, run_labels
from breezy.analysis.labeling.label_run import run_canary
from breezy.analysis.labeling.memory_gate import Hold, record_hold
from breezy.analysis.labeling.proof_source import (
    ProofSourceError,
    collect_day_evidence,
    hold_days,
    metric_or_none,
    store_proof_window,
)
from breezy.analysis.labeling.proof_window import DayEvidence, DayStatus, evaluate_window
from breezy.analysis.labeling.skip_journal import utc_day
from breezy.persistence.autonomy.label_schema import PSource
from breezy.persistence.autonomy.label_store import write_labels
from breezy.persistence.autonomy.verdict import VerdictOutcome
from tests.support.aut2_fixtures import HOUR_NS, TS, make_label_row
from tests.support.aut2_run_fixtures import FAMILY, NOW_NS, make_deps

_VENUE = "polymarket_us"
_FILL_DAY = utc_day(TS)


def _collect(tmp_path: Path) -> tuple[LabelRunDeps, DayEvidence]:
    deps = make_deps(tmp_path)
    run_labels(deps)
    return deps, collect_day_evidence(
        deps.data_root,
        exec_db=deps.exec_db,
        venue=_VENUE,
        family_id=FAMILY,
        day=_FILL_DAY,
        lag_start_ns=deps.lag_start_ns,
        now_ns=NOW_NS,
    )


def test_a_labelled_day_reads_counts_from_the_stores(tmp_path: Path) -> None:
    _, ev = _collect(tmp_path)

    assert ev.utc_day == _FILL_DAY
    assert (ev.real_fills, ev.final_labelled) == (2, 2)
    assert (ev.unresolved, ev.missing_label, ev.p_null_count, ev.non_c1_post_epoch_count) == (
        0,
        0,
        0,
        0,
    )
    assert ev.non_c1_entry_rows == 0 and ev.label_slot_held is False
    assert ev.marker_file is not None and ev.marker_file.startswith("marker_")
    assert (ev.canary_fills, ev.no_leg_fills, ev.exit_fills) == (0, 0, 0)


def test_the_daily_verdict_outcome_and_id_come_from_the_verdict_journal(tmp_path: Path) -> None:
    deps, ev = _collect(tmp_path)

    wires = [
        json.loads(p.read_text())
        for p in deps.data_root.joinpath("derived", "verdicts").rglob("*.json")
    ]
    daily = [w for w in wires if w["detector"] == "aut2.reconciliation"]
    assert ev.daily_recon is VerdictOutcome(daily[0]["outcome"])
    assert ev.daily_recon_verdict_id == daily[0]["verdict_id"]
    assert ev.post_stop is None and ev.post_stop_verdict_id is None  # WP9 produces it


def test_a_non_c1_entry_row_on_the_day_is_counted(tmp_path: Path) -> None:
    deps, _ = _collect(tmp_path)
    bad = make_label_row(
        label_id="9" * 32,
        client_order_id="O-1",
        p_source=PSource.ARTEFACT_RECOMPUTE,
        labelled_at_ns=NOW_NS + 1,
        label_seq=1,
    )
    write_labels(deps.data_root, FAMILY, [bad], now_ns=NOW_NS + 5)

    ev = collect_day_evidence(
        deps.data_root,
        exec_db=deps.exec_db,
        venue=_VENUE,
        family_id=FAMILY,
        day=_FILL_DAY,
        lag_start_ns=deps.lag_start_ns,
        now_ns=NOW_NS + 10,
    )

    assert ev.non_c1_entry_rows >= 1


def test_a_hold_journal_marks_the_day_held_and_is_listed(tmp_path: Path) -> None:
    deps = make_deps(tmp_path)
    record_hold(
        deps.data_root,
        Hold("memory_gate", "verdict_missing", 5 * 1024**3, None, None),
        now_ns=NOW_NS,
        slot_ns=NOW_NS,
    )

    assert hold_days(deps.data_root) == (utc_day(NOW_NS),)
    ev = collect_day_evidence(
        deps.data_root,
        exec_db=deps.exec_db,
        venue=_VENUE,
        family_id=FAMILY,
        day=utc_day(NOW_NS),
        lag_start_ns=deps.lag_start_ns,
        now_ns=NOW_NS,
    )
    assert ev.label_slot_held is True


def test_no_hold_journal_means_no_hold_days(tmp_path: Path) -> None:
    assert hold_days(make_deps(tmp_path).data_root) == ()


def test_canary_fields_come_from_the_canary_store_and_its_labels(tmp_path: Path) -> None:
    deps = make_deps(tmp_path, n_fills=0)
    run_canary(
        data_root=deps.data_root,
        venue=_VENUE,
        family_id=FAMILY,
        day="2026-10-02",
        now_ns=NOW_NS,
        real_fill_count=0,
    )

    ev = collect_day_evidence(
        deps.data_root,
        exec_db=deps.exec_db,
        venue=_VENUE,
        family_id=FAMILY,
        day="2026-10-02",
        lag_start_ns=deps.lag_start_ns,
        now_ns=NOW_NS,
    )

    assert (ev.real_fills, ev.canary_fills) == (0, 2)
    assert ev.canary_labelled_with_p is True and ev.canary_recon_passes is True


def test_an_unreadable_verdict_file_raises_never_reads_as_absent(tmp_path: Path) -> None:
    deps, _ = _collect(tmp_path)
    victim = next(deps.data_root.joinpath("derived", "verdicts").rglob("*.json"))
    victim.write_bytes(b"{")

    with pytest.raises(ProofSourceError):
        collect_day_evidence(
            deps.data_root,
            exec_db=deps.exec_db,
            venue=_VENUE,
            family_id=FAMILY,
            day=_FILL_DAY,
            lag_start_ns=deps.lag_start_ns,
            now_ns=NOW_NS,
        )


def test_an_unreadable_exec_store_raises(tmp_path: Path) -> None:
    deps = make_deps(tmp_path, n_fills=None)

    with pytest.raises(ProofSourceError):
        collect_day_evidence(
            deps.data_root,
            exec_db=deps.exec_db,
            venue=_VENUE,
            family_id=FAMILY,
            day=_FILL_DAY,
            lag_start_ns=deps.lag_start_ns,
            now_ns=NOW_NS,
        )


def test_the_store_backed_proof_window_refuses_until_wp7_and_the_epoch(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    deps = make_deps(tmp_path)
    run_labels(deps)

    store_proof_window(
        deps.data_root,
        exec_db=deps.exec_db,
        venue=_VENUE,
        family_id=FAMILY,
        start_day="2026-10-02",
        lag_start_ns=deps.lag_start_ns,
        now_ns=NOW_NS,
        wp7_active=False,
        capture_epoch_start_ns=None,
    )

    out = capsys.readouterr().out
    assert "AUT2 PROOF_WINDOW_REFUSED reason=capture_epoch_unwritten" in out
    assert not (deps.data_root / "evidence" / "aut2_live_proof").exists()


def test_the_store_backed_proof_window_evaluates_closed_days_once_started(tmp_path: Path) -> None:
    deps = make_deps(tmp_path)
    run_labels(deps)
    epoch = TS - 24 * HOUR_NS

    path = store_proof_window(
        deps.data_root,
        exec_db=deps.exec_db,
        venue=_VENUE,
        family_id=FAMILY,
        start_day=_FILL_DAY,
        lag_start_ns=deps.lag_start_ns,
        now_ns=NOW_NS + 36 * HOUR_NS,
        wp7_active=True,
        capture_epoch_start_ns=epoch,
    )

    assert path is not None and path.parent.name == "aut2_live_proof"
    body = json.loads(path.read_text())
    assert body["days"][0]["utc_day"] == _FILL_DAY and body["days"][0]["real_fills"] == 2


def test_open_days_are_never_evaluated(tmp_path: Path) -> None:
    deps = make_deps(tmp_path)
    run_labels(deps)
    epoch = TS - 24 * HOUR_NS

    path = store_proof_window(
        deps.data_root,
        exec_db=deps.exec_db,
        venue=_VENUE,
        family_id=FAMILY,
        start_day=utc_day(NOW_NS),
        lag_start_ns=deps.lag_start_ns,
        now_ns=NOW_NS,  # the same UTC day: still open
        wp7_active=True,
        capture_epoch_start_ns=epoch,
    )

    assert path is None


# -- review fold-in: a missing input fails the day, it never reads as zero ------------------------


def _collect_no_run(tmp_path: Path) -> DayEvidence:
    deps = make_deps(tmp_path)  # fills exist, but no label run has written a marker or verdict
    return collect_day_evidence(
        deps.data_root,
        exec_db=deps.exec_db,
        venue=_VENUE,
        family_id=FAMILY,
        day=_FILL_DAY,
        lag_start_ns=deps.lag_start_ns,
        now_ns=NOW_NS,
    )


def test_a_missing_marker_fails_the_day_not_counts_zero(tmp_path: Path) -> None:
    ev = _collect_no_run(tmp_path)

    assert "marker_missing" in ev.evidence_gaps
    result = evaluate_window(
        start_day=_FILL_DAY,
        days=[ev],
        capture_epoch_start_ns=TS - 24 * HOUR_NS,
        wp7_active=True,
        hold_days=(),
    )
    assert result.days[0].status is DayStatus.FAILS
    assert "evidence_gap:marker_missing" in result.days[0].reasons


def test_a_missing_metric_fails_the_day_not_reads_zero(tmp_path: Path) -> None:
    _, ev = _collect(tmp_path)  # the daily verdict this run wrote carries no position metrics yet

    assert "metric_missing:fills_never_position_compared" in ev.evidence_gaps
    result = evaluate_window(
        start_day=_FILL_DAY,
        days=[ev],
        capture_epoch_start_ns=TS - 24 * HOUR_NS,
        wp7_active=True,
        hold_days=(),
    )
    assert result.days[0].status is DayStatus.FAILS


def test_metric_reader_returns_none_for_an_absent_metric_and_a_value_otherwise() -> None:
    wire = {"metrics": {"present": "7", "also": 3}}

    assert metric_or_none(wire, "present") == 7
    assert metric_or_none(wire, "also") == 3
    assert metric_or_none(wire, "absent") is None
    assert metric_or_none({}, "absent") is None
    assert metric_or_none({"metrics": {"bad": "x"}}, "bad") is None


def test_a_present_marker_and_metrics_leave_no_gap_for_those_inputs(tmp_path: Path) -> None:
    _, ev = _collect(tmp_path)

    assert "marker_missing" not in ev.evidence_gaps
