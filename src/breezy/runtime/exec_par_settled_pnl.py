"""EXEC-PAR BG-1c: settled-P&L accumulator and the K=1 pre-boot fill-ledger read (inert).

Spec: D-PREREG 10a (settled-P&L accumulator), 15 (units, attribution), 7 (parity
ledger), r4.1 K3/K9. Nothing in the node calls this yet.

**Seam.** There is no node-observable "settlement ingested" hook today: CLI-final
settlement outcomes are consumed by the offline labeling/settlement pipeline
(``analysis/labeling``, ``settlement/settlement_truth``), not by the live node. So
the accumulator is a PURE function over (entries, settlement outcomes) plus a store
writer, and no ingest pipeline is invented.

**How BG-5 calls it** (on the daily pass, after settlement ingest)::

    entries  = [EntryInput(arm_ns=slot.created_ns, fill=record, ambiguous_unresolved=...)
                for each entry slot joined to its DurableFillRecord]   # entries only
    outcomes = {instrument_id: held_side_won}   # CLI-final; absent = not settled yet
    rows     = settled_pnl_by_day(entries, outcomes, day_of_ns)        # day of ARM time
    persist_settled_pnl(latch, rows)                                   # ExecParStorePort
    # consumers read via latch.read_settled_pnl_day(d) and settled_pnl_or_fail(...)

Every input defect raises :class:`SettledPnlInputError` (missing or None is FAIL, never
zero). Currency values are never logged here: this module has no logger and its
error messages carry no amounts.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal, localcontext
from typing import Final, Protocol

from breezy.runtime.exec_par_records import SettledPnlDay

__all__ = [
    "FILL_PREFIX",
    "SETTLEMENT_DEADLINE_DAYS",
    "PreBootLedger",
    "SettledPnlReading",
    "check_monotonic",
    "SettledPnlRegression",
    "EntryInput",
    "FillLedgerCorrupt",
    "FillLike",
    "SettledPnlInputError",
    "SettledPnlMissing",
    "Timed",
    "persist_settled_pnl",
    "pre_boot_fill_ledger",
    "settled_pnl_by_day",
    "settled_pnl_or_fail",
]

#: Mirrors ``adapters.polymarket_us.exec.client.FILL_KEY_PREFIX`` (a test pins equality)
#: so this module never imports the byte-pinned exec client.
FILL_PREFIX: Final[str] = "exec/polymarket_us/fill/"
_PAYOUT_PER_CONTRACT: Final[Decimal] = Decimal(1)
_PRECISION: Final[int] = 60
_CENT: Final[Decimal] = Decimal("0.01")

#: An unsettled entry whose arm-time climate day is at least this many days old is
#: OVERDUE: scored as a full-cost loss like an AMBIGUOUS entry (review F2).
SETTLEMENT_DEADLINE_DAYS: Final[int] = 3


class Timed(Protocol):
    @property
    def ts_event(self) -> int: ...


class SettledPnlInputError(ValueError):
    """An accumulator input is missing, None or malformed (FAIL, never zero)."""


class SettledPnlMissing(RuntimeError):
    """No settled-P&L row exists for the day (counts as FAIL/trip, never 0)."""


class SettledPnlRegression(ValueError):
    """A settled-P&L write would shrink the entry count or raise pnl without a new settlement."""


class FillLedgerCorrupt(RuntimeError):
    """A durable fill row could not be decoded (fail closed, never skipped)."""


class FillLike(Protocol):
    """The slice of ``DurableFillRecord`` the accumulator reads."""

    @property
    def instrument_id(self) -> str: ...
    @property
    def order_side(self) -> str: ...
    @property
    def cumulative_qty(self) -> Decimal: ...
    @property
    def cumulative_cost(self) -> Decimal: ...
    @property
    def cumulative_fee(self) -> Decimal: ...
    @property
    def fee_reconciled(self) -> bool: ...
    @property
    def fee_coefficient_at_fill(self) -> Decimal | None: ...


@dataclass(frozen=True, slots=True)
class EntryInput:
    """One ENTRY: ``arm_ns`` is the ``arm_slot`` ``created_ns``; exits are not entries.

    ``fill.instrument_id`` is looked up in the caller's ``outcomes`` map, which must hold the
    HELD-SIDE outcome for that instrument: for a NO instrument the caller flips the YES
    sibling's resolution (YES resolved NO => the NO instrument won). This module never
    interprets legs or siblings.

    ``ambiguous_unresolved`` scores the entry as a full-cost loss whatever the outcome.
    With no fill, ``ambiguous_cost`` (cost plus fee, declared by the caller) is required.
    """

    arm_ns: int
    fill: FillLike | None
    ambiguous_unresolved: bool = False
    ambiguous_cost: Decimal | None = None


def _money(value: object) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
        raise SettledPnlInputError("amount is missing, non-finite or negative")
    return value


def _unreconciled_fee(fill: FillLike) -> Decimal:
    """Floor for a fee not yet reconciled: theta*C*p*(1-p) rounded UP to the cent."""
    theta = fill.fee_coefficient_at_fill
    if not isinstance(theta, Decimal) or not theta.is_finite() or theta < 0:
        raise SettledPnlInputError("unreconciled fee has no usable fee coefficient")
    qty, cost = _money(fill.cumulative_qty), _money(fill.cumulative_cost)
    return (theta * cost * (1 - cost / qty)).quantize(_CENT, rounding=ROUND_CEILING)


def _entry_cost(entry: EntryInput, day: _Day) -> Decimal:
    fill = entry.fill
    if fill is None:
        if entry.ambiguous_cost is None:
            raise SettledPnlInputError("ambiguous entry has neither a fill nor a cost")
        return _money(entry.ambiguous_cost)
    fee = _money(fill.cumulative_fee)
    if fill.fee_reconciled is not True:
        fee = max(fee, _unreconciled_fee(fill))
        day.fee_unreconciled += 1
    return _money(fill.cumulative_cost) + fee


def _check_fill(fill: FillLike | None) -> FillLike:
    if fill is None:
        raise SettledPnlInputError("entry has no durable fill record")
    if fill.order_side != "BUY":
        raise SettledPnlInputError("accumulator scores BUY entries only")
    if _money(fill.cumulative_qty) <= 0:
        raise SettledPnlInputError("fill quantity must be positive")
    return fill


class _Day:
    """Mutable per-day tally, private to one ``settled_pnl_by_day`` call."""

    def __init__(self) -> None:
        self.contributions: list[Decimal] = []
        self.settled = 0
        self.ambiguous = 0
        self.unsettled = 0
        self.overdue = 0
        self.fee_unreconciled = 0


def _contribution(
    entry: EntryInput, outcomes: Mapping[str, bool | None], day: _Day, overdue: bool
) -> None:
    if entry.ambiguous_unresolved:
        day.contributions.append(-_entry_cost(entry, day))
        day.ambiguous += 1
        return
    fill = _check_fill(entry.fill)
    if fill.instrument_id not in outcomes:
        if overdue:
            day.contributions.append(-_entry_cost(entry, day))
            day.overdue += 1
        else:
            day.unsettled += 1
        return
    won = outcomes[fill.instrument_id]
    if not isinstance(won, bool):
        raise SettledPnlInputError("settlement outcome is None or not a bool")
    payout = _money(fill.cumulative_qty) * _PAYOUT_PER_CONTRACT if won else Decimal(0)
    day.contributions.append(payout - _entry_cost(entry, day))
    day.settled += 1


def _canonical(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def settled_pnl_by_day(
    entries: Iterable[EntryInput],
    outcomes: Mapping[str, bool | None],
    day_of_ns: Callable[[int], str],
    *,
    today: str,
) -> dict[str, SettledPnlDay]:
    """Per arm-time day: sum of (payout - cost - fee) over settled entries.

    A win pays 1 per contract; AMBIGUOUS-unresolved entries are full-cost losses; an
    entry whose instrument has no outcome yet is PENDING (counted, not summed) until its
    arm-day is ``SETTLEMENT_DEADLINE_DAYS`` old relative to ``today`` (ISO date), then
    OVERDUE: a full-cost loss.
    The day is ``day_of_ns(arm_ns)`` only, never fill or settlement time. Pure and
    order-independent (exact decimal arithmetic).
    """
    try:
        today_date = dt.date.fromisoformat(today)
    except (TypeError, ValueError):
        raise SettledPnlInputError("today must be an ISO date") from None
    days: dict[str, _Day] = {}
    with localcontext() as ctx:
        ctx.prec = _PRECISION
        for entry in entries:
            arm = entry.arm_ns
            if isinstance(arm, bool) or not isinstance(arm, int) or arm <= 0:
                raise SettledPnlInputError("arm time must be a positive int")
            arm_day = day_of_ns(arm)
            try:
                age = (today_date - dt.date.fromisoformat(arm_day)).days
            except ValueError:
                raise SettledPnlInputError("day_of_ns returned a non-ISO day") from None
            _contribution(
                entry, outcomes, days.setdefault(arm_day, _Day()), age >= SETTLEMENT_DEADLINE_DAYS
            )
        return {
            day: SettledPnlDay(
                day=day,
                pnl=_canonical(sum(tally.contributions, Decimal(0))),
                settled_entries=tally.settled,
                ambiguous_entries=tally.ambiguous,
                unsettled_entries=tally.unsettled,
                overdue_entries=tally.overdue,
                fee_unreconciled_entries=tally.fee_unreconciled,
            )
            for day, tally in sorted(days.items())
        }


@dataclass(frozen=True, slots=True)
class SettledPnlReading:
    """A day's pnl WITH its counts: BG-5 must look at pending/overdue/ambiguous too."""

    pnl: Decimal
    settled: int
    ambiguous: int
    pending: int
    overdue: int
    fee_unreconciled: int


def settled_pnl_or_fail(row: SettledPnlDay | None) -> SettledPnlReading:
    """The day's pnl and counts; a missing row is a failure, never zero."""
    if row is None:
        raise SettledPnlMissing("no settled-P&L row for the day")
    return SettledPnlReading(
        pnl=row.pnl_decimal,
        settled=row.settled_entries,
        ambiguous=row.ambiguous_entries,
        pending=row.unsettled_entries,
        overdue=row.overdue_entries,
        fee_unreconciled=row.fee_unreconciled_entries,
    )


def check_monotonic(prior: SettledPnlDay | None, new: SettledPnlDay) -> None:
    """Refuse a write that shrinks the entry count or raises pnl with no new settlement."""
    if prior is None:
        return
    if new.total_entries < prior.total_entries:
        raise SettledPnlRegression("entry count would shrink")
    if new.pnl_decimal > prior.pnl_decimal and new.settled_entries <= prior.settled_entries:
        raise SettledPnlRegression("pnl would rise without a new settlement")


class _DayWriter(Protocol):
    def write_settled_pnl_day(self, record: SettledPnlDay) -> None: ...


def persist_settled_pnl(port: _DayWriter, rows: Mapping[str, SettledPnlDay]) -> None:
    """Write each day through the store port in ASCENDING day order; a failure propagates.

    A failure mid-loop leaves earlier days updated and later days stale. BG-5 must rerun:
    the computation is idempotent and the monotonic write guard accepts the identical rows.
    """
    for day in sorted(rows):
        port.write_settled_pnl_day(rows[day])


class _FillStore(Protocol):
    def get(self, key: str) -> bytes | None: ...
    def keys_with_prefix(self, prefix: str) -> list[str]: ...


@dataclass(frozen=True, slots=True)
class PreBootLedger[F]:
    """The K=1 fills plus whether no epoch row exists at all (vs. no K>1 epoch yet)."""

    fills: tuple[F, ...]
    no_epoch_rows: bool


def pre_boot_fill_ledger[F: Timed](
    store: _FillStore,
    *,
    first_k_gt1_boot_ts: int | None,
    has_epoch_rows: bool,
    decode: Callable[[bytes], F],
    in_family: Callable[[F], bool],
) -> PreBootLedger[F]:
    """Read-only: durable fills of one family strictly before the first K>1 epoch (spec 7).

    ``first_k_gt1_boot_ts`` ``None`` means no K>1 epoch yet: every fill qualifies; ``has_epoch_rows`` False
    sets ``no_epoch_rows`` so the caller can tell that apart. A
    garbled row raises :class:`FillLedgerCorrupt`; it is never skipped. Rows come back in
    store-key order (deterministic).
    """
    kept: list[F] = []
    for key in store.keys_with_prefix(FILL_PREFIX):
        raw = store.get(key)
        if raw is None:
            raise FillLedgerCorrupt("fill row vanished during the read")
        try:
            record = decode(raw)
        except Exception as exc:  # noqa: BLE001 - any decoder defect is a corrupt ledger row
            raise FillLedgerCorrupt("fill row is not decodable") from exc
        if first_k_gt1_boot_ts is not None and record.ts_event >= first_k_gt1_boot_ts:
            continue
        if in_family(record):
            kept.append(record)
    return PreBootLedger(fills=tuple(kept), no_epoch_rows=not has_epoch_rows)
