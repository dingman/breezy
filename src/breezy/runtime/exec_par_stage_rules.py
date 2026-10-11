"""EXEC-PAR BG-5a: the s6, s9 and s15 rules and the stop ordering (pure)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from types import MappingProxyType
from typing import Final

from breezy.runtime.exec_par_stage_types import (
    CUMULATIVE_FRACTION,
    DAY_FRACTION,
    DEMOTE_K,
    RESTART_S1_K,
    S3_K,
    S6_SHARE_LIMIT,
    S9_MIN_ORDERS,
    S9_SHARE_LIMIT,
    S9_ZERO,
    STAGE_FRACTION,
    STOP_S15_CUMULATIVE,
    STOP_S15_DAY,
    STOP_S15_STAGE,
    TRAILING_DAYS,
    DayCounters,
    PnlPredicatePort,
    StageContext,
    StopOutcome,
    check_count,
    fail,
    parse_dec,
)


def _share(denied: int, posted: int) -> Decimal:
    total = denied + posted
    return Decimal(denied) / Decimal(total) if total else Decimal(0)


def _dropped_share(ctx: StageContext, window: Sequence[str]) -> Decimal | None:
    denied = posted = 0
    for label in window:
        row = ctx.by_day[label]
        if row.denied_counted is None or row.posted is None:
            return None
        denied += row.denied_counted
        posted += row.posted
    return _share(denied, posted)


def s6_share(ctx: StageContext) -> tuple[Decimal | None, bool]:
    """Trailing-5 share on the last closed day, and whether two consecutive windows trip."""
    if any(ctx.by_day[x].denied_counted is None for x in ctx.eligible):
        if ctx.stage_k == S3_K:
            raise fail("missing_counter:denied")
        return None, False
    last = _dropped_share(ctx, ctx.eligible[-TRAILING_DAYS:]) if ctx.eligible else None
    prev = _dropped_share(ctx, ctx.eligible[:-1][-TRAILING_DAYS:]) if ctx.eligible[:-1] else None
    tripped = (
        last is not None and prev is not None and last > S6_SHARE_LIMIT and prev > S6_SHARE_LIMIT
    )
    return last, tripped


def _window_flagged(row: DayCounters) -> bool:
    windows = row.windows or ()
    if sum(check_count(w.orders) for w in windows) < S9_MIN_ORDERS:
        return False
    notionals = [parse_dec(w.notional) for w in windows]
    total = sum(notionals, Decimal(0))
    if total <= S9_ZERO:
        raise fail("window_notional")
    return max(notionals) / total > S9_SHARE_LIMIT


def s9_flags(ctx: StageContext) -> tuple[tuple[str, ...], tuple[str, ...]]:
    last = ctx.eligible[-TRAILING_DAYS:]
    station = tuple(x for x in last if any(f.exceeded for f in ctx.by_day[x].open_flags or ()))
    burst = tuple(x for x in last if _window_flagged(ctx.by_day[x]))
    return station, burst


def _breaches(port: PnlPredicatePort, name: str, aggregate: Decimal, fraction: Decimal) -> bool:
    try:
        result = port.pnl_breaches_budget_fraction(aggregate_pnl=aggregate, fraction=fraction)
    except Exception:  # noqa: BLE001 - any raise is an integrity trip (K6)
        raise fail(f"predicate:{name}") from None
    if type(result) is not bool:
        raise fail(f"predicate:{name}")
    return result


def s15_findings(ctx: StageContext) -> list[str]:
    """Day, stage and cumulative stops, all through the predicate port."""
    port = ctx.snap.predicates
    found: list[str] = []
    stage_total = Decimal(0)
    day_hit = False
    for label in ctx.live:
        reading = ctx.pnl.get(label)
        if reading is None:
            continue
        stage_total += reading.pnl
        day_hit = day_hit or _breaches(port, "s15_day", reading.pnl, DAY_FRACTION)
    if day_hit:
        found.append(STOP_S15_DAY)
    if _breaches(port, "s15_stage", stage_total, STAGE_FRACTION):
        found.append(STOP_S15_STAGE)
    cumulative = sum(
        (
            r.pnl
            for day, r in ctx.pnl.items()
            if r is not None and ctx.first_k_day <= day <= ctx.today
        ),
        Decimal(0),
    )
    if _breaches(port, "s15_cumulative", cumulative, CUMULATIVE_FRACTION):
        found.append(STOP_S15_CUMULATIVE)
    return found


#: Tie-break between stops with the same target K: most severe first (item M11).
SEVERITY: Final[Mapping[StopOutcome, int]] = MappingProxyType(
    {
        StopOutcome.SUSPEND: 0,
        StopOutcome.K1_AMENDMENT: 1,
        StopOutcome.RESTART_S1: 2,
        StopOutcome.DOWN_ONE_STAGE: 3,
    }
)


def target_k(outcome: StopOutcome, k: int, effective_k: int) -> int:
    """The K the ramp goes to; never above a K the node was already forced down to (H2)."""
    if outcome is StopOutcome.RESTART_S1:
        target = RESTART_S1_K
    elif outcome is StopOutcome.DOWN_ONE_STAGE:
        target = DEMOTE_K[k]
    else:
        target = 1
    return min(target, effective_k) if effective_k < k else target
