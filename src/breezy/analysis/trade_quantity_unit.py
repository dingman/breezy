"""MAKER S1 WP2: which unit does a recorded trade print's ``size`` carry? (pure core)

Plan r3 WP2 (``docs/plans/backlog/MAKER_2026-10-12/S1_preconditions_plan_r3.md``). The venue's trade
print ``size`` is unit-unresolved (``parsing.TRADE_QUANTITY_UNIT``). Our own create-path fills
carry a known quantity and cost, so a fill matched to the print it produced predicts that
print's size under each hypothesis; the hypotheses that survive every counted match are the verdict.

Pure: no Nautilus, no pyarrow, no I/O, and nothing from ``breezy.adapters.polymarket_us.exec`` (the
exec package is touched only by the script, which converts a ``DurableFillRecord`` into a
:class:`Fill`). The firewall check is INJECTED (``Clearance``) for the same reason.

``Print`` input shape (JSONL, one object per line; WP1's print rows have this shape; every key is
required, unknown keys are refused)::

    {"ts_ns": 1790870525229407434, "side": "BUYER" | "SELLER", "price": "0.35",
     "size": "1", "instrument_id": "<yes-instrument>.POLYMARKET_US", "trade_id": "<venue id>"}

``price`` is the YES-frame price of the YES instrument; ``side`` is the aggressor.

Matching (size-blind, else the test is circular): a NO fill (bought as a SELL of the YES book at
``1 - cost``) matches a SELLER print at ``1 - cost``; a YES fill matches a BUYER print at ``cost``;
both within ``MATCH_WINDOW_NS`` of the fill's ``tsEvent`` on the fill's YES instrument. A match
counts only with exactly one candidate and not summed (``DurableFillRecord`` is cumulative per
venue order, ``exec/client.py:933-957``).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Final, Literal

from breezy.domain.instrument_leg import (
    base_symbol_of,
    leg_of_symbol,
    symbol_of_instrument_id,
)

__all__ = [
    "MATCH_WINDOW_NS",
    "TRADE_CAPTURE_START_NS",
    "UNIT_HYPOTHESES",
    "USD_BRACKET",
    "Clearance",
    "ClearanceRefused",
    "Fill",
    "KeepDecision",
    "OwnFillMatch",
    "Print",
    "candidates_of",
    "classify_trade_quantity_unit",
    "consistent_hypotheses",
    "counted_matches",
    "inversion_verdict",
    "is_counted",
    "keep_decision",
    "match_fill",
    "parse_print",
    "predicted_size",
]

#: 2026-09-17T09:00Z: the first trade-print capture rotation. A fill stamped earlier has no recorded
#: print to match, and a resolver record's ``tsEvent`` is discovery time, not a print clock.
TRADE_CAPTURE_START_NS: Final[int] = 1_789_635_600_000_000_000

#: Clock tolerance: create-path ``tsEvent`` is the venue ``Execution.transactTime`` (print clock).
MATCH_WINDOW_NS: Final[int] = 5_000_000_000

UNIT_HYPOTHESES: Final[tuple[str, ...]] = ("CONTRACTS", "USD_NOTIONAL_YES", "USD_NOTIONAL_TAKER")
USD_BRACKET: Final[frozenset[str]] = frozenset({"USD_NOTIONAL_YES", "USD_NOTIONAL_TAKER"})

#: Same set as WP1's ``MAKER_STATIONS``; restated so this module does not depend on WP1.
_STATIONS: Final[frozenset[str]] = frozenset({"LAX", "MDW", "MIA", "SFO"})
_MIN_COUNTED: Final[int] = 2
_RESOLVER_PREFIX: Final[str] = "GET-"
_SIDES: Final[tuple[str, str]] = ("BUYER", "SELLER")
_PRINT_KEYS: Final[frozenset[str]] = frozenset(
    {"ts_ns", "side", "price", "size", "instrument_id", "trade_id"}
)

Inversion = Literal["HOLDS", "CONTRADICTED", "NO_PRINT"]


class ClearanceRefused(Exception):
    """The post-freeze firewall refused this station-day (no covering declaration)."""


#: ``(station, climate_day) -> None``, raising :class:`ClearanceRefused`.
Clearance = Callable[[str, dt.date], None]


@dataclass(frozen=True)
class Print:
    ts_ns: int
    side: str
    price: Decimal
    size: Decimal
    instrument_id: str
    trade_id: str


@dataclass(frozen=True)
class Fill:
    """One own create-path fill (cumulative per venue order), resolved to station and day."""

    venue_order_id: str
    instrument_id: str
    order_side: str
    qty: Decimal
    cost: Decimal
    ts_event_ns: int
    trade_id: str | None
    fee_reconciled: bool
    station: str
    climate_day: dt.date

    @property
    def leg(self) -> Literal["YES", "NO"]:
        return "NO" if leg_of_symbol(symbol_of_instrument_id(self.instrument_id)) == "no" else "YES"

    @property
    def unit_cost(self) -> Decimal:
        return self.cost / self.qty

    @property
    def yes_instrument(self) -> str:
        symbol, dot, venue = self.instrument_id.partition(".")
        return f"{base_symbol_of(symbol)}{dot}{venue}"


@dataclass(frozen=True)
class OwnFillMatch:
    leg: str
    fill_cost: Decimal
    fill_qty: Decimal
    candidate_count: int
    anti_candidate_count: int
    print_price_yes: Decimal
    print_size: Decimal | None
    summed: bool


@dataclass(frozen=True)
class KeepDecision:
    kept: bool
    reason: str


def parse_print(row: Mapping[str, object]) -> Print:
    """One strict print row; ``ValueError`` on a missing/unknown key, bad side or bad number."""
    keys = set(row)
    if keys != _PRINT_KEYS:
        raise ValueError(
            f"print row keys differ: missing {sorted(_PRINT_KEYS - keys)}, "
            f"extra {sorted(keys - _PRINT_KEYS)}"
        )
    side = row["side"]
    if side not in _SIDES:
        raise ValueError(f"print side must be BUYER or SELLER, got {side!r}")
    ts = row["ts_ns"]
    if isinstance(ts, bool) or not isinstance(ts, int):
        raise TypeError("print ts_ns must be an integer")
    return Print(
        ts_ns=ts,
        side=str(side),
        price=_decimal(row["price"], "price"),
        size=_decimal(row["size"], "size"),
        instrument_id=str(row["instrument_id"]),
        trade_id=str(row["trade_id"]),
    )


def _decimal(value: object, name: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise ValueError(f"print {name} is not a number: {value!r}") from None
    if not number.is_finite():
        raise ValueError(f"print {name} must be finite: {value!r}")
    return number


def keep_decision(fill: Fill, clearance: Clearance) -> KeepDecision:
    """Whether ``fill`` may be matched; the firewall is consulted last, for a kept fill only."""
    if fill.order_side != "BUY":
        return KeepDecision(False, "NOT_A_BUY")
    if fill.ts_event_ns < TRADE_CAPTURE_START_NS:
        return KeepDecision(False, "PRE_CAPTURE")
    if fill.trade_id is None:
        return KeepDecision(False, "NULL_TRADE_ID")
    if fill.trade_id.startswith(_RESOLVER_PREFIX):
        return KeepDecision(False, "RESOLVER_TRADE_ID")
    if not fill.fee_reconciled:
        return KeepDecision(False, "UNRECONCILED_FEE")
    if fill.station not in _STATIONS:
        return KeepDecision(False, "STATION_OUT_OF_SCOPE")
    try:
        clearance(fill.station, fill.climate_day)
    except ClearanceRefused:
        return KeepDecision(False, "FIREWALL_REFUSED")
    return KeepDecision(True, "KEPT")


def _target_yes_price(fill: Fill) -> Decimal:
    return Decimal(1) - fill.unit_cost if fill.leg == "NO" else fill.unit_cost


def _required_side(fill: Fill) -> str:
    return "SELLER" if fill.leg == "NO" else "BUYER"


def _in_window(fill: Fill, prints: Sequence[Print]) -> list[Print]:
    return [
        p
        for p in prints
        if p.instrument_id == fill.yes_instrument
        and abs(p.ts_ns - fill.ts_event_ns) <= MATCH_WINDOW_NS
    ]


def candidates_of(fill: Fill, prints: Sequence[Print]) -> list[Print]:
    """Inversion-consistent prints: required aggressor, inverted price, in window; never size."""
    target, side = _target_yes_price(fill), _required_side(fill)
    return [p for p in _in_window(fill, prints) if p.side == side and p.price == target]


def _anti_candidates(fill: Fill, prints: Sequence[Print]) -> list[Print]:
    """Opposite aggressor at the inverted price, or any print at the un-inverted price."""
    target, raw = _target_yes_price(fill), fill.unit_cost
    chosen = {id(p) for p in candidates_of(fill, prints)}
    return [p for p in _in_window(fill, prints) if id(p) not in chosen and p.price in (target, raw)]


def predicted_size(hypothesis: str, match: OwnFillMatch) -> Decimal:
    if hypothesis == "CONTRACTS":
        return match.fill_qty
    if hypothesis == "USD_NOTIONAL_YES":
        return match.print_price_yes * match.fill_qty
    if hypothesis == "USD_NOTIONAL_TAKER":
        return match.fill_cost
    raise ValueError(f"unknown unit hypothesis {hypothesis!r}")


def consistent_hypotheses(match: OwnFillMatch) -> frozenset[str]:
    """Hypotheses whose predicted size equals the match's print size (exact Decimal equality)."""
    if match.print_size is None:
        return frozenset()
    return frozenset(h for h in UNIT_HYPOTHESES if predicted_size(h, match) == match.print_size)


def match_fill(fill: Fill, prints: Sequence[Print]) -> OwnFillMatch:
    cands = candidates_of(fill, prints)
    antis = _anti_candidates(fill, prints)

    def build(size: Decimal | None, summed: bool) -> OwnFillMatch:
        return OwnFillMatch(
            leg=fill.leg,
            fill_cost=fill.cost,
            fill_qty=fill.qty,
            candidate_count=len(cands),
            anti_candidate_count=len(antis),
            print_price_yes=_target_yes_price(fill),
            print_size=size,
            summed=summed,
        )

    if not cands:
        return build(None, False)
    singles = [build(c.size, False) for c in cands]
    plain = singles[0] if len(cands) == 1 else build(None, False)
    if any(consistent_hypotheses(s) for s in singles):
        return plain
    # no single print explains the fill: a cumulative order's clips, never a counted match
    total = sum((c.size for c in cands), Decimal(0))
    if len(cands) > 1 and consistent_hypotheses(build(total, True)):
        return build(total, True)
    if len(cands) == 1 and fill.qty > 1:
        return build(cands[0].size, True)
    return plain


def is_counted(match: OwnFillMatch) -> bool:
    return match.candidate_count == 1 and not match.summed


def counted_matches(matches: Sequence[OwnFillMatch]) -> list[OwnFillMatch]:
    return [m for m in matches if is_counted(m)]


def inversion_verdict(match: OwnFillMatch) -> Inversion:
    if match.candidate_count >= 1:
        return "HOLDS"
    return "CONTRADICTED" if match.anti_candidate_count >= 1 else "NO_PRINT"


def classify_trade_quantity_unit(
    matches: Sequence[OwnFillMatch],
) -> tuple[str, frozenset[str], str]:
    """``(verdict, surviving, reason)``: a hypothesis, ``BRACKETED_USD`` or ``UNRESOLVED``."""
    counted = counted_matches(matches)
    surviving = frozenset(UNIT_HYPOTHESES)
    for match in counted:
        surviving &= consistent_hypotheses(match)
    if len(counted) < _MIN_COUNTED:
        return (
            "UNRESOLVED",
            surviving if counted else frozenset(),
            f"{len(counted)} counted match(es); at least {_MIN_COUNTED} required",
        )
    if not surviving:
        return "UNRESOLVED", surviving, "counted matches contradict every hypothesis"
    if len(surviving) == 1:
        (only,) = surviving
        return only, surviving, f"{len(counted)} counted matches leave only {only}"
    if surviving == USD_BRACKET:
        return "BRACKETED_USD", surviving, "both USD hypotheses survive; Stage 0 runs under both"
    return (
        "UNRESOLVED",
        surviving,
        f"surviving set {sorted(surviving)} is not a single hypothesis or the USD pair",
    )
