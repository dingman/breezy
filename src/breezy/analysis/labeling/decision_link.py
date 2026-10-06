"""The backfill-only decision bridge over the node's log files (AUT-2 r7 WP3, section 3.4.4).

For a PRE_EPOCH fill the bridge recovers the probability the bound artefact produced at decision
time from the node's own ``SHADOW_DECISION`` output; it never computes one afresh (L-2). The join
keys on ``client_order_id`` inside bounded windows and never on line adjacency:

1. the durable fill's ``client_order_id`` and ``trade_id``;
2. the ``OrderFilled`` line with both;
3. the ``OrderInitialized`` line with the same ``client_order_id``, at most
   ``BRIDGE_INIT_TO_FILL_MAX_S`` before the fill;
4. exactly one ``SHADOW_DECISION`` ``Take`` on the same market whose ``now_ns`` lies in
   ``[init - BRIDGE_TAKE_TO_INIT_MAX_S, init]``.

It reads log FILES only (journald is never read) and runs only for PRE_EPOCH fills; a POST_EPOCH
fill is attributed through C1 and nothing else (Q2).
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Final, Literal

from breezy.adapters.polymarket_us.exec.client import DurableFillRecord
from breezy.analysis.labeling.attribution import BackfillRefused
from breezy.analysis.labeling.constants import BRIDGE_INIT_TO_FILL_MAX_S, BRIDGE_TAKE_TO_INIT_MAX_S
from breezy.analysis.labeling.epoch import EpochClass
from breezy.analysis.labeling.probability import (
    LegMismatch,
    artefact_p_raw,
    bought_leg_probabilities,
)
from breezy.domain.instrument_leg import base_symbol_of, leg_of_symbol, symbol_of_instrument_id
from breezy.persistence.autonomy.label_schema import PSource

__all__ = [
    "BridgeEvent",
    "BridgeMatch",
    "BridgeReport",
    "BridgeUnmatched",
    "bridge_decision",
    "bridge_report",
    "parse_log_line",
    "read_log_events",
]

_NS_PER_S: Final = 1_000_000_000
_ANSI: Final = re.compile(r"\x1b\[[0-9;]*m")
_STAMP: Final = re.compile(r"^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2}):(\d{2})\.(\d{1,9})Z")
_FIELD: Final = re.compile(r"(?:^|[(,\s])(client_order_id|instrument_id|trade_id)=([^,)\s]+)")
_TAKE_NOW: Final = re.compile(r"'now_ns': (\d+)")
_TAKE_INSTRUMENT: Final = re.compile(r"'instrument_id': '([^']+)'")
_TAKE_SIDE: Final = re.compile(r"'side': '(yes|no)'")
_TAKE_P: Final = re.compile(r"'p_hat': ([0-9.eE+-]+)")

EventKind = Literal["take", "init", "filled"]


@dataclass(frozen=True)
class BridgeEvent:
    """One bridge-relevant log line. ``ts_ns`` is the line's own UTC stamp."""

    kind: EventKind
    ts_ns: int
    instrument_id: str
    client_order_id: str | None = None
    trade_id: str | None = None
    side: str | None = None
    p_hat: str | None = None
    now_ns: int | None = None


@dataclass(frozen=True)
class BridgeMatch:
    p_at_decision: float
    p_raw_at_decision: float | None
    decision_now_ns: int
    p_source: PSource = PSource.ARTEFACT_RECOMPUTE


@dataclass(frozen=True)
class BridgeUnmatched:
    reason: str
    p_source: PSource = PSource.NONE


@dataclass(frozen=True)
class BridgeReport:
    n: int
    matched: int
    p_null_count: int
    match_rate: Decimal | None


def _stamp_ns(line: str) -> int | None:
    found = _STAMP.match(line)
    if found is None:
        return None
    day, hh, mm, ss, frac = found.groups()
    moment = dt.datetime.fromisoformat(f"{day}T{hh}:{mm}:{ss}").replace(tzinfo=dt.UTC)
    seconds = int(moment.timestamp())
    return seconds * _NS_PER_S + int(frac.ljust(9, "0"))


def _event_fields(line: str) -> dict[str, str]:
    return {key: value for key, value in _FIELD.findall(line)}


def _take_event(line: str, ts_ns: int) -> BridgeEvent | None:
    if "'kind': 'Take'" not in line:
        return None
    now = _TAKE_NOW.search(line)
    instrument = _TAKE_INSTRUMENT.search(line)
    side = _TAKE_SIDE.search(line)
    p_hat = _TAKE_P.search(line)
    if not (now and instrument and side and p_hat):
        return None
    return BridgeEvent(
        kind="take",
        ts_ns=ts_ns,
        instrument_id=instrument.group(1),
        side=side.group(1),
        p_hat=p_hat.group(1),
        now_ns=int(now.group(1)),
    )


def parse_log_line(line: str) -> BridgeEvent | None:
    """The bridge event on one log line, or ``None`` for every other line."""
    text = _ANSI.sub("", line).strip()
    if not text:
        return None
    ts_ns = _stamp_ns(text)
    if ts_ns is None:
        return None
    if "SHADOW_DECISION" in text:
        return _take_event(text, ts_ns)
    kind: EventKind
    if "OrderInitialized(" in text:
        kind = "init"
    elif "OrderFilled(" in text:
        kind = "filled"
    else:
        return None
    fields = _event_fields(text)
    if "client_order_id" not in fields or "instrument_id" not in fields:
        return None
    return BridgeEvent(
        kind=kind,
        ts_ns=ts_ns,
        instrument_id=fields["instrument_id"],
        client_order_id=fields["client_order_id"],
        trade_id=fields.get("trade_id"),
    )


def read_log_events(log_files: Sequence[Path]) -> tuple[BridgeEvent, ...]:
    """Every bridge event in the given node log files, in file then line order."""
    events: list[BridgeEvent] = []
    for path in log_files:
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                event = parse_log_line(line)
                if event is not None:
                    events.append(event)
    return tuple(events)


def _leg_of(instrument_id: str) -> str:
    return leg_of_symbol(symbol_of_instrument_id(instrument_id))


def _slug_of(instrument_id: str) -> str:
    return base_symbol_of(symbol_of_instrument_id(instrument_id))


def _filled_event(fill: DurableFillRecord, events: Iterable[BridgeEvent]) -> BridgeEvent | None:
    for event in events:
        if (
            event.kind == "filled"
            and event.client_order_id == fill.client_order_id
            and event.trade_id == fill.trade_id
        ):
            return event
    return None


def _init_event(
    fill: DurableFillRecord, filled: BridgeEvent, events: Iterable[BridgeEvent]
) -> BridgeEvent | None:
    earliest = filled.ts_ns - BRIDGE_INIT_TO_FILL_MAX_S * _NS_PER_S
    for event in events:
        if (
            event.kind == "init"
            and event.client_order_id == fill.client_order_id
            and earliest <= event.ts_ns <= filled.ts_ns
        ):
            return event
    return None


def bridge_decision(
    fill: DurableFillRecord,
    events: Sequence[BridgeEvent],
    *,
    epoch_class: EpochClass,
    recalibration: str | None,
) -> BridgeMatch | BridgeUnmatched:
    """Recover the artefact's bought-leg probability for one PRE_EPOCH fill, or say why not.

    Raises ``BackfillRefused`` for a POST_EPOCH fill.
    """
    if epoch_class is not EpochClass.PRE_EPOCH:
        raise BackfillRefused("the decision bridge never runs on a post-epoch fill")
    if fill.trade_id is None:
        return BridgeUnmatched("no_trade_id")
    filled = _filled_event(fill, events)
    if filled is None:
        return BridgeUnmatched("no_fill_line")
    init = _init_event(fill, filled, events)
    if init is None:
        return BridgeUnmatched("no_init_line")
    low = init.ts_ns - BRIDGE_TAKE_TO_INIT_MAX_S * _NS_PER_S
    slug = _slug_of(fill.instrument_id)
    takes = [
        e
        for e in events
        if e.kind == "take"
        and e.now_ns is not None
        and low <= e.now_ns <= init.ts_ns
        and _slug_of(e.instrument_id) == slug
    ]
    if not takes:
        return BridgeUnmatched("no_take_in_window")
    if len(takes) > 1:
        return BridgeUnmatched("ambiguous_takes")
    take = takes[0]
    assert take.p_hat is not None and take.side is not None and take.now_ns is not None
    leg = _leg_of(fill.instrument_id)
    result = bought_leg_probabilities(p_hat=take.p_hat, p_hat_raw=None, side=take.side, leg=leg)
    if isinstance(result, LegMismatch):
        return BridgeUnmatched("side_leg_mismatch")
    p_hat = float(take.p_hat)
    raw_yes = artefact_p_raw(p_hat, recalibration=recalibration)
    raw = None if raw_yes is None else (raw_yes if leg == "yes" else 1.0 - raw_yes)
    return BridgeMatch(
        p_at_decision=result.p_at_decision, p_raw_at_decision=raw, decision_now_ns=take.now_ns
    )


def bridge_report(results: Sequence[BridgeMatch | BridgeUnmatched]) -> BridgeReport:
    """The backfill's match rate and the number of entry rows left with a null probability."""
    matched = sum(1 for r in results if isinstance(r, BridgeMatch))
    n = len(results)
    rate = Decimal(matched) / Decimal(n) if n else None
    return BridgeReport(n=n, matched=matched, p_null_count=n - matched, match_rate=rate)
