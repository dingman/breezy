"""ARM D1: the harm stop for the maker family ``pm_us_no_maker_sharp_v1`` (plan r2 delta D5).

Pure: no I/O, no clock, no network. The rule text is the pre-declared D5 paragraph, implemented
verbatim:

    Settled fill = a filled qty-1 BUY NO resolved by venue settlement, cross-checked against the
    CLI final; a fill with unresolved, missing or mismatched settlement counts as a LOSS until
    resolved (fail closed). cost_i = posted bid + max(venue-reported fee, taker theta=0.0695
    round-half-even cent fee), slip 0. W wins, L losses (two NO legs on one ladder-day lose at
    most once; losses count distinct station-days), n = W+L, w* = mean(cost_i). FAIL if ANY:
    (T1) L >= 3; (T2) n >= 3 and the one-sided 95% Clopper-Pearson upper bound on W/n < w*;
    (T3) n >= 4 and cumulative realised net PnL after fees <= -w*. PASS otherwise; PASS with zero
    fills.

Two further fail-closed facts come from the B6 fill-record selector freeze (formerly fixture-level
in ``tests/unit/test_maker_fill_record_selector_freeze.py``, now owned here): the family's booked
MAKER fills are the ``POLL-`` BUY fills on family stations; the verdict is HOLD (never PASS) while
resolver-booked ``GET-`` family fills or an open AMBIGUOUS family intent may hide a fill the poll
never saw. Nothing here reads ``fee_reconciled`` (rebate-clamped and unreadable-commission fills
are exactly the unreconciled ones; filtering them out would hide the worst fills).

Counting units (W counts winning FILLS; L counts distinct loss STATION-DAYS) follow the D5 text
literally; the unresolved/mismatched/qty-not-1 fills are LOSSES for L, for ``w*`` and for PnL.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

from scipy.stats import beta

from breezy.adapters.polymarket_us.exec import submit_chain
from breezy.adapters.polymarket_us.exec.client import LONG_ONLY_SIDE
from breezy.domain.instrument_leg import symbol_of_instrument_id

__all__ = [
    "TAKER_THETA",
    "FamilyFillClassification",
    "FillOutcome",
    "HarmStopResult",
    "HarmVerdict",
    "SettledFill",
    "classify_family_fills",
    "cp_upper_bound",
    "d1_fail_closed",
    "d1_fill_cost",
    "d1_verdict",
    "evaluate_harm_stop",
    "maker_loss_stop_artefact_path",
    "select_maker_fills",
    "settle_fill",
]

#: D5: the taker theta of the cost model (a pinned rule constant, NOT the record's coefficient).
TAKER_THETA: Final[Decimal] = Decimal("0.0695")
#: plan r2 delta "Fee booking": the modelled fee is at least one cent.
MIN_MODELLED_FEE: Final[Decimal] = Decimal("0.01")
_CENT: Final[Decimal] = Decimal("0.01")
_ONE: Final[Decimal] = Decimal(1)
SETTLED_QTY: Final[Decimal] = Decimal(1)

T1_MIN_LOSSES: Final[int] = 3
T2_MIN_N: Final[int] = 3
T3_MIN_N: Final[int] = 4
CP_CONFIDENCE: Final[float] = 0.95

RESOLVER_TRADE_ID_PREFIX: Final[str] = "GET-"
#: ``derived/<this>/latest.json`` -- the file ``LossStopProbe`` reads for this family.
ARTEFACT_DIR_NAME: Final[str] = "maker-loss-stop"


def maker_loss_stop_artefact_path(catalog_root: Path) -> Path:
    """Sibling of the quote-tape catalog root, beside the FQ probe's own derived artefact."""
    return catalog_root.parent / "derived" / ARTEFACT_DIR_NAME / "latest.json"


# -- the frozen selector / classifier (B6) -------------------------------------------------------


def _station_of_slug(slug: str) -> str:
    """The station (city) segment of a daily-high slug: ``tc-temp-<city>high-...``.

    ``""`` for anything that is not that grammar (no family station is empty), so a foreign or
    malformed instrument is simply out of scope instead of raising."""
    parts = slug.removesuffix("^no").split("-")
    if len(parts) < 3:
        return ""
    return str(parts[2]).removesuffix("high")


def _station_of(instrument_id: str) -> str:
    return _station_of_slug(symbol_of_instrument_id(instrument_id))


def select_maker_fills(records: Iterable[Any], *, family_stations: frozenset[str]) -> list[Any]:
    """THE FROZEN SELECTOR: ``POLL-`` marker AND BUY AND station in the family scope."""
    return [
        r
        for r in records
        if submit_chain.is_maker_poll_fill(r.trade_id)
        and r.order_side == LONG_ONLY_SIDE
        and _station_of(r.instrument_id) in family_stations
    ]


@dataclass(frozen=True)
class FamilyFillClassification:
    """What D1 may know about the family's durable fills."""

    #: the family's POLL- maker-booked BUY fills (the frozen selector's result)
    maker_fills: tuple[Any, ...]
    #: the family's OWN resolver-booked fills (``GET-`` trade id, TAKER-booked) on family slugs
    get_fills: tuple[Any, ...]
    #: any open AMBIGUOUS intent on a family slug (it may be a fill the poll never sees)
    open_ambiguous_family_intent: bool


def classify_family_fills(
    records: Sequence[Any],
    *,
    family_stations: frozenset[str],
    open_ambiguous_slugs: Iterable[str],
) -> FamilyFillClassification:
    """THE FROZEN CLASSIFIER. Never reads ``fee_reconciled``."""
    get_fills = tuple(
        r
        for r in records
        if isinstance(r.trade_id, str)
        and r.trade_id.startswith(RESOLVER_TRADE_ID_PREFIX)
        and r.order_side == LONG_ONLY_SIDE
        and _station_of(r.instrument_id) in family_stations
    )
    return FamilyFillClassification(
        maker_fills=tuple(select_maker_fills(records, family_stations=family_stations)),
        get_fills=get_fills,
        open_ambiguous_family_intent=any(
            _station_of_slug(slug) in family_stations for slug in open_ambiguous_slugs
        ),
    )


def d1_fail_closed(classification: FamilyFillClassification) -> bool:
    """D1 must fail closed (never PASS) while the maker tally may be missing family fills."""
    return bool(classification.get_fills) or classification.open_ambiguous_family_intent


def d1_verdict(classification: FamilyFillClassification, *, criterion_met: bool) -> str:
    """``HOLD`` while failing closed, else ``PASS`` / ``CONTINUE`` by the criterion."""
    if d1_fail_closed(classification):
        return "HOLD"
    return "PASS" if criterion_met else "CONTINUE"


# -- the D5 cost ---------------------------------------------------------------------------------


def modelled_taker_fee(*, quantity: Decimal, price: Decimal) -> Decimal:
    """``theta * C * p * (1 - p)`` at theta 0.0695, round-half-even to the cent, floor 0.01."""
    if price < 0 or price > _ONE:
        raise ValueError(f"fill price {price} is outside [0, 1]")
    exact = TAKER_THETA * quantity * price * (_ONE - price)
    return max(exact.quantize(_CENT, rounding=ROUND_HALF_EVEN), MIN_MODELLED_FEE)


def d1_fill_cost(record: Any) -> Decimal:
    """D5: ``cost_i = posted bid + max(venue-reported fee, modelled taker fee)``, slip 0.

    The posted bid is the maker fill's cost (``cumulative_cost``, a maker fills AT its bid); the
    venue-reported fee is ``cumulative_fee`` (never the raw venue string, which may be a clamped
    rebate). Raises ``ValueError`` for a record without a positive quantity (fail closed).
    """
    quantity: Decimal = record.cumulative_qty
    if quantity <= 0:
        raise ValueError("a fill without a positive quantity has no cost")
    price = record.cumulative_cost / quantity
    fee = max(record.cumulative_fee, modelled_taker_fee(quantity=quantity, price=price))
    cost: Decimal = record.cumulative_cost + fee
    return cost


# -- settlement of one fill ----------------------------------------------------------------------


class FillOutcome(StrEnum):
    WIN = "WIN"
    LOSS = "LOSS"
    #: unresolved, missing or mismatched settlement: counts as a LOSS until resolved
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True, slots=True, kw_only=True)
class SettledFill:
    station_day: str
    cost: Decimal
    outcome: FillOutcome
    cause: str


def settle_fill(
    *,
    station_day: str,
    cost: Decimal,
    quantity: Decimal,
    venue_yes_resolved: bool | None,
    cli_yes: bool | None,
) -> SettledFill:
    """A BUY NO fill wins iff the venue resolved YES false AND the CLI final agrees.

    ``cli_yes`` is whether the CLI final lands inside the fill's rung (None: no usable final).
    """

    def _made(outcome: FillOutcome, cause: str) -> SettledFill:
        return SettledFill(station_day=station_day, cost=cost, outcome=outcome, cause=cause)

    if quantity != SETTLED_QTY:
        return _made(FillOutcome.LOSS, "qty_not_1")
    if venue_yes_resolved is None:
        return _made(FillOutcome.UNRESOLVED, "venue_settlement_missing")
    if cli_yes is None:
        return _made(FillOutcome.UNRESOLVED, "cli_final_missing")
    if venue_yes_resolved != cli_yes:
        return _made(FillOutcome.UNRESOLVED, "settlement_mismatch")
    return _made(FillOutcome.LOSS if venue_yes_resolved else FillOutcome.WIN, "settled")


# -- the rule ------------------------------------------------------------------------------------


def cp_upper_bound(wins: int, n: int) -> float:
    """One-sided 95% Clopper-Pearson upper bound on a success probability (exact beta quantile)."""
    if n <= 0 or wins < 0 or wins > n:
        raise ValueError(f"impossible counts: wins={wins}, n={n}")
    if wins == n:
        return 1.0
    return float(beta.ppf(CP_CONFIDENCE, wins + 1, n - wins))


class HarmVerdict(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    HOLD = "HOLD"


@dataclass(frozen=True, slots=True, kw_only=True)
class HarmStopResult:
    verdict: HarmVerdict
    triggers: tuple[str, ...]
    wins: int
    losses: int
    n: int
    unresolved: int
    fills: int
    w_star: Decimal | None
    cum_pnl: Decimal
    cp_upper: float | None
    hold_reasons: tuple[str, ...]


def evaluate_harm_stop(
    fills: Sequence[SettledFill], *, blocked_reasons: Sequence[str] = ()
) -> HarmStopResult:
    """D5 over the settled fills. FAIL outranks HOLD; HOLD outranks PASS."""
    loss_days = {f.station_day for f in fills if f.outcome is not FillOutcome.WIN}
    wins = sum(1 for f in fills if f.outcome is FillOutcome.WIN)
    losses = len(loss_days)
    n = wins + losses
    w_star = sum((f.cost for f in fills), Decimal(0)) / len(fills) if fills else None
    cum_pnl = sum(
        ((_ONE - f.cost) if f.outcome is FillOutcome.WIN else -f.cost for f in fills), Decimal(0)
    )
    cp_upper = cp_upper_bound(wins, n) if n >= T2_MIN_N else None
    triggers: list[str] = []
    if losses >= T1_MIN_LOSSES:
        triggers.append("T1")
    if cp_upper is not None and w_star is not None and cp_upper < float(w_star):
        triggers.append("T2")
    if n >= T3_MIN_N and w_star is not None and cum_pnl <= -w_star:
        triggers.append("T3")
    if triggers:
        verdict = HarmVerdict.FAIL
    elif blocked_reasons:
        verdict = HarmVerdict.HOLD
    else:
        verdict = HarmVerdict.PASS
    return HarmStopResult(
        verdict=verdict,
        triggers=tuple(triggers),
        wins=wins,
        losses=losses,
        n=n,
        unresolved=sum(1 for f in fills if f.outcome is FillOutcome.UNRESOLVED),
        fills=len(fills),
        w_star=w_star,
        cum_pnl=cum_pnl,
        cp_upper=cp_upper,
        hold_reasons=tuple(blocked_reasons),
    )
