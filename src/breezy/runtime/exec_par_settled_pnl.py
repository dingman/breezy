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

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import Final, Protocol

from breezy.runtime.exec_par_records import SettledPnlDay

__all__ = [
    "FILL_PREFIX",
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


class Timed(Protocol):
    @property
    def ts_event(self) -> int: ...


class SettledPnlInputError(ValueError):
    """An accumulator input is missing, None or malformed (FAIL, never zero)."""


class SettledPnlMissing(RuntimeError):
    """No settled-P&L row exists for the day (counts as FAIL/trip, never 0)."""


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


@dataclass(frozen=True, slots=True)
class EntryInput:
    """One ENTRY: ``arm_ns`` is the ``arm_slot`` ``created_ns``; exits are not entries.

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


def _entry_cost(entry: EntryInput) -> Decimal:
    fill = entry.fill
    if fill is None:
        if entry.ambiguous_cost is None:
            raise SettledPnlInputError("ambiguous entry has neither a fill nor a cost")
        return _money(entry.ambiguous_cost)
    return _money(fill.cumulative_cost) + _money(fill.cumulative_fee)


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


def _contribution(entry: EntryInput, outcomes: Mapping[str, bool | None], day: _Day) -> None:
    if entry.ambiguous_unresolved:
        day.contributions.append(-_entry_cost(entry))
        day.ambiguous += 1
        return
    fill = _check_fill(entry.fill)
    if fill.instrument_id not in outcomes:
        day.unsettled += 1
        return
    won = outcomes[fill.instrument_id]
    if not isinstance(won, bool):
        raise SettledPnlInputError("settlement outcome is None or not a bool")
    payout = _money(fill.cumulative_qty) * _PAYOUT_PER_CONTRACT if won else Decimal(0)
    day.contributions.append(payout - _entry_cost(entry))
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
) -> dict[str, SettledPnlDay]:
    """Per arm-time day: sum of (payout - cost - fee) over settled entries.

    A win pays 1 per contract; AMBIGUOUS-unresolved entries are full-cost losses; an
    entry whose instrument has no outcome yet is counted ``unsettled`` and not summed.
    The day is ``day_of_ns(arm_ns)`` only, never fill or settlement time. Pure and
    order-independent (exact decimal arithmetic).
    """
    days: dict[str, _Day] = {}
    with localcontext() as ctx:
        ctx.prec = _PRECISION
        for entry in entries:
            arm = entry.arm_ns
            if isinstance(arm, bool) or not isinstance(arm, int) or arm <= 0:
                raise SettledPnlInputError("arm time must be a positive int")
            _contribution(entry, outcomes, days.setdefault(day_of_ns(arm), _Day()))
        return {
            day: SettledPnlDay(
                day=day,
                pnl=_canonical(sum(tally.contributions, Decimal(0))),
                settled_entries=tally.settled,
                ambiguous_entries=tally.ambiguous,
                unsettled_entries=tally.unsettled,
            )
            for day, tally in sorted(days.items())
        }


def settled_pnl_or_fail(row: SettledPnlDay | None) -> Decimal:
    """The day's settled P&L; a missing row is a failure, never zero."""
    if row is None:
        raise SettledPnlMissing("no settled-P&L row for the day")
    return row.pnl_decimal


class _DayWriter(Protocol):
    def write_settled_pnl_day(self, record: SettledPnlDay) -> None: ...


def persist_settled_pnl(port: _DayWriter, rows: Mapping[str, SettledPnlDay]) -> None:
    """Write each day through the store port in day order; a failure propagates."""
    for day in sorted(rows):
        port.write_settled_pnl_day(rows[day])


class _FillStore(Protocol):
    def get(self, key: str) -> bytes | None: ...
    def keys_with_prefix(self, prefix: str) -> list[str]: ...


def pre_boot_fill_ledger[F: Timed](
    store: _FillStore,
    *,
    first_k_gt1_boot_ts: int | None,
    decode: Callable[[bytes], F],
    in_family: Callable[[F], bool],
) -> tuple[F, ...]:
    """Read-only: durable fills of one family strictly before the first K>1 epoch (spec 7).

    ``first_k_gt1_boot_ts`` ``None`` means no K>1 epoch yet: every fill qualifies. A
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
        except Exception:  # noqa: BLE001 - any decoder defect is a corrupt ledger row
            raise FillLedgerCorrupt("fill row is not decodable") from None
        if first_k_gt1_boot_ts is not None and record.ts_event >= first_k_gt1_boot_ts:
            continue
        if in_family(record):
            kept.append(record)
    return tuple(kept)
