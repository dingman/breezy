"""AUT-2 r7 WP8 / section 6: the live-proof window rules (canary days, start gates, restarts)."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from breezy.analysis.labeling.constants import PROOF_MIN_REAL_FILLS, PROOF_QUALIFYING_DAYS
from breezy.analysis.labeling.label_run import run_proof_window
from breezy.analysis.labeling.proof_window import (
    DayEvidence,
    DayStatus,
    ProofWindowRefused,
    evaluate_window,
)
from breezy.persistence.autonomy.verdict import VerdictOutcome

_PASS = VerdictOutcome.PASS
_NS_PER_DAY = 86_400_000_000_000
# 2026-10-01T16:50:00Z, the capture epoch start used throughout.
_EPOCH_NS = 1_790_873_400_000_000_000
_START = "2026-10-02"


def _day(n: int) -> str:
    return f"2026-10-{n:02d}"


def _ev(day: str = _START, **over: Any) -> DayEvidence:
    base: dict[str, Any] = {
        "utc_day": day,
        "real_fills": 1,
        "final_labelled": 1,
        "unresolved": 0,
        "missing_label": 0,
        "non_c1_post_epoch_count": 0,
        "non_c1_entry_rows": 0,
        "p_null_count": 0,
        "daily_recon": _PASS,
        "post_stop": _PASS,
        "intraday_non_pass_ids": (),
        "position_mismatches_transient": 0,
        "max_label_lag_h": 3.0,
        "fills_never_position_compared": 0,
        "canary_fills": 0,
        "canary_labelled_with_p": False,
        "canary_recon_passes": False,
        "label_slot_held": False,
        "no_leg_fills": 0,
        "exit_fills": 0,
        "marker_file": "marker_1.json",
        "invocation_id": "inv-1",
    }
    base.update(over)
    return DayEvidence(**base)


def _canary(day: str = _START, **over: Any) -> DayEvidence:
    base: dict[str, Any] = {
        "real_fills": 0,
        "final_labelled": 0,
        "canary_fills": 2,
        "canary_labelled_with_p": True,
        "canary_recon_passes": True,
    }
    base.update(over)
    return _ev(day, **base)


def _eval(days: list[DayEvidence], **over: Any) -> Any:
    args: dict[str, Any] = {
        "start_day": _START,
        "capture_epoch_start_ns": _EPOCH_NS,
        "wp7_active": True,
        "hold_days": (),
    }
    args.update(over)
    return evaluate_window(days=days, **args)


def _status(result: Any, day: str) -> DayStatus:
    status: DayStatus = next(d.status for d in result.days if d.utc_day == day)
    return status


def test_pins() -> None:
    assert (PROOF_QUALIFYING_DAYS, PROOF_MIN_REAL_FILLS) == (7, 5)


def test_canary_day_qualifies_only_with_real_recon_pass() -> None:
    ok = _eval([_canary()])
    bad_recon = _eval([_canary(daily_recon=VerdictOutcome.FAIL)])
    inconclusive = _eval([_canary(daily_recon=VerdictOutcome.INCONCLUSIVE)])
    no_recon = _eval([_canary(daily_recon=None)])
    bad_canary = _eval([_canary(canary_recon_passes=False)])
    null_p = _eval([_canary(canary_labelled_with_p=False)])

    assert _status(ok, _START) is DayStatus.QUALIFIES_CANARY
    for result in (bad_recon, inconclusive, no_recon, bad_canary, null_p):
        assert _status(result, _START) is DayStatus.EXTENDS


def test_canary_never_satisfies_live_fill_check() -> None:
    result = _eval([_canary()])

    day = result.days[0]
    assert (day.real_fills, day.canary_fills, day.live_fill_check) == (0, 2, "vacuous")
    assert result.real_fills == 0 and result.complete is False
    # a canary day never carries a real-fill label check, and canary fills never reach the 5
    many = _eval([_canary(_day(n), canary_fills=50) for n in range(2, 9)])
    assert many.qualifying_days == 7 and many.real_fills == 0 and many.complete is False


def test_a_real_fill_day_reports_all_labelled() -> None:
    result = _eval([_ev()])

    assert result.days[0].live_fill_check == "all_labelled"
    assert _status(result, _START) is DayStatus.QUALIFIES


def test_proof_window_refuses_start_before_capture_epoch_and_wp7() -> None:
    with pytest.raises(ProofWindowRefused) as before:
        _eval([_ev("2026-10-01")], start_day="2026-10-01")
    with pytest.raises(ProofWindowRefused) as no_wp7:
        _eval([_ev()], wp7_active=False)
    with pytest.raises(ProofWindowRefused) as no_epoch:
        _eval([_ev()], capture_epoch_start_ns=None)

    assert before.value.reason == "start_before_capture_epoch"
    assert no_wp7.value.reason == "wp7_not_active"
    assert no_epoch.value.reason == "capture_epoch_unwritten"
    assert _status(_eval([_ev()]), _START) is DayStatus.QUALIFIES  # the first full day after


def test_proof_day_fails_on_any_non_c1_entry_row() -> None:
    result = _eval([_ev(_day(2)), _ev(_day(3), non_c1_entry_rows=1), _ev(_day(4))])

    assert _status(result, _day(3)) is DayStatus.FAILS
    assert result.restarted_on == (_day(3),)
    assert result.start_day == _day(4) and result.qualifying_days == 1


def test_proof_window_excludes_pre_epoch_days() -> None:
    pre = _ev("2026-09-30", real_fills=40, final_labelled=40)
    result = _eval([pre, _ev()])

    assert _status(result, "2026-09-30") is DayStatus.EXCLUDED
    assert result.real_fills == 1 and result.qualifying_days == 1


def test_proof_window_not_started_while_label_timer_held() -> None:
    with pytest.raises(ProofWindowRefused) as caught:
        _eval([_ev()], hold_days=("2026-10-05",))
    assert caught.value.reason == "label_timer_held"

    # a hold strictly before the candidate start does not refuse it
    assert _status(_eval([_ev()], hold_days=("2026-10-01",)), _START) is DayStatus.QUALIFIES


def test_held_slot_inside_window_fails_day_and_restarts_window() -> None:
    result = _eval([_ev(_day(2)), _ev(_day(3), label_slot_held=True), _ev(_day(4))])

    assert _status(result, _day(3)) is DayStatus.FAILS
    assert result.restarted_on == (_day(3),)
    assert result.start_day == _day(4) and result.qualifying_days == 1
    assert result.real_fills == 1


def test_real_fill_day_failing_a_check_fails_and_restarts() -> None:
    cases: list[dict[str, Any]] = [
        {"final_labelled": 0},
        {"unresolved": 1},
        {"missing_label": 1},
        {"non_c1_post_epoch_count": 1},
        {"p_null_count": 1},
        {"daily_recon": VerdictOutcome.FAIL},
        {"post_stop": None},
        {"max_label_lag_h": 24.5},
        {"fills_never_position_compared": 1},
    ]
    for over in cases:
        result = _eval([_ev(_day(2)), _ev(_day(3), **over)])
        assert _status(result, _day(3)) is DayStatus.FAILS, over
        assert result.qualifying_days == 0, over


def test_zero_fill_non_canary_day_extends_the_window() -> None:
    zero = _ev(_day(3), real_fills=0, final_labelled=0)

    result = _eval([_ev(_day(2)), zero, _ev(_day(4))])

    assert _status(result, _day(3)) is DayStatus.EXTENDS
    assert result.qualifying_days == 2 and result.restarted_on == ()


def test_window_completes_with_seven_qualifying_days_and_five_real_fills() -> None:
    fills = [1, 1, 1, 1, 1, 0, 0]
    days = [
        _ev(_day(2 + i), real_fills=n, final_labelled=n) if n else _canary(_day(2 + i))
        for i, n in enumerate(fills)
    ]

    done = _eval(days)
    short = _eval(days[:4] + [_canary(_day(n)) for n in (6, 7, 8)])

    assert done.complete is True and (done.qualifying_days, done.real_fills) == (7, 5)
    assert short.complete is False  # seven days, four real fills


def test_no_leg_and_exit_fills_are_totalled_with_capability_fields() -> None:
    result = _eval([_ev(no_leg_fills=2, exit_fills=1)])

    assert (result.no_leg_fills, result.exit_fills) == (2, 1)


# -- the artefact -----------------------------------------------------------------------------


def test_run_proof_window_writes_the_artefact_once(tmp_path: Path) -> None:
    days = [_ev(_day(2)), _canary(_day(3))]

    path = run_proof_window(
        tmp_path,
        start_day=_START,
        days=days,
        capture_epoch_start_ns=_EPOCH_NS,
        wp7_active=True,
        hold_days=(),
    )

    assert path == tmp_path / "evidence" / "aut2_live_proof" / f"window_{_START}_{_day(3)}.json"
    body = json.loads(path.read_text())
    assert body["real_fills"] == 1 and body["canary_fills"] == 2
    assert [d["live_fill_check"] for d in body["days"]] == ["all_labelled", "vacuous"]
    assert body["marker_files"] == ["marker_1.json", "marker_1.json"]
    assert body["invocation_ids"] == ["inv-1", "inv-1"]
    again = run_proof_window(
        tmp_path,
        start_day=_START,
        days=days,
        capture_epoch_start_ns=_EPOCH_NS,
        wp7_active=True,
        hold_days=(),
    )
    assert again == path


def test_run_proof_window_refuses_before_writing_anything(tmp_path: Path) -> None:
    with pytest.raises(ProofWindowRefused):
        run_proof_window(
            tmp_path,
            start_day="2026-10-01",
            days=[_ev("2026-10-01")],
            capture_epoch_start_ns=_EPOCH_NS,
            wp7_active=True,
            hold_days=(),
        )

    assert not (tmp_path / "evidence").exists()


def test_day_evidence_is_immutable() -> None:
    ev = _ev()

    with pytest.raises(AttributeError):
        ev.real_fills = 9  # type: ignore[misc]
    assert replace(ev, real_fills=2).real_fills == 2


# -- review fold-ins: the write-once artefact carries every section 6 field -----------------------

_ARTEFACT_DAY_FIELDS = (
    "utc_day",
    "status",
    "reasons",
    "real_fills",
    "final_labelled",
    "unresolved",
    "missing_label",
    "non_c1_post_epoch_count",
    "non_c1_entry_rows",
    "p_null_count",
    "daily_recon",
    "daily_recon_verdict_id",
    "post_stop",
    "post_stop_verdict_id",
    "intraday_non_pass_ids",
    "position_mismatches_transient",
    "max_label_lag_h",
    "fills_never_position_compared",
    "canary_fills",
    "canary_labelled_with_p",
    "canary_recon_passes",
    "live_fill_check",
    "no_leg_fills",
    "exit_fills",
)


def test_artefact_day_rows_carry_every_section_6_field(tmp_path: Path) -> None:
    day = _ev(
        daily_recon_verdict_id="v-daily",
        post_stop_verdict_id="v-post",
        intraday_non_pass_ids=("v-i1",),
        position_mismatches_transient=2,
        max_label_lag_h=7.5,
        no_leg_fills=1,
    )

    path = run_proof_window(
        tmp_path,
        start_day=_START,
        days=[day],
        capture_epoch_start_ns=_EPOCH_NS,
        wp7_active=True,
        hold_days=(),
    )

    row = json.loads(path.read_text())["days"][0]
    assert set(_ARTEFACT_DAY_FIELDS) <= set(row)
    assert row["daily_recon_verdict_id"] == "v-daily" and row["post_stop_verdict_id"] == "v-post"
    assert row["daily_recon"] == "PASS" and row["intraday_non_pass_ids"] == ["v-i1"]
    assert (row["position_mismatches_transient"], row["max_label_lag_h"]) == (2, "7.500")
    assert row["final_labelled"] == 1 and row["fills_never_position_compared"] == 0


def test_a_missing_verdict_is_recorded_as_null_not_dropped(tmp_path: Path) -> None:
    path = run_proof_window(
        tmp_path,
        start_day=_START,
        days=[_ev(post_stop=None)],
        capture_epoch_start_ns=_EPOCH_NS,
        wp7_active=True,
        hold_days=(),
    )

    row = json.loads(path.read_text())["days"][0]
    assert "post_stop" in row and row["post_stop"] is None


# -- review fold-in: malformed dates are refused, never compared as strings -----------------------


@pytest.mark.parametrize(
    ("start", "holds"),
    [
        ("2026-1-2", ()),
        ("20261002", ()),
        ("not-a-date", ()),
        (_START, ("2026-10",)),
        (_START, ("garbage",)),
    ],
)
def test_malformed_start_or_hold_dates_are_refused(start: str, holds: tuple[str, ...]) -> None:
    with pytest.raises(ProofWindowRefused) as caught:
        _eval([_ev()], start_day=start, hold_days=holds)

    assert caught.value.reason == "malformed_date"


def test_a_malformed_evidence_day_is_refused() -> None:
    with pytest.raises(ProofWindowRefused) as caught:
        _eval([_ev("2026-10-2")])

    assert caught.value.reason == "malformed_date"


def test_any_evidence_gap_fails_the_day_and_restarts_the_window() -> None:
    gap = _ev(_day(3), evidence_gaps=("marker_missing",))

    result = _eval([_ev(_day(2)), gap, _ev(_day(4))])

    assert _status(result, _day(3)) is DayStatus.FAILS
    assert result.restarted_on == (_day(3),) and result.qualifying_days == 1
    assert next(d for d in result.days if d.utc_day == _day(3)).reasons == (
        "evidence_gap:marker_missing",
    )


def test_a_zero_fill_day_with_an_evidence_gap_also_fails() -> None:
    result = _eval([_canary(_day(2), evidence_gaps=("marker_missing",))])

    assert _status(result, _day(2)) is DayStatus.FAILS
