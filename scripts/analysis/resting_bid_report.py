"""Row assembly, corpus summary and Markdown rendering for the offline
"resting bid" counterfactual study, Arm A
(``docs/plans/RESTING_BID_HUNT_2026-09-16.md`` Sec 2).

Same split as ``exit_window_core.py``/``exit_window_report.py``: this module
owns aggregation and rendering, never replay/state-machine logic (that lives
in ``resting_bid_core.py``). PURE: no I/O, no wall-clock read.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

__all__ = [
    "GateResult",
    "RungLegRow",
    "StudySummary",
    "build_summary",
    "render_markdown",
]

GateStatus = Literal["PASS", "FAIL", "NOT_COMPUTABLE"]


def _decimal_or_none(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _margin_share_key(margin: Decimal, share: Decimal) -> str:
    return f"m={margin}:s={share}"


@dataclass(frozen=True, slots=True, kw_only=True)
class GateResult:
    """One of the plan's pre-registered arming gates (Sec 2.1), evaluated."""

    gate_id: str
    description: str
    status: GateStatus
    detail: str

    def to_dict(self) -> dict[str, object]:
        return {
            "gate_id": self.gate_id, "description": self.description,
            "status": self.status, "detail": self.detail,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class RungLegRow:
    """One (station-day, instrument, leg, margin, queue-share) result row."""

    station: str
    climate_day: str
    instrument_id: str
    leg: str
    margin: Decimal
    queue_share: Decimal
    rests: int
    reprices: int
    cancels_by_reason: Mapping[str, int]
    fill_events: int
    fills_expected: Decimal  # fill_events * queue_share
    informed_count: int
    liquidity_count: int
    #: PRIMARY, TAKER-priced pnl (domain-review finding 2), already scaled by
    #: queue_share -- see ``resting_bid_core.fill_pnl``.
    pnl_taker_sum: Decimal | None
    ioc_armed: bool
    ioc_pnl: Decimal | None
    time_to_fill_bands: Mapping[str, int]

    def to_dict(self) -> dict[str, object]:
        return {
            "station": self.station, "climate_day": self.climate_day,
            "instrument_id": self.instrument_id, "leg": self.leg,
            "margin": str(self.margin), "queue_share": str(self.queue_share),
            "rests": self.rests, "reprices": self.reprices,
            "cancels_by_reason": dict(self.cancels_by_reason),
            "fill_events": self.fill_events, "fills_expected": str(self.fills_expected),
            "informed_count": self.informed_count, "liquidity_count": self.liquidity_count,
            "pnl_taker_sum": _decimal_or_none(self.pnl_taker_sum),
            "ioc_armed": self.ioc_armed, "ioc_pnl": _decimal_or_none(self.ioc_pnl),
            "time_to_fill_bands": dict(self.time_to_fill_bands),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class StudySummary:
    qualifying_station_days: int
    stranded_station_days: int
    fills_by_margin_share: Mapping[tuple[Decimal, Decimal], int] = field(default_factory=dict)
    pi_hat_i_by_margin_share: Mapping[tuple[Decimal, Decimal], tuple[float, float]] = field(
        default_factory=dict,
    )
    #: PRIMARY, TAKER-priced pnl sums (domain-review finding 2) -- see
    #: ``resting_bid_core.fill_pnl``.
    pnl_sum_taker_by_margin_share: Mapping[tuple[Decimal, Decimal], Decimal] = field(
        default_factory=dict,
    )
    pnl_sum_ioc: Decimal = Decimal(0)
    gates: tuple[GateResult, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "qualifying_station_days": self.qualifying_station_days,
            "stranded_station_days": self.stranded_station_days,
            "fills_by_margin_share": {
                _margin_share_key(m, s): n for (m, s), n in self.fills_by_margin_share.items()
            },
            "pi_hat_i_by_margin_share": {
                _margin_share_key(m, s): list(ci)
                for (m, s), ci in self.pi_hat_i_by_margin_share.items()
            },
            "pnl_sum_taker_by_margin_share": {
                _margin_share_key(m, s): str(pnl)
                for (m, s), pnl in self.pnl_sum_taker_by_margin_share.items()
            },
            "pnl_sum_ioc": str(self.pnl_sum_ioc),
            "gates": [gate.to_dict() for gate in self.gates],
        }


def build_summary(
    rows: Sequence[RungLegRow], *, gates: Sequence[GateResult],
    qualifying_station_days: int, stranded_station_days: int,
) -> StudySummary:
    fills: dict[tuple[Decimal, Decimal], int] = {}
    informed: dict[tuple[Decimal, Decimal], int] = {}
    liquidity: dict[tuple[Decimal, Decimal], int] = {}
    pnl_taker: dict[tuple[Decimal, Decimal], Decimal] = {}
    pnl_ioc = Decimal(0)
    seen_ioc_keys: set[tuple[str, str, str]] = set()

    for row in rows:
        key = (row.margin, row.queue_share)
        fills[key] = fills.get(key, 0) + row.fill_events
        informed[key] = informed.get(key, 0) + row.informed_count
        liquidity[key] = liquidity.get(key, 0) + row.liquidity_count
        if row.pnl_taker_sum is not None:
            pnl_taker[key] = pnl_taker.get(key, Decimal(0)) + row.pnl_taker_sum
        ioc_key = (row.station, row.climate_day, row.instrument_id + row.leg)
        if row.ioc_pnl is not None and ioc_key not in seen_ioc_keys:
            seen_ioc_keys.add(ioc_key)
            pnl_ioc += row.ioc_pnl

    pi_hat: dict[tuple[Decimal, Decimal], tuple[float, float]] = {}
    from resting_bid_core import wilson_interval  # local import: avoid a hard cycle at module load

    for key in fills:
        total = informed.get(key, 0) + liquidity.get(key, 0)
        pi_hat[key] = wilson_interval(informed.get(key, 0), total)

    return StudySummary(
        qualifying_station_days=qualifying_station_days,
        stranded_station_days=stranded_station_days,
        fills_by_margin_share=fills, pi_hat_i_by_margin_share=pi_hat,
        pnl_sum_taker_by_margin_share=pnl_taker, pnl_sum_ioc=pnl_ioc, gates=tuple(gates),
    )


def render_markdown(summary: StudySummary) -> str:
    lines = [
        "# RESTING BID HUNT -- Arm A counterfactual study",
        "",
        (
            "Gates evaluated at s=1.0 (queue share); the per-(margin, share) fill "
            "counts below scale the EXPECTED FILL COUNT only -- they are not a "
            "gate-robustness sweep across s (domain-review finding 4)."
        ),
        "",
        f"Qualifying station-days: {summary.qualifying_station_days}",
        f"Stranded station-days (ING-1): {summary.stranded_station_days}",
        f"IOC baseline Sigma pnl: {summary.pnl_sum_ioc}",
        "",
        "## Fills / PnL / adverse selection by (margin, queue share)",
        "",
        "| margin | share | fills | pi_hat_I 95% CI | taker Sigma pnl (primary) |",
        "|---|---|---|---|---|",
    ]
    for key in sorted(summary.fills_by_margin_share, key=lambda k: (k[0], k[1])):
        margin, share = key
        fills = summary.fills_by_margin_share[key]
        ci = summary.pi_hat_i_by_margin_share.get(key, (0.0, 0.0))
        pnl = summary.pnl_sum_taker_by_margin_share.get(key, Decimal(0))
        lines.append(
            f"| {margin} | {share} | {fills} | [{ci[0]:.4f}, {ci[1]:.4f}] | {pnl} |",
        )

    lines += ["", "## Pre-registered arming gates (plan Sec 2.1)", "", "| gate | status | detail |",
              "|---|---|---|"]
    for gate in summary.gates:
        lines.append(f"| {gate.gate_id} ({gate.description}) | {gate.status} | {gate.detail} |")

    return "\n".join(lines) + "\n"
