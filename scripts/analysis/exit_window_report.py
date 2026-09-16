"""Row assembly, corpus summary, and Markdown rendering for the offline
"exit window" study (``docs/plans/POSITION_EXIT_EXECUTION_2026-09-16.md``).

Split out of ``exit_window_core.py`` (behaviour-preserving; mirrors the
``monitor_hypothetical_core.py``/``monitor_hypothetical_report.py`` split for
INC-8) purely to keep each new module under the repo's ~400-line guidance.
No I/O, no catalog access, no strategy or monitor evaluation -- those inputs
already exist by the time this module sees them (``exit_window_core
.build_exit_timeline``'s return value, plus the caller's own settlement
resolution).
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Literal

from exit_window_core import (
    ExitTimeline,
    FilledPosition,
    RuleOutcome,
    entry_cost,
    hold_pnl,
    r_best_outcome,
    r_dead_outcome,
    r_threat_outcome,
)

__all__ = [
    "ExitWindowSummary",
    "PositionExitRow",
    "build_position_exit_row",
    "build_summary",
    "render_markdown",
]

_ZERO: Final[Decimal] = Decimal(0)
_MINUTE_NS: Final[int] = 60_000_000_000


def _decimal_or_none(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


@dataclass(frozen=True, slots=True, kw_only=True)
class PositionExitRow:
    position: FilledPosition
    timeline: ExitTimeline
    settled_held: bool | None
    settlement_preliminary: bool
    hold_pnl: Decimal | None
    r_dead: RuleOutcome
    r_threat: RuleOutcome
    r_best: RuleOutcome
    #: Which Depth10 source this row's timeline was replayed against --
    #: "catalog" (the committed ``ParquetDataCatalog``) or "staged" (the
    #: recorder's own not-yet-converted feather frames, used when the
    #: catalog's newest frame precedes the fill -- ING-1). Reported per row
    #: so a caller never has to guess which tape backed a given result.
    depth_source: Literal["catalog", "staged"]

    def to_dict(self) -> dict[str, object]:
        position = self.position
        return {
            "trial_id": position.trial_id,
            "station": position.station,
            "climate_day": position.climate_day,
            "instrument_id": position.instrument_id,
            "leg": position.leg,
            "fill_px": str(position.fill_px),
            "fee": str(position.fee),
            "held_qty": position.held_qty,
            "filled_at_ns": position.filled_at_ns,
            "entry_cost": str(entry_cost(position)),
            "p_hold_at_entry": _decimal_or_none(self.timeline.p_hold_at_entry),
            "first_threatened_ts_ns": self.timeline.first_threatened_ts_ns,
            "first_dead_ts_ns": self.timeline.first_dead_ts_ns,
            "last_executable_ts_ns": self.timeline.last_executable_ts_ns,
            "depth_source": self.depth_source,
            "settled_held": self.settled_held,
            "settlement_preliminary": self.settlement_preliminary,
            "hold_pnl": _decimal_or_none(self.hold_pnl),
            "rules": {
                outcome.rule: {
                    "status": outcome.status,
                    "signal_ts_ns": outcome.signal_ts_ns,
                    "exit_ts_ns": outcome.exit_ts_ns,
                    "exit_price": _decimal_or_none(outcome.exit_price),
                    "pnl": _decimal_or_none(outcome.pnl),
                }
                for outcome in (self.r_dead, self.r_threat, self.r_best)
            },
            "total_evaluations": len(self.timeline.evaluations),
        }


def build_position_exit_row(
    *, timeline: ExitTimeline, settled_held: bool | None, settlement_preliminary: bool,
    depth_source: Literal["catalog", "staged"],
) -> PositionExitRow:
    """Assemble one output row from an already-built timeline plus a
    settlement resolution the caller made (scored-trial lookup, else
    ``exit_window_core.infer_preliminary_settlement``)."""
    hold_pnl_value = hold_pnl(timeline.position, settled_held=settled_held)
    return PositionExitRow(
        position=timeline.position,
        timeline=timeline,
        settled_held=settled_held,
        settlement_preliminary=settlement_preliminary,
        hold_pnl=hold_pnl_value,
        r_dead=r_dead_outcome(timeline, hold_pnl_value=hold_pnl_value),
        r_threat=r_threat_outcome(timeline, hold_pnl_value=hold_pnl_value),
        r_best=r_best_outcome(timeline, hold_pnl_value=hold_pnl_value),
        depth_source=depth_source,
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class ExitWindowSummary:
    n_positions: int
    threatened_before_emptied: int
    dead_before_emptied: int
    median_minutes_last_executable_to_threatened: Decimal | None
    median_minutes_last_executable_to_dead: Decimal | None
    sum_hold_pnl: Decimal | None
    sum_r_dead_pnl: Decimal | None
    sum_r_threat_pnl: Decimal | None
    sum_r_best_pnl: Decimal | None

    def to_dict(self) -> dict[str, object]:
        return {
            "n_positions": self.n_positions,
            "threatened_before_emptied": self.threatened_before_emptied,
            "dead_before_emptied": self.dead_before_emptied,
            "median_minutes_last_executable_to_threatened": _decimal_or_none(
                self.median_minutes_last_executable_to_threatened,
            ),
            "median_minutes_last_executable_to_dead": _decimal_or_none(
                self.median_minutes_last_executable_to_dead,
            ),
            "sum_hold_pnl": _decimal_or_none(self.sum_hold_pnl),
            "sum_r_dead_pnl": _decimal_or_none(self.sum_r_dead_pnl),
            "sum_r_threat_pnl": _decimal_or_none(self.sum_r_threat_pnl),
            "sum_r_best_pnl": _decimal_or_none(self.sum_r_best_pnl),
        }


def _minutes(delta_ns: int) -> Decimal:
    return Decimal(delta_ns) / Decimal(_MINUTE_NS)


def _median_minutes_to(
    rows: Sequence[PositionExitRow], *, confirmation_attr: str,
) -> Decimal | None:
    deltas: list[Decimal] = []
    for row in rows:
        last_executable_ts_ns = row.timeline.last_executable_ts_ns
        confirmation_ts_ns = getattr(row.timeline, confirmation_attr)
        if last_executable_ts_ns is None or confirmation_ts_ns is None:
            continue
        deltas.append(_minutes(confirmation_ts_ns - last_executable_ts_ns))
    if not deltas:
        return None
    return statistics.median(deltas)


def _sum_pnl(rows: Sequence[PositionExitRow], *, outcome_attr: str) -> Decimal | None:
    values = [
        getattr(row, outcome_attr).pnl if outcome_attr != "hold_pnl" else row.hold_pnl
        for row in rows
    ]
    known = [value for value in values if value is not None]
    if not known:
        return None
    return sum(known, _ZERO)


def build_summary(rows: Sequence[PositionExitRow]) -> ExitWindowSummary:
    threatened_before_emptied = sum(
        1
        for row in rows
        if row.timeline.first_threatened_ts_ns is not None
        and row.timeline.last_executable_ts_ns is not None
        and row.timeline.first_threatened_ts_ns <= row.timeline.last_executable_ts_ns
    )
    dead_before_emptied = sum(
        1
        for row in rows
        if row.timeline.first_dead_ts_ns is not None
        and row.timeline.last_executable_ts_ns is not None
        and row.timeline.first_dead_ts_ns <= row.timeline.last_executable_ts_ns
    )
    return ExitWindowSummary(
        n_positions=len(rows),
        threatened_before_emptied=threatened_before_emptied,
        dead_before_emptied=dead_before_emptied,
        median_minutes_last_executable_to_threatened=_median_minutes_to(
            rows, confirmation_attr="first_threatened_ts_ns",
        ),
        median_minutes_last_executable_to_dead=_median_minutes_to(
            rows, confirmation_attr="first_dead_ts_ns",
        ),
        sum_hold_pnl=_sum_pnl(rows, outcome_attr="hold_pnl"),
        sum_r_dead_pnl=_sum_pnl(rows, outcome_attr="r_dead"),
        sum_r_threat_pnl=_sum_pnl(rows, outcome_attr="r_threat"),
        sum_r_best_pnl=_sum_pnl(rows, outcome_attr="r_best"),
    )


def _fmt(value: object) -> str:
    return "-" if value is None else str(value)


def _fmt_rule(outcome: RuleOutcome) -> str:
    if outcome.status == "exited":
        return f"{outcome.status}@{_fmt(outcome.exit_price)} pnl={_fmt(outcome.pnl)}"
    return f"{outcome.status} pnl={_fmt(outcome.pnl)}"


def render_markdown(rows: Sequence[PositionExitRow], summary: ExitWindowSummary) -> str:
    """One Markdown table row per position plus the aggregate summary block."""
    header = (
        "| trial_id | leg | fill_px | depth_source | first_threatened_ts_ns | "
        "first_dead_ts_ns | last_executable_ts_ns | settled_held | preliminary | hold_pnl | "
        "R-DEAD | R-THREAT | R-BEST |"
    )
    sep = "|---" * 13 + "|"
    lines = [header, sep]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    row.position.trial_id,
                    row.position.leg,
                    str(row.position.fill_px),
                    row.depth_source,
                    _fmt(row.timeline.first_threatened_ts_ns),
                    _fmt(row.timeline.first_dead_ts_ns),
                    _fmt(row.timeline.last_executable_ts_ns),
                    _fmt(row.settled_held),
                    "YES" if row.settlement_preliminary else "no",
                    _fmt(row.hold_pnl),
                    _fmt_rule(row.r_dead),
                    _fmt_rule(row.r_threat),
                    _fmt_rule(row.r_best),
                ],
            )
            + " |",
        )
    lines.append("")
    lines.append(f"n_positions={summary.n_positions}")
    lines.append(
        f"threatened_before_exit_side_emptied={summary.threatened_before_emptied}/"
        f"{summary.n_positions}",
    )
    lines.append(
        f"dead_before_exit_side_emptied={summary.dead_before_emptied}/{summary.n_positions}",
    )
    lines.append(
        "median_minutes_last_executable_to_threatened="
        f"{_fmt(summary.median_minutes_last_executable_to_threatened)}",
    )
    lines.append(
        "median_minutes_last_executable_to_dead="
        f"{_fmt(summary.median_minutes_last_executable_to_dead)}",
    )
    lines.append(f"sum_hold_pnl={_fmt(summary.sum_hold_pnl)}")
    lines.append(f"sum_r_dead_pnl={_fmt(summary.sum_r_dead_pnl)}")
    lines.append(f"sum_r_threat_pnl={_fmt(summary.sum_r_threat_pnl)}")
    lines.append(f"sum_r_best_pnl={_fmt(summary.sum_r_best_pnl)}")
    return "\n".join(lines) + "\n"
