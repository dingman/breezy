"""Pure helpers for ``continuous_strategy`` (R3.4 move; bodies unchanged).

Time constants, the ask-snapshot dataclasses and three side-effect-free
functions. Re-exported from ``continuous_strategy`` at the old path.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Final, Literal

from nautilus_trader.model.identifiers import InstrumentId

from breezy.adapters.polymarket_us.exec.client import DurableFillRecord

if TYPE_CHECKING:  # pragma: no cover - typing only
    from nautilus_trader.model.data import QuoteTick

_NS_PER_MINUTE: Final[int] = 60_000_000_000
#: GAP fix 2026-09-15: for the `take:` log line's `staleness_s=` field only.
_NS_PER_SECOND: Final[int] = 1_000_000_000
#: F-4 (STALL_FOLLOWUPS_F1_F4_2026-09-24.md): the `open_intent_wait:` log
#: line's own re-log cadence while the SAME intent_id persists.
_NS_PER_HOUR: Final[int] = 60 * _NS_PER_MINUTE
#: GAP fix 2026-09-15: `NO_ask = 1 - bid`, for the NO-side offer-tape row's
#: `ask` field ONLY when `no_decision` is a `Refuse` that never reached a
#: `Take.limit_price` -- mirrors `decision.py`'s own inversion exactly,
#: recomputed here purely for logging (never for a decision).
_ONE: Final[Decimal] = Decimal(1)

Trigger = Literal["quote_tick", "on_data", "depth"]
Source = Literal["quote", "depth"]


@dataclass(frozen=True, slots=True)
class _AskSnapshot:
    """The minimal ask-side view `_hunt_tick` needs, from either a `QuoteTick`
    or a `OrderBookDepth10` ask level (Phase 0b). `tick_eval.py` stays typed
    on primitives only -- this is the one construction seam that lets
    `_hunt_tick` treat the two sources identically.
    """

    instrument_id: InstrumentId
    #: F-1b (plan STALL_FOLLOWUPS_F1_F4_2026-09-24.md, Rev 3.1): optional --
    #: `None` when a Depth10 frame carries a real bid but no real ask (the
    #: cheapest NO population, `on_order_book_depth`). `size` is `0` in that
    #: case. `_snapshot_from_quote` always sets a real `ask` (a `QuoteTick`
    #: cannot exist without both sides), so the QuoteTick path is unaffected.
    ask: Decimal | None
    size: int
    ts_event: int
    source: Source
    #: S3b (plan NO_SIDE_EDGE_2026-09-14 S3): the YES bid side of the SAME
    #: frame, additive -- every existing construction site gains these two
    #: fields below; a caller that omits them (there are none left in this
    #: module) would get `None`, which `evaluate_both_sides` already treats
    #: as a missing bid (NO refuses `not_executable`).
    bid: Decimal | None = None
    bid_size: Decimal | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class _EligibleSetup:
    """The three per-tick facts the YES path and the NO-only hunt (F-1a)
    both need, derived identically from the same snapshot -- extracted (A1,
    plan ``STALL_FOLLOWUPS_F1_F4_2026-09-24.md``) so `_hunt_no_only` can
    share them with `_hunt_tick`'s YES path without duplicating the calls.
    """

    width_code: int
    m_code: int
    fee_coefficient: Decimal | None
    staleness_ns: int | None


def _snapshot_from_quote(tick: QuoteTick) -> _AskSnapshot:
    return _AskSnapshot(
        instrument_id=tick.instrument_id,
        ask=tick.ask_price.as_decimal(),
        size=int(tick.ask_size),
        ts_event=tick.ts_event,
        source="quote",
        bid=tick.bid_price.as_decimal(),
        bid_size=tick.bid_size.as_decimal(),
    )


def _startup_evidence_summary(
    evidence: dict[str, object] | None,
    *,
    now_ns: int,
    decisions: Mapping[str, str],
) -> str:
    """AC-13/N2 (R-8, 2026-09-12): a pure, unit-tested renderer for the
    never-arm walk's ONE INFO summary line, emitted on ALL FIVE
    `_run_never_arm_walk` return paths (L-30: observability by presence of
    a line, never by the absence of a halt error). Accepts ``evidence is
    None`` (the evidence-missing return path). ``decisions`` maps each
    candidate instrument id already evaluated (in this call) to one of
    ``"present-flat" | "absent-flat" | "LONG" | "UNKNOWN"``; it may be
    empty when the walk halted before any per-slug decision was made
    (family halt, evidence-missing, fill-walk-unreadable).
    """
    if evidence is None:
        return (
            f"continuous_rung_hold startup_evidence: evidence=absent decisions={dict(decisions)!r}"
        )
    eof_complete = evidence.get("eof_complete")
    position_read_refused = evidence.get("position_read_refused")
    fill_walk_complete = evidence.get("fill_walk_complete")
    positions = evidence.get("positions")
    page_slug_count = len(positions) if isinstance(positions, list) else None
    ts = evidence.get("ts_ns")
    age_secs: float | None = None
    if isinstance(ts, int) and not isinstance(ts, bool):
        age_secs = (now_ns - ts) / 1_000_000_000
    return (
        "continuous_rung_hold startup_evidence: "
        f"eof_complete={eof_complete!r} "
        f"position_read_refused={position_read_refused!r} "
        f"fill_walk_complete={fill_walk_complete!r} "
        f"page_slug_count={page_slug_count!r} "
        f"age_secs={age_secs!r} "
        f"decisions={dict(decisions)!r}"
    )


def _per_contract_reconciled_fee(record: DurableFillRecord) -> Decimal | None:
    """The per-contract fee a `DurableFillRecord` supports, when known.

    ONE shared derivation for both `TrialDayRecord.fee` call sites (companion
    ruling to option B, domain review of a9fd0fb): `ContinuousRungHoldStrategy
    ._recorded_fee_for` (create-path fill, `_consume_or_flag_duplicate`) and
    `_consume_trial_from_fill_record` (the boot never-arm walk's fill-record
    join). The boot walk re-adopts open positions through this join on every
    16:50Z reboot, so a fee derivation that only ran on the create path would
    re-impose the unknown-fee refusal on any later rung of that station-day
    after every restart -- this function makes both sites agree byte-for-byte.

    `None` unless `record` is `fee_reconciled` and carries a positive
    `cumulative_qty` -- an unreconciled or zero-qty record leaves `q`
    UNKNOWN, and `station_day_admission` must keep refusing rather than
    guess (never relaxed by this helper). Deliberately NEVER
    `event.commission`: the resolver path emits a synthetic `Money(0)`
    there, indistinguishable from a genuine zero fee (PREREG v3
    fee-unreconciled-residual ruling).
    """
    if not record.fee_reconciled or record.cumulative_qty <= 0:
        return None
    return record.cumulative_fee / record.cumulative_qty
