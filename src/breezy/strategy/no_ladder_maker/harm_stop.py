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

Counting units (review K1, coordinator ruling): W, L and n are all counted per STATION-DAY. A
day is a win only if EVERY fill on it won; any other fill (a loss, or unresolved, mismatched or
qty-not-1) makes it a loss day. ``w*`` (mean cost) and the cumulative PnL stay per FILL. The T3
n-gate is counted on station-days, so T3 can arm one fill later than a per-fill count would. A
pending fill (review J2) is excluded from every count.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from enum import StrEnum
from pathlib import Path
from typing import Final

from scipy.stats import beta

from breezy.adapters.polymarket_us.exec import submit_chain
from breezy.adapters.polymarket_us.exec.client import LONG_ONLY_SIDE, DurableFillRecord
from breezy.domain.instrument_leg import symbol_of_instrument_id

__all__ = [
    "SETTLEMENT_PENDING_WINDOW",
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
    "d1_fill_cost_conservative",
    "d1_verdict",
    "evaluate_harm_stop",
    "maker_loss_stop_artefact_path",
    "select_maker_fills",
    "settle_fill",
    "settlement_deadline",
    "station_of_slug",
]

#: D5: the taker theta of the cost model (a pinned rule constant, NOT the record's coefficient).
TAKER_THETA: Final[Decimal] = Decimal("0.0695")
#: plan r2 delta "Fee booking": the modelled fee is at least one cent.
MIN_MODELLED_FEE: Final[Decimal] = Decimal("0.01")
_CENT: Final[Decimal] = Decimal("0.01")
_ONE: Final[Decimal] = Decimal(1)
SETTLED_QTY: Final[Decimal] = Decimal(1)
#: review J2: a fill whose settlement is not yet knowable stays PENDING (excluded from every count)
#: until this long after the END of its local station-day; after that an unresolved, missing or
#: mismatched result counts as a LOSS. Pinned by ``test_j2_the_settlement_deadline_...``.
SETTLEMENT_PENDING_WINDOW: Final[timedelta] = timedelta(hours=48)

T1_MIN_LOSSES: Final[int] = 3
#: T2 arms at n >= 3 exactly as pre-registered (plan r2 delta D5: "n >= 3"); small-n CP-bound
#: firing is the declared rule, not a defect to retune.
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


def station_of_slug(slug: str) -> str:
    """The station (city) segment of a daily-high slug: ``tc-temp-<city>high-...``.

    ``""`` for anything that is not that grammar (no family station is empty), so a foreign or
    malformed instrument is simply out of scope instead of raising."""
    parts = slug.removesuffix("^no").split("-")
    if len(parts) < 3:
        return ""
    return str(parts[2]).removesuffix("high")


def _station_of(instrument_id: str) -> str:
    return station_of_slug(symbol_of_instrument_id(instrument_id))


def select_maker_fills(
    records: Iterable[DurableFillRecord], *, family_stations: frozenset[str]
) -> list[DurableFillRecord]:
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
    maker_fills: tuple[DurableFillRecord, ...]
    #: the family's OWN resolver-booked fills (``GET-`` trade id, TAKER-booked) on family slugs
    get_fills: tuple[DurableFillRecord, ...]
    #: any open AMBIGUOUS intent on a family slug (it may be a fill the poll never sees)
    open_ambiguous_family_intent: bool


def classify_family_fills(
    records: Sequence[DurableFillRecord],
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
            station_of_slug(slug) in family_stations for slug in open_ambiguous_slugs
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


def d1_fill_cost(record: DurableFillRecord) -> Decimal:
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


def d1_fill_cost_conservative(record: DurableFillRecord) -> Decimal:
    """Review K5: the cost when :func:`d1_fill_cost` cannot price the fill (no positive quantity,
    or a price outside [0, 1]). It still books the modelled taker fee, at its one-cent floor, over
    the booked fee: an unpriceable fill is never costed cheaper than a priceable one."""
    try:
        return d1_fill_cost(record)
    except ValueError:
        fee = max(record.cumulative_fee, MIN_MODELLED_FEE)
        cost: Decimal = record.cumulative_cost + fee
        return cost


# -- settlement of one fill ----------------------------------------------------------------------


class FillOutcome(StrEnum):
    WIN = "WIN"
    LOSS = "LOSS"
    #: unresolved, missing or mismatched settlement PAST the deadline: counts as a LOSS
    UNRESOLVED = "UNRESOLVED"
    #: not yet resolvable and still before the deadline (review J2): excluded from every count
    PENDING = "PENDING"


@dataclass(frozen=True, slots=True, kw_only=True)
class SettledFill:
    station_day: str
    cost: Decimal
    outcome: FillOutcome
    cause: str


def settlement_deadline(climate_day: date, *, std_utc_offset_hours: float) -> datetime:
    """When an unresolved fill on ``climate_day`` stops being PENDING (review J2).

    The climate day runs local-STANDARD midnight to midnight (the registry's fixed offset), so it
    ends at ``climate_day + 1`` 00:00 local standard time; the deadline is
    :data:`SETTLEMENT_PENDING_WINDOW` after that. UTC, timezone-aware."""
    local_midnight = datetime.combine(climate_day + timedelta(days=1), time(0), tzinfo=UTC)
    end_of_day = local_midnight - timedelta(hours=std_utc_offset_hours)
    return end_of_day + SETTLEMENT_PENDING_WINDOW


def settle_fill(
    *,
    station_day: str,
    cost: Decimal,
    quantity: Decimal,
    venue_yes_resolved: bool | None,
    cli_yes: bool | None,
    pending: bool = False,
) -> SettledFill:
    """A BUY NO fill wins iff the venue resolved YES false AND the CLI final agrees.

    ``cli_yes`` is whether the CLI final lands inside the fill's rung (None: no usable final).
    ``pending`` (the caller's "before the settlement deadline") turns an unresolved, missing or
    mismatched result into PENDING instead of UNRESOLVED; a resolved fill is scored at once.
    """
    unresolved = FillOutcome.PENDING if pending else FillOutcome.UNRESOLVED

    def _made(outcome: FillOutcome, cause: str) -> SettledFill:
        return SettledFill(station_day=station_day, cost=cost, outcome=outcome, cause=cause)

    if quantity != SETTLED_QTY:
        return _made(FillOutcome.LOSS, "qty_not_1")
    if venue_yes_resolved is None:
        return _made(unresolved, "venue_settlement_missing")
    if cli_yes is None:
        return _made(unresolved, "cli_final_missing")
    if venue_yes_resolved != cli_yes:
        return _made(unresolved, "settlement_mismatch")
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
    #: fills still before their settlement deadline: in no other count
    pending: int
    #: the COUNTED fills (pending excluded); ``w_star`` and ``cum_pnl`` are over these
    fills: int
    w_star: Decimal | None
    cum_pnl: Decimal
    cp_upper: float | None
    hold_reasons: tuple[str, ...]


def evaluate_harm_stop(
    fills: Sequence[SettledFill], *, blocked_reasons: Sequence[str] = ()
) -> HarmStopResult:
    """D5 over the settled fills. FAIL outranks HOLD; HOLD outranks PASS.

    W, L and n are per station-day (a day is a win only if every fill on it won); ``w*`` and the
    cumulative PnL are per fill. PENDING fills are in no count. T2 arms at n >= 3 as pre-registered
    (D5: "n >= 3"); that small-n firing is the declared rule."""
    counted = [f for f in fills if f.outcome is not FillOutcome.PENDING]
    days: dict[str, bool] = {}
    for f in counted:
        days[f.station_day] = days.get(f.station_day, True) and f.outcome is FillOutcome.WIN
    wins = sum(1 for won in days.values() if won)
    losses = len(days) - wins
    n = len(days)
    w_star = sum((f.cost for f in counted), Decimal(0)) / len(counted) if counted else None
    cum_pnl = sum(
        ((_ONE - f.cost) if f.outcome is FillOutcome.WIN else -f.cost for f in counted),
        Decimal(0),
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
        unresolved=sum(1 for f in counted if f.outcome is FillOutcome.UNRESOLVED),
        pending=len(fills) - len(counted),
        fills=len(counted),
        w_star=w_star,
        cum_pnl=cum_pnl,
        cp_upper=cp_upper,
        hold_reasons=tuple(blocked_reasons),
    )
