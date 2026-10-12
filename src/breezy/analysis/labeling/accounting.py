"""Per-fill accounting P&L (TE-1 WP-B): every ledger fill appears once, with the bot's own net.

``accounting_rows`` is the P&L-side twin of ``admissible_rows``: it selects the ENTRY label rows
that are final and carry a net (including the pre-epoch ``unattributed`` rows that the statistics
selector must never read). ``build_fill_pnl`` consumes the report's ``bucket_ledger_fills`` output
and books each fill from exactly one source in the fixed order legacy store, then residual
settlement, then C2 label. ``family_pnl`` and the disclosures are derived from that table alone.

Nothing here is a statistic: no verdict, tally or ROI-for-decision is built from these sums
(E-TE1-a narrows AUT-2 D3 to statistics). Only ``scripts/analysis/portfolio_roi_report.py`` may
import this module (an AST guard enforces it).
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any, Final, Protocol

from breezy.adapters.polymarket_us.exec.client import DurableFillRecord
from breezy.analysis.labeling.attribution import fill_key_sha, post_terminal_straddle
from breezy.analysis.labeling.constants import LABEL_LAG_MAX_H
from breezy.analysis.labeling.instrument_facts import bucket_facts_from_instrument_id
from breezy.domain.instrument_leg import leg_of_symbol, symbol_of_instrument_id
from breezy.persistence.autonomy.label_schema import ExcludedReason, LabelRole
from breezy.persistence.autonomy.label_store import LabelRow
from breezy.persistence.family_manifest import FamilyManifest
from breezy.settlement.trial_scorer import ScoredTrial

__all__ = [
    "AMBIGUOUS_UNKNOWN",
    "FEE_DELTA_DISCLOSURE_REF",
    "LEGACY_CHECK_WHOLE_STORE",
    "NO_FILL_INTENTS_RECORDED",
    "NO_FILL_SOURCE",
    "POST_TERMINAL_NOTE",
    "POST_TERMINAL_REF",
    "UNKNOWN_FAMILY",
    "AccountingError",
    "AmbiguousAccountingRow",
    "Basis",
    "CliCheck",
    "CliFinalReader",
    "Disclosures",
    "FamilyPnlRow",
    "FillPnlRow",
    "FillStatus",
    "PnlSource",
    "RoiAccountingStatus",
    "SourceTotalMismatch",
    "accounting_rows",
    "assert_source_totals",
    "build_disclosures",
    "build_fill_pnl",
    "family_pnl",
    "legacy_expected_total",
    "roi_accounting_status",
]

#: The family label of a fill no source can attribute (the report's ``UNKNOWN`` label).
UNKNOWN_FAMILY: Final = "UNKNOWN"
#: Stage 0 S0-5 (2026-10-11): the whole-store total equals the SCORED-bucket sum, so the LEGACY
#: runtime check compares against the whole-store figure (``realised_pnl_after_fees_total``).
LEGACY_CHECK_WHOLE_STORE: Final = True
#: Stage 0 S0-11 (2026-10-11): five intents that never filled, read from the exec store's intent
#: history and resolver rows. A recorded fact, not a runtime measurement.
NO_FILL_INTENTS_RECORDED: Final = 5
NO_FILL_SOURCE: Final = "exec/polymarket_us/intent/history+resolver"
#: The strict ambiguity count is not knowable from the store (every IOC miss is AMBIGUOUS): never 0.
AMBIGUOUS_UNKNOWN: Final = "UNKNOWN"
#: Where the FU-3d fee delta lives (the sibling Markdown line), never in this JSON.
FEE_DELTA_DISCLOSURE_REF: Final = (
    "markdown: fee_unverified residuals (FU-3d, modelled, never booked)"
)
POST_TERMINAL_REF: Final = "TE-2 P16 / cebaab49"
POST_TERMINAL_NOTE: Final = (
    "sent by the live v1 node after the failed 10-05 halt; included in family P&L; excluded from "
    "the v1 tally by the terminal window (score_live_trials.py:1142). n_no_fill_intents and "
    "n_post_terminal_bridge are unrelated counts."
)

_SCORED: Final = "scored"
_RESIDUAL: Final = "residual"
_UNRECONCILED: Final = "unreconciled"
_BUY: Final = "BUY"
_SELL: Final = "SELL"
_GATED_IDENTITY: Final = "GATED_IDENTITY"
_GATED_UNSETTLED_CAPITAL: Final = "GATED_UNSETTLED_CAPITAL"
_NS_PER_H: Final = 3_600_000_000_000
_VENUE_CHECK_UNAVAILABLE: Final = "UNAVAILABLE"


def _dec(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _read_dec(raw: Mapping[str, object], key: str, *, nullable: bool = False) -> Decimal | None:
    value = raw.get(key)
    if value is None and nullable and key in raw:
        return None
    if not isinstance(value, str):
        raise AccountingError(f"accounting field {key!r} must be a decimal string")
    try:
        return Decimal(value)
    except ArithmeticError as exc:
        raise AccountingError(f"accounting field {key!r} is not a decimal") from exc


def _read_str(raw: Mapping[str, object], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str):
        raise AccountingError(f"accounting field {key!r} must be a str")
    return value


def _read_int(raw: Mapping[str, object], key: str) -> int:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise AccountingError(f"accounting field {key!r} must be an int")
    return value


def _read_bool(raw: Mapping[str, object], key: str) -> bool:
    value = raw.get(key)
    if not isinstance(value, bool):
        raise AccountingError(f"accounting field {key!r} must be a bool")
    return value


def _read_opt_bool(raw: Mapping[str, object], key: str) -> bool | None:
    if key not in raw:
        raise AccountingError(f"accounting field {key!r} is absent")
    value = raw[key]
    if value is not None and not isinstance(value, bool):
        raise AccountingError(f"accounting field {key!r} must be a bool or null")
    return value


def _read_opt_str(raw: Mapping[str, object], key: str) -> str | None:
    if key not in raw:
        raise AccountingError(f"accounting field {key!r} is absent")
    value = raw[key]
    if value is not None and not isinstance(value, str):
        raise AccountingError(f"accounting field {key!r} must be a str or null")
    return value


def _read_opt_int(raw: Mapping[str, object], key: str) -> int | None:
    if key not in raw:
        raise AccountingError(f"accounting field {key!r} is absent")
    value = raw[key]
    if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
        raise AccountingError(f"accounting field {key!r} must be an int or null")
    return value


class AccountingError(Exception):
    """Base of every accounting refusal."""


class AmbiguousAccountingRow(AccountingError):
    """Two accounting rows cover one fill: the net cannot be booked once."""


class SourceTotalMismatch(AccountingError):
    """A source's booked sum differs from the report's own total for that source."""


class FillStatus(StrEnum):
    EXIT = "EXIT"
    SETTLED_NWS_IMPLIED = "SETTLED_NWS_IMPLIED"
    RESIDUAL_PENDING = "RESIDUAL_PENDING"
    UNSETTLED = "UNSETTLED"
    LABELS_GATED = "LABELS_GATED"
    OPEN = "OPEN"
    UNPRICED = "UNPRICED"


class PnlSource(StrEnum):
    LEGACY = "LEGACY"
    RESIDUAL = "RESIDUAL"
    C2 = "C2"
    NONE = "NONE"


class CliCheck(StrEnum):
    AGREE = "AGREE"
    DISAGREE = "DISAGREE"
    UNAVAILABLE = "UNAVAILABLE"


class Basis(StrEnum):
    """How a fill's identity was reached; ``pre_epoch_bridge_post_terminal`` is the R11 straddle."""

    PRE_EPOCH_BRIDGE = "pre_epoch_bridge"
    PRE_EPOCH_BRIDGE_POST_TERMINAL = "pre_epoch_bridge_post_terminal"
    PRE_EPOCH_FOLD = "pre_epoch_fold"
    LEGACY_LATCH = "legacy_latch"
    RESIDUAL = "residual"
    C1_DECISION = "c1_decision"
    NONE = "none"


class RoiAccountingStatus(StrEnum):
    OK = "OK"
    GATED_IDENTITY = "GATED_IDENTITY"
    GATED_UNLABELLED_FQ = "GATED_UNLABELLED_FQ"
    GATED_UNSETTLED_CAPITAL = "GATED_UNSETTLED_CAPITAL"


#: ``(station, climate_day) -> the fresh NWS CLI FINAL tmax``, or ``None`` when none is readable.
CliFinalReader = Callable[[str, dt.date], int | None]


class AttributedFillLike(Protocol):
    """One ``bucket_ledger_fills`` item: the ledger fill and the trial id it was joined to."""

    @property
    def fill(self) -> DurableFillRecord: ...

    @property
    def trial_id(self) -> str | None: ...


class ResidualLike(Protocol):
    """One resolved residual settlement (the report's ``ResidualSettlement``)."""

    @property
    def realised_pnl(self) -> Decimal: ...

    @property
    def payout(self) -> Decimal: ...

    @property
    def settlement_tmax_f(self) -> int | None: ...


@dataclass(frozen=True)
class FillPnlRow:
    """One ledger fill's booked P&L. Private; ``net`` is ``None`` unless a source booked it."""

    fill_key: str
    client_order_id: str
    instrument_id: str
    climate_day: str | None
    family_id: str
    source: PnlSource
    status: FillStatus
    attribution_basis: Basis
    win: bool | None
    payout: Decimal | None
    cost: Decimal | None
    fee: Decimal | None
    net: Decimal | None
    fee_unverified: bool
    booked_tmax_f: int | None
    cli_final_check: CliCheck
    cli_final_net: Decimal | None
    entry_ask_known: bool
    venue_check: str = _VENUE_CHECK_UNAVAILABLE

    def to_json(self) -> dict[str, object]:
        return {
            "fill_key": self.fill_key,
            "client_order_id": self.client_order_id,
            "instrument_id": self.instrument_id,
            "climate_day": self.climate_day,
            "family_id": self.family_id,
            "source": self.source.value,
            "status": self.status.value,
            "attribution_basis": self.attribution_basis.value,
            "win": self.win,
            "payout": _dec(self.payout),
            "cost": _dec(self.cost),
            "fee": _dec(self.fee),
            "net": _dec(self.net),
            "fee_unverified": self.fee_unverified,
            "booked_tmax_f": self.booked_tmax_f,
            "cli_final_check": self.cli_final_check.value,
            "cli_final_net": _dec(self.cli_final_net),
            "entry_ask_known": self.entry_ask_known,
            "venue_check": self.venue_check,
        }

    @classmethod
    def from_json(cls, raw: Mapping[str, object]) -> FillPnlRow:
        """Strict inverse of :meth:`to_json`: a missing or wrong-typed field raises."""
        try:
            return cls(
                fill_key=_read_str(raw, "fill_key"),
                client_order_id=_read_str(raw, "client_order_id"),
                instrument_id=_read_str(raw, "instrument_id"),
                climate_day=_read_opt_str(raw, "climate_day"),
                family_id=_read_str(raw, "family_id"),
                source=PnlSource(_read_str(raw, "source")),
                status=FillStatus(_read_str(raw, "status")),
                attribution_basis=Basis(_read_str(raw, "attribution_basis")),
                win=_read_opt_bool(raw, "win"),
                payout=_read_dec(raw, "payout", nullable=True),
                cost=_read_dec(raw, "cost", nullable=True),
                fee=_read_dec(raw, "fee", nullable=True),
                net=_read_dec(raw, "net", nullable=True),
                fee_unverified=_read_bool(raw, "fee_unverified"),
                booked_tmax_f=_read_opt_int(raw, "booked_tmax_f"),
                cli_final_check=CliCheck(_read_str(raw, "cli_final_check")),
                cli_final_net=_read_dec(raw, "cli_final_net", nullable=True),
                entry_ask_known=_read_bool(raw, "entry_ask_known"),
                venue_check=_read_str(raw, "venue_check"),
            )
        except ValueError as exc:  # an unknown enum member
            raise AccountingError(f"fill_pnl row has an unknown vocabulary value: {exc}") from exc


@dataclass(frozen=True)
class FamilyPnlRow:
    family_id: str
    n_fills: int
    n_booked: int
    n_wins: int
    cost: Decimal
    fee: Decimal
    net: Decimal

    def to_json(self) -> dict[str, object]:
        return {
            "family_id": self.family_id,
            "n_fills": self.n_fills,
            "n_booked": self.n_booked,
            "n_wins": self.n_wins,
            "cost": str(self.cost),
            "fee": str(self.fee),
            "net": str(self.net),
        }

    @classmethod
    def from_json(cls, raw: Mapping[str, object]) -> FamilyPnlRow:
        cost, fee, net = (_read_dec(raw, key) for key in ("cost", "fee", "net"))
        assert cost is not None and fee is not None and net is not None
        return cls(
            family_id=_read_str(raw, "family_id"),
            n_fills=_read_int(raw, "n_fills"),
            n_booked=_read_int(raw, "n_booked"),
            n_wins=_read_int(raw, "n_wins"),
            cost=cost,
            fee=fee,
            net=net,
        )


@dataclass(frozen=True)
class Disclosures:
    """What the table cannot say on its own. Counts and totals only; every figure is private."""

    n_fee_unverified: int = 0
    n_null_pnl_final: int = 0
    n_settlement_disagree: int = 0
    n_cli_final_unavailable: int = 0
    cli_final_net_total: Decimal = Decimal(0)
    booked_total: Decimal = Decimal(0)
    cost_total: Decimal = Decimal(0)
    fee_total: Decimal = Decimal(0)
    n_entry_ask_unknown: int = 0
    n_labels_gated: int = 0
    n_no_fill_intents: int = NO_FILL_INTENTS_RECORDED
    no_fill_source: str = NO_FILL_SOURCE
    n_ambiguous_no_fill: str = AMBIGUOUS_UNKNOWN
    venue_positions_reconciled: bool = False
    fee_delta_disclosure_ref: str = FEE_DELTA_DISCLOSURE_REF
    n_post_terminal_bridge: int = 0
    post_terminal_pnl: Decimal = Decimal(0)
    post_terminal_wins: int = 0
    post_terminal_ref: str = POST_TERMINAL_REF
    post_terminal_note: str = POST_TERMINAL_NOTE

    def to_json(self) -> dict[str, object]:
        return {
            "n_fee_unverified": self.n_fee_unverified,
            "n_null_pnl_final": self.n_null_pnl_final,
            "n_settlement_disagree": self.n_settlement_disagree,
            "n_cli_final_unavailable": self.n_cli_final_unavailable,
            "cli_final_net_total": str(self.cli_final_net_total),
            "booked_total": str(self.booked_total),
            "cost_total": str(self.cost_total),
            "fee_total": str(self.fee_total),
            "n_entry_ask_unknown": self.n_entry_ask_unknown,
            "n_labels_gated": self.n_labels_gated,
            "n_no_fill_intents": self.n_no_fill_intents,
            "no_fill_source": self.no_fill_source,
            "n_ambiguous_no_fill": self.n_ambiguous_no_fill,
            "venue_positions_reconciled": self.venue_positions_reconciled,
            "fee_delta_disclosure_ref": self.fee_delta_disclosure_ref,
            "n_post_terminal_bridge": self.n_post_terminal_bridge,
            "post_terminal_pnl": str(self.post_terminal_pnl),
            "post_terminal_wins": self.post_terminal_wins,
            "post_terminal_ref": self.post_terminal_ref,
            "post_terminal_note": self.post_terminal_note,
        }

    @classmethod
    def from_json(cls, raw: Mapping[str, object]) -> Disclosures:
        decimals = {
            key: _read_dec(raw, key)
            for key in (
                "cli_final_net_total",
                "booked_total",
                "cost_total",
                "fee_total",
                "post_terminal_pnl",
            )
        }
        ambiguous = _read_str(raw, "n_ambiguous_no_fill")
        return cls(
            n_fee_unverified=_read_int(raw, "n_fee_unverified"),
            n_null_pnl_final=_read_int(raw, "n_null_pnl_final"),
            n_settlement_disagree=_read_int(raw, "n_settlement_disagree"),
            n_cli_final_unavailable=_read_int(raw, "n_cli_final_unavailable"),
            cli_final_net_total=decimals["cli_final_net_total"] or Decimal(0),
            booked_total=decimals["booked_total"] or Decimal(0),
            cost_total=decimals["cost_total"] or Decimal(0),
            fee_total=decimals["fee_total"] or Decimal(0),
            n_entry_ask_unknown=_read_int(raw, "n_entry_ask_unknown"),
            n_labels_gated=_read_int(raw, "n_labels_gated"),
            n_no_fill_intents=_read_int(raw, "n_no_fill_intents"),
            no_fill_source=_read_str(raw, "no_fill_source"),
            n_ambiguous_no_fill=ambiguous,
            venue_positions_reconciled=_read_bool(raw, "venue_positions_reconciled"),
            fee_delta_disclosure_ref=_read_str(raw, "fee_delta_disclosure_ref"),
            n_post_terminal_bridge=_read_int(raw, "n_post_terminal_bridge"),
            post_terminal_pnl=decimals["post_terminal_pnl"] or Decimal(0),
            post_terminal_wins=_read_int(raw, "post_terminal_wins"),
            post_terminal_ref=_read_str(raw, "post_terminal_ref"),
            post_terminal_note=_read_str(raw, "post_terminal_note"),
        )


def accounting_rows(
    rows: Iterable[LabelRow], *, legacy_scorer_ids: Collection[str]
) -> tuple[LabelRow, ...]:
    """The ENTRY rows the P&L table may book (R1).

    A row is selected when it is an entry row written by a non-legacy scorer (a legacy row IS a
    trial the scored store already pays), carries no exclusion other than ``unattributed``, and is
    final: admissible, or ``unattributed``, or settled. The predicate is static (no clock, no
    deadline) and equals ``is_final_row`` on the set it selects. It is the P&L-side twin of
    ``admissible_rows``, which stays the only selector for statistics.
    """
    return tuple(
        row
        for row in rows
        if row.role == LabelRole.ENTRY
        and row.scorer_id not in legacy_scorer_ids
        and row.excluded_reason in (ExcludedReason.UNATTRIBUTED, None)
        and (
            row.admissible
            or row.excluded_reason is ExcludedReason.UNATTRIBUTED
            or row.settled_outcome is not None
        )
    )


@dataclass(frozen=True)
class _Booking:
    """What one source booked for one fill (everything but the fill's own columns)."""

    source: PnlSource
    status: FillStatus
    basis: Basis
    family_id: str
    win: bool | None = None
    payout: Decimal | None = None
    net: Decimal | None = None
    booked_tmax_f: int | None = None
    entry_ask_known: bool = False


def _bucket_name(key: Any) -> str:
    return str(getattr(key, "value", key))


def _label_index(accounting: Sequence[LabelRow]) -> dict[str, list[LabelRow]]:
    index: dict[str, list[LabelRow]] = defaultdict(list)
    for row in accounting:
        if row.role == LabelRole.ENTRY:
            index[row.client_order_id].append(row)
    return index


def _legacy_booking(
    item: AttributedFillLike,
    scored: Mapping[str, ScoredTrial],
    family_of_trial: Callable[[str, str], str],
) -> _Booking:
    trial = scored.get(item.trial_id or "")
    if trial is None:
        raise AccountingError("a SCORED-bucket fill has no scored trial")
    qty = item.fill.cumulative_qty
    return _Booking(
        source=PnlSource.LEGACY,
        status=FillStatus.SETTLED_NWS_IMPLIED,
        basis=Basis.LEGACY_LATCH,
        family_id=family_of_trial(trial.trial_id, trial.climate_day),
        win=trial.held,
        payout=qty if trial.held else Decimal(0),
        net=trial.pnl,
        booked_tmax_f=trial.settlement_tmax_f,
        entry_ask_known=trial.entry_ask is not None,
    )


def _residual_booking(
    item: AttributedFillLike,
    residual: Mapping[str, ResidualLike],
    family_of_trial: Callable[[str, str], str],
    day: str,
) -> _Booking:
    trial_id = item.trial_id or ""
    family = family_of_trial(trial_id, day)
    settled = residual.get(trial_id)
    if settled is None:
        return _Booking(PnlSource.NONE, FillStatus.RESIDUAL_PENDING, Basis.RESIDUAL, family)
    return _Booking(
        source=PnlSource.RESIDUAL,
        status=FillStatus.SETTLED_NWS_IMPLIED,
        basis=Basis.RESIDUAL,
        family_id=family,
        win=settled.payout > 0,
        payout=settled.payout,
        net=settled.realised_pnl,
        booked_tmax_f=settled.settlement_tmax_f,
        entry_ask_known=False,
    )


def _basis_of(
    row: LabelRow, fill: DurableFillRecord, manifests: Mapping[str, FamilyManifest]
) -> Basis:
    if row.excluded_reason is not ExcludedReason.UNATTRIBUTED:
        return Basis.C1_DECISION
    manifest = manifests.get(row.family_id)
    if manifest is not None and post_terminal_straddle(manifest, row.climate_day, fill.ts_event):
        return Basis.PRE_EPOCH_BRIDGE_POST_TERMINAL
    return Basis.PRE_EPOCH_BRIDGE


def _c2_booking(
    row: LabelRow, fill: DurableFillRecord, manifests: Mapping[str, FamilyManifest]
) -> _Booking:
    basis = _basis_of(row, fill, manifests)
    if row.realized_pnl is None:
        return _Booking(PnlSource.C2, FillStatus.UNSETTLED, basis, row.family_id)
    win = row.settled_outcome
    payout = None if win is None else (fill.cumulative_qty if win else Decimal(0))
    tmax = None if row.settlement_tmax_f is None else int(row.settlement_tmax_f)
    return _Booking(
        source=PnlSource.C2,
        status=FillStatus.SETTLED_NWS_IMPLIED,
        basis=basis,
        family_id=row.family_id,
        win=win,
        payout=payout,
        net=row.realized_pnl,
        booked_tmax_f=tmax,
        entry_ask_known=row.entry_ask is not None,
    )


def _unbooked(status: FillStatus) -> _Booking:
    return _Booking(PnlSource.NONE, status, Basis.NONE, UNKNOWN_FAMILY)


def _unreconciled_booking(
    item: AttributedFillLike,
    labels: Mapping[str, list[LabelRow]],
    manifests: Mapping[str, FamilyManifest],
    *,
    gate_status: str | None,
    overdue: bool,
) -> _Booking:
    if gate_status == _GATED_IDENTITY:
        return _unbooked(FillStatus.LABELS_GATED)
    rows = labels.get(item.fill.client_order_id, [])
    if len(rows) > 1:
        raise AmbiguousAccountingRow("two accounting rows cover one fill")
    if rows:
        return _c2_booking(rows[0], item.fill, manifests)
    return _unbooked(FillStatus.UNPRICED if overdue else FillStatus.OPEN)


def _cli_check(
    fill: DurableFillRecord,
    facts: Any,
    booked_tmax_f: int | None,
    cli_check: CliFinalReader,
) -> tuple[CliCheck, Decimal | None]:
    """R10: the booked tmax against a fresh read; a disagreement carries a disclosure-only net."""
    if facts is None or booked_tmax_f is None:
        return CliCheck.UNAVAILABLE, None
    fresh = cli_check(facts.settlement_station, facts.climate_day)
    if fresh is None:
        return CliCheck.UNAVAILABLE, None
    if fresh == booked_tmax_f:
        return CliCheck.AGREE, None
    inside = facts.contains(fresh)
    is_no = leg_of_symbol(symbol_of_instrument_id(fill.instrument_id)) == "no"
    held = (not inside) if is_no else inside
    payout = fill.cumulative_qty if held else Decimal(0)
    return CliCheck.DISAGREE, payout - fill.cumulative_cost - fill.cumulative_fee


def build_fill_pnl(
    buckets: Mapping[Any, Sequence[AttributedFillLike]],
    *,
    scored: Mapping[str, ScoredTrial],
    residual: Mapping[str, ResidualLike],
    accounting: Sequence[LabelRow],
    gate_status: str | None,
    cli_check: CliFinalReader,
    now_ns: int,
    deadline_ns: Callable[[DurableFillRecord], int],
    family_of_trial: Callable[[str, str], str],
    manifests: Sequence[FamilyManifest] = (),
) -> tuple[FillPnlRow, ...]:
    """One :class:`FillPnlRow` per fill in ``buckets``, booked from exactly one source.

    The source order is fixed: the scored store (LEGACY) for the SCORED bucket, the residual
    settlement for the RESIDUAL bucket, the C2 accounting row for the UNRECONCILED bucket. Under a
    ``GATED_IDENTITY`` label gate no label-sourced row is booked. R9 gives the status; R10 the
    settlement check, which applies to SETTLED rows only.
    """
    labels = _label_index(accounting)
    by_family = {m.family_id: m for m in manifests}
    items = sorted(
        ((_bucket_name(key), item) for key, members in buckets.items() for item in members),
        key=lambda pair: (pair[1].fill.ts_event, pair[1].fill.venue_order_id),
    )
    rows = []
    for bucket, item in items:
        fill = item.fill
        facts = bucket_facts_from_instrument_id(fill.instrument_id)
        day = "" if facts is None else facts.climate_day.isoformat()
        overdue = now_ns >= deadline_ns(fill) + LABEL_LAG_MAX_H * _NS_PER_H
        if fill.order_side == _SELL:
            booking = _Booking(PnlSource.NONE, FillStatus.EXIT, Basis.NONE, UNKNOWN_FAMILY)
        elif fill.order_side != _BUY:
            raise AccountingError("a fill's order side is neither BUY nor SELL")
        elif bucket == _SCORED:
            booking = _legacy_booking(item, scored, family_of_trial)
        elif bucket == _RESIDUAL:
            booking = _residual_booking(item, residual, family_of_trial, day)
        elif bucket == _UNRECONCILED:
            booking = _unreconciled_booking(
                item, labels, by_family, gate_status=gate_status, overdue=overdue
            )
        else:
            raise AccountingError("an unknown ledger bucket")
        settled = booking.status is FillStatus.SETTLED_NWS_IMPLIED
        check, cli_net = (
            _cli_check(fill, facts, booking.booked_tmax_f, cli_check)
            if settled
            else (CliCheck.UNAVAILABLE, None)
        )
        exit_row = booking.status is FillStatus.EXIT
        rows.append(
            FillPnlRow(
                fill_key=fill_key_sha(fill),
                client_order_id=fill.client_order_id,
                instrument_id=fill.instrument_id,
                climate_day=day or None,
                family_id=booking.family_id,
                source=booking.source,
                status=booking.status,
                attribution_basis=booking.basis,
                win=booking.win if settled else None,
                payout=booking.payout if settled else None,
                cost=None if exit_row else fill.cumulative_cost,
                fee=None if exit_row else fill.cumulative_fee,
                net=booking.net if settled else None,
                fee_unverified=not fill.fee_reconciled,
                booked_tmax_f=booking.booked_tmax_f if settled else None,
                cli_final_check=check,
                cli_final_net=cli_net,
                entry_ask_known=booking.entry_ask_known,
            )
        )
    return tuple(rows)


def family_pnl(rows: Sequence[FillPnlRow]) -> tuple[FamilyPnlRow, ...]:
    """The per-family table, derived from the fill table alone (so it sums to the same total)."""
    grouped: dict[str, list[FillPnlRow]] = defaultdict(list)
    for row in rows:
        grouped[row.family_id].append(row)
    return tuple(
        FamilyPnlRow(
            family_id=family,
            n_fills=len(members),
            n_booked=sum(1 for r in members if r.net is not None),
            n_wins=sum(1 for r in members if r.win is True),
            cost=sum((r.cost or Decimal(0) for r in members), Decimal(0)),
            fee=sum((r.fee or Decimal(0) for r in members), Decimal(0)),
            net=sum((r.net or Decimal(0) for r in members), Decimal(0)),
        )
        for family, members in sorted(grouped.items())
    )


def roi_accounting_status(
    *,
    gate_status: str | None,
    n_unlabelled_fq: int,
    statuses: Iterable[FillStatus],
) -> RoiAccountingStatus:
    """R6: the first match wins.

    1. the label gate is ``GATED_IDENTITY``;
    2. an FQ fill no final C2 row covers (a fill that arrived after the run);
    3. the gate is ``GATED_UNSETTLED_CAPITAL`` or any fill is not SETTLED_NWS_IMPLIED / EXIT;
    4. otherwise OK.
    """
    if gate_status == _GATED_IDENTITY:
        return RoiAccountingStatus.GATED_IDENTITY
    if n_unlabelled_fq > 0:
        return RoiAccountingStatus.GATED_UNLABELLED_FQ
    settled = (FillStatus.SETTLED_NWS_IMPLIED, FillStatus.EXIT)
    if gate_status == _GATED_UNSETTLED_CAPITAL or any(s not in settled for s in statuses):
        return RoiAccountingStatus.GATED_UNSETTLED_CAPITAL
    return RoiAccountingStatus.OK


def build_disclosures(rows: Sequence[FillPnlRow]) -> Disclosures:
    """The disclosure counts and totals of a fill table (counts and totals only)."""
    settled = [r for r in rows if r.status is FillStatus.SETTLED_NWS_IMPLIED]
    booked = [r for r in rows if r.net is not None]
    straddle = [r for r in rows if r.attribution_basis is Basis.PRE_EPOCH_BRIDGE_POST_TERMINAL]
    zero = Decimal(0)
    return Disclosures(
        n_fee_unverified=sum(1 for r in rows if r.fee_unverified),
        n_null_pnl_final=sum(1 for r in rows if r.status is FillStatus.UNSETTLED),
        n_settlement_disagree=sum(1 for r in rows if r.cli_final_check is CliCheck.DISAGREE),
        n_cli_final_unavailable=sum(
            1 for r in settled if r.cli_final_check is CliCheck.UNAVAILABLE
        ),
        cli_final_net_total=sum(
            ((r.cli_final_net if r.cli_final_net is not None else r.net) or zero for r in settled),
            zero,
        ),
        booked_total=sum((r.net or zero for r in booked), zero),
        cost_total=sum((r.cost or zero for r in rows), zero),
        fee_total=sum((r.fee or zero for r in rows), zero),
        n_entry_ask_unknown=sum(1 for r in booked if not r.entry_ask_known),
        n_labels_gated=sum(1 for r in rows if r.status is FillStatus.LABELS_GATED),
        n_post_terminal_bridge=len(straddle),
        post_terminal_pnl=sum((r.net or zero for r in straddle), zero),
        post_terminal_wins=sum(1 for r in straddle if r.win is True),
    )


def legacy_expected_total(
    *,
    store_total: Decimal,
    scored_bucket_total: Decimal,
    whole_store: bool = LEGACY_CHECK_WHOLE_STORE,
) -> Decimal:
    """The figure the LEGACY-source sum must equal.

    Stage 0 S0-5 recorded that the whole-store total equals the SCORED-bucket sum, so the runtime
    check compares against the whole-store ``realised_pnl_after_fees_total``; a store holding a
    trial with no ledger fill would then fail loudly. ``whole_store=False`` is the subset form.
    """
    return store_total if whole_store else scored_bucket_total


def assert_source_totals(
    rows: Sequence[FillPnlRow], *, legacy_expected: Decimal, residual_expected: Decimal
) -> None:
    """Raise :class:`SourceTotalMismatch` when a source's sum differs from its report total."""
    for source, expected in (
        (PnlSource.LEGACY, legacy_expected),
        (PnlSource.RESIDUAL, residual_expected),
    ):
        booked = sum((r.net or Decimal(0) for r in rows if r.source is source), Decimal(0))
        if booked != expected:
            raise SourceTotalMismatch(
                f"the {source.value} booked sum differs from the report's own total for that source"
            )
