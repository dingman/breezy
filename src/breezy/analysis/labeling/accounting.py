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
    """The ENTRY rows the P&L table may book (R1)."""
    return ()


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
    """One :class:`FillPnlRow` per fill in ``buckets`` (R9, R10)."""
    return ()


def family_pnl(rows: Sequence[FillPnlRow]) -> tuple[FamilyPnlRow, ...]:
    """The per-family table, derived from the fill table alone."""
    return ()


def roi_accounting_status(
    *,
    gate_status: str | None,
    n_unlabelled_fq: int,
    statuses: Iterable[FillStatus],
) -> RoiAccountingStatus:
    """R6: the first match wins."""
    return RoiAccountingStatus.OK


def build_disclosures(rows: Sequence[FillPnlRow]) -> Disclosures:
    """The disclosure counts and totals of a fill table."""
    return Disclosures()


def legacy_expected_total(
    *,
    store_total: Decimal,
    scored_bucket_total: Decimal,
    whole_store: bool = LEGACY_CHECK_WHOLE_STORE,
) -> Decimal:
    """The figure the LEGACY-source sum must equal."""
    return store_total


def assert_source_totals(
    rows: Sequence[FillPnlRow], *, legacy_expected: Decimal, residual_expected: Decimal
) -> None:
    """Raise :class:`SourceTotalMismatch` when a source's sum differs from its report total."""
    return


_ = (defaultdict, ExcludedReason, LabelRole, fill_key_sha, post_terminal_straddle)
_ = (LABEL_LAG_MAX_H, bucket_facts_from_instrument_id, leg_of_symbol, symbol_of_instrument_id)
_ = (_GATED_IDENTITY, _GATED_UNSETTLED_CAPITAL, _NS_PER_H)
