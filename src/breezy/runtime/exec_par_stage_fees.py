"""EXEC-PAR BG-5a: fill parsing and the s7 fee checks (pure; see ``exec_par_stage_eval``)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation

from breezy.runtime.exec_par_stage_types import (
    CENT,
    FEE_STAGE_FLOOR,
    FEE_STAGE_PER_ORDER,
    FEE_THETA,
    STOP_S7_COEFFICIENT,
    STOP_S7_PER_ORDER,
    STOP_S7_PER_STAGE,
    StageContext,
    fail,
    parse_dec,
)


def fee_stage_tolerance(orders: int) -> Decimal:
    """s7 per-stage fee tolerance: ``max(2 c, 0.5 c x orders)`` in dollars."""
    return max(FEE_STAGE_FLOOR, FEE_STAGE_PER_ORDER * orders)


@dataclass(frozen=True, slots=True)
class ParsedFill:
    trade: str
    order: str
    qty: Decimal
    px: Decimal
    slip: Decimal
    realized: Decimal
    exact: Decimal
    theta_ok: bool


def parse_fills(ctx: StageContext, labels: Iterable[str]) -> list[ParsedFill]:
    parsed: list[ParsedFill] = []
    seen: set[str] = set()
    for label in labels:
        for row in ctx.by_day[label].fills or ():
            ask = parse_dec(row.decision_ask)  # a missing decision ask is FAIL (s7)
            try:
                theta = Decimal(row.fee_theta)
                theta_ok = theta.is_finite() and theta == FEE_THETA
            except (InvalidOperation, TypeError, ValueError):
                theta_ok = False
            qty, px, stored = parse_dec(row.qty), parse_dec(row.px), parse_dec(row.slippage)
            realized = parse_dec(row.fee_realized, nonfinite="pnl_nonfinite")
            exact = parse_dec(row.fee_exact, nonfinite="pnl_nonfinite")
            if not 0 <= px <= 1 or qty <= 0:
                raise fail("fill_sanity")
            if row.trade_id in seen:
                raise fail("duplicate_fill")
            seen.add(row.trade_id)
            slip = px - ask  # s7: slippage per fill is fill_px - decision ask
            if slip != stored:
                raise fail("slippage_inconsistent")
            parsed.append(
                ParsedFill(
                    row.trade_id, row.client_order_id, qty, px, slip, realized, exact, theta_ok
                )
            )
    return parsed


def _fee(qty: Decimal, px: Decimal) -> Decimal:
    return (FEE_THETA * qty * px * (1 - px)).quantize(CENT, rounding=ROUND_HALF_EVEN)


def fee_findings(fills: list[ParsedFill]) -> tuple[list[str], int]:
    """s7 halts (coefficient, per order, per stage) and the report-only per-fill mismatches."""
    found: list[str] = []
    if any(not f.theta_ok for f in fills):
        found.append(STOP_S7_COEFFICIENT)
    orders: dict[str, list[ParsedFill]] = {}
    for f in fills:
        orders.setdefault(f.order, []).append(f)
    for group in orders.values():
        expected = (
            FEE_THETA * sum((f.qty * f.px * (1 - f.px) for f in group), Decimal(0))
        ).quantize(CENT, rounding=ROUND_HALF_EVEN)
        slack = Decimal(0) if len(group) == 1 else CENT
        if abs(sum((f.realized for f in group), Decimal(0)) - expected) > slack:
            found.append(STOP_S7_PER_ORDER)
            break
    gap = abs(
        sum((f.realized for f in fills), Decimal(0)) - sum((f.exact for f in fills), Decimal(0))
    )
    if gap > fee_stage_tolerance(len(orders)):
        found.append(STOP_S7_PER_STAGE)
    mismatches = sum(1 for f in fills if f.realized != _fee(f.qty, f.px))
    return found, mismatches
