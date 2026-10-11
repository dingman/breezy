"""EXEC-PAR BG-5b: the stage report JSON is explicit (no asdict) and byte-stable."""

from __future__ import annotations

import dataclasses
import json
from decimal import Decimal

from breezy.runtime.exec_par_stage_report import report_json
from breezy.runtime.exec_par_stage_types import DayStat, StageReport


def _fixed_report() -> StageReport:
    return StageReport(
        stage="S2", configured_k=4, effective_k=2, floor_day="2026-10-01", today="2026-10-09",
        closed_days=7, nonexcluded_days=6, excluded_days=("2026-10-03",), posted=40, ambiguous=3,
        ambiguous_rate=Decimal("0.075"), fills=12, filled_orders=10, days_with_fill=5,
        m_bar=Decimal("2.5"),
        day_stats=(DayStat("2026-10-02", 5, 1, 2), DayStat("2026-10-04", 6, 0, 3)),
        minima_met=True, dropped_share=Decimal("0.01"), station_day_flag_days=("2026-10-05",),
        window_flag_days=("2026-10-06", "2026-10-07"), slippage_mean=Decimal("-0.0125"),
        slippage_tail_share=None, parity_diff=Decimal(0), fee_unreconciled_share=None,
        per_fill_fee_mismatches=1, section5_halt_in_stage=False, held_days=2,
        promotion_blocked_reason="v2", promotion_pending_commit=True, pnl_pending=1,
        pnl_overdue=2, pnl_ambiguous_unresolved=3, programme_paused=False, notes=("a", "b"),
    )  # fmt: skip


_EXPECTED = (
    '{"ambiguous":3,"ambiguous_rate":"0.075","closed_days":7,"configured_k":4,'
    '"day_stats":[{"ambiguous":1,"day":"2026-10-02","fills":2,'
    '"posted":5},{"ambiguous":0,"day":"2026-10-04","fills":3,"posted":6}],'
    '"days_with_fill":5,"dropped_share":"0.01","effective_k":2,'
    '"excluded_days":["2026-10-03"],"fee_unreconciled_share":null,"filled_orders":10,'
    '"fills":12,"floor_day":"2026-10-01","held_days":2,"m_bar":"2.5",'
    '"minima_met":true,"nonexcluded_days":6,"notes":["a","b"],"parity_diff":"0",'
    '"per_fill_fee_mismatches":1,"pnl_ambiguous_unresolved":3,"pnl_overdue":2,'
    '"pnl_pending":1,"posted":40,"programme_paused":false,'
    '"promotion_blocked_reason":"v2","promotion_pending_commit":true,'
    '"section5_halt_in_stage":false,"slippage_mean":"-0.0125",'
    '"slippage_tail_share":null,"stage":"S2","station_day_flag_days":["2026-10-05"],'
    '"today":"2026-10-09","window_flag_days":["2026-10-06","2026-10-07"]}'
)


def test_report_json_is_byte_identical_to_the_pinned_document() -> None:
    assert report_json(_fixed_report()) == _EXPECTED


def test_to_json_dict_covers_every_stage_report_field() -> None:
    report = _fixed_report()
    names = {f.name for f in dataclasses.fields(StageReport)}
    assert set(report.to_json_dict()) == names


def test_to_json_dict_covers_every_day_stat_field() -> None:
    stat = DayStat("2026-10-02", 5, 1, 2)
    assert set(stat.to_json_dict()) == {f.name for f in dataclasses.fields(DayStat)}


def test_report_json_round_trips_as_compact_sorted_json() -> None:
    text = report_json(_fixed_report())
    assert text == json.dumps(json.loads(text), sort_keys=True, separators=(",", ":"))
