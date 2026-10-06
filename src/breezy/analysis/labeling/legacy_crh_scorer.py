"""The retired-kind ``Scorer`` and the scorer-refusal gate (AUT-2 r7 WP3, section 3.3; P2-6, P3).

``current_rung_hold`` and ``continuous_rung_hold`` stay out of the live gate, but their durable
fills still need C2 rows. :class:`LegacyCrhScorer` maps each frozen CRH ``ScoredTrial`` joined to a
durable BUY fill into one unattributed row (``decision_id`` null, ``p_source=none``, P&L =
``ScoredTrial.pnl x qty``). A SELL fill is never priced from ``ScoredTrial`` (it has no exit
semantics): it is an ``exit`` row with null P&L, counted in ``legacy_sell_rows``, final for
completeness. These rows emit no cash record: CRH cash stays in the legacy reconciliation.

A kind's scorer may refuse only once every attributed fill of that kind has a final C2 row
(:func:`scorer_may_refuse`).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, ClassVar, Final

from breezy.adapters.polymarket_us.exec.client import DurableFillRecord
from breezy.analysis.labeling.attribution import fq_rung_id
from breezy.analysis.labeling.fq_scorer import apply_prior, label_id_of
from breezy.analysis.labeling.instrument_facts import bucket_facts_from_instrument_id
from breezy.domain.instrument_leg import base_symbol_of, leg_of_symbol, symbol_of_instrument_id
from breezy.persistence.autonomy.label_schema import ExcludedReason, LabelRole, PSource
from breezy.persistence.autonomy.label_store import LabelRow
from breezy.settlement.trial_scorer import ScoredTrial

__all__ = [
    "LEGACY_SCORER_ID",
    "LegacyCrhScorer",
    "LegacyFillInput",
    "LegacyLabelResult",
    "scorer_may_refuse",
]

LEGACY_SCORER_ID: Final = "legacy_crh/v1"
_LEGACY_KINDS: Final = frozenset({"current_rung_hold", "continuous_rung_hold"})
_NO_FILL_KINDS: Final = frozenset({"forecast_ladder"})


def scorer_may_refuse(kind: str, *, unlabelled_fills: int) -> bool:
    """Whether ``kind``'s scorer may refuse now.

    FQ has a real scorer and never refuses. A retired CRH kind, and ``forecast_ladder`` (which has
    no fills), may refuse only when no attributed fill of the kind still lacks a final C2 row.
    """
    if kind in _LEGACY_KINDS or kind in _NO_FILL_KINDS:
        return unlabelled_fills == 0
    return False


@dataclass(frozen=True)
class LegacyFillInput:
    """One durable CRH fill, the label-file key of its family, its latch trial id, and its frozen
    ``ScoredTrial`` (``None`` until the legacy scorer has scored it)."""

    fill: DurableFillRecord
    label_family: str
    trial_id: str
    scored: ScoredTrial | None


@dataclass(frozen=True)
class LegacyLabelResult:
    rows: tuple[LabelRow, ...]
    legacy_sell_rows: int


class LegacyCrhScorer:
    legs: ClassVar[frozenset[str]] = frozenset({"yes", "no"})
    roles: ClassVar[frozenset[str]] = frozenset({"entry", "exit"})

    def __init__(self, *, now_ns: int, prior: Sequence[LabelRow] = ()) -> None:
        self._now_ns = now_ns
        self._prior = tuple(prior)

    def label(
        self, capture_day: Any, exec_fills: Sequence[LegacyFillInput], settlements: Any
    ) -> tuple[LabelRow, ...]:
        return self.label_with_counts(capture_day, exec_fills, settlements).rows

    def label_with_counts(
        self, capture_day: Any, exec_fills: Sequence[LegacyFillInput], settlements: Any
    ) -> LegacyLabelResult:
        """``capture_day`` and ``settlements`` are the C6 signature only: the legacy settlement
        truth is the frozen ``ScoredTrial`` already joined to each fill."""
        rows = [self._row(inp) for inp in exec_fills]
        sells = sum(1 for row in rows if row.role is LabelRole.EXIT)
        return LegacyLabelResult(rows=apply_prior(rows, self._prior), legacy_sell_rows=sells)

    def _row(self, inp: LegacyFillInput) -> LabelRow:
        fill = inp.fill
        facts = bucket_facts_from_instrument_id(fill.instrument_id)
        if facts is None:
            raise ValueError("a fill's instrument id is not a weather rung")
        if fill.cumulative_qty <= 0:
            raise ValueError("a durable fill must have a positive quantity")
        role = LabelRole.ENTRY if fill.order_side == "BUY" else LabelRole.EXIT
        scored = inp.scored if role is LabelRole.ENTRY else None
        fee_ok = fill.fee_reconciled
        qty = fill.cumulative_qty
        return LabelRow(
            label_id=label_id_of(inp.label_family, fill.client_order_id, fill.trade_id, role),
            decision_id=None,
            family_id=inp.label_family,
            trial_id=inp.trial_id,
            client_order_id=fill.client_order_id,
            trade_id=fill.trade_id,
            station=facts.settlement_station,
            climate_day=facts.climate_day.isoformat(),
            instrument_id=fill.instrument_id,
            rung_id=fq_rung_id(facts.lower_f, facts.upper_f) or f"gte_{facts.lower_f}",
            leg=leg_of_symbol(symbol_of_instrument_id(fill.instrument_id)),
            role=role,
            qty=qty,
            fill_px=fill.cumulative_cost / qty,
            entry_ask=None,
            fee_reconciled=fill.cumulative_fee if fee_ok else None,
            slippage=None,
            p_at_decision=None,
            p_raw_at_decision=None,
            p_source=PSource.NONE,
            settled_outcome=None if scored is None else scored.held,
            settlement_tmax_f=None if scored is None else Decimal(scored.settlement_tmax_f),
            settlement_basis=None if scored is None else scored.settlement_basis,
            realized_pnl=None if scored is None else scored.pnl * qty,
            counterfactual_hold_pnl=None,
            reconciled=False,
            reconciliation_delta=None,
            reconciliation_source="node_belief",
            net_position_key=base_symbol_of(symbol_of_instrument_id(fill.instrument_id)),
            admissible=False,
            excluded_reason=ExcludedReason.UNATTRIBUTED,
            labelled_at_ns=self._now_ns,
            label_seq=0,
            scorer_id=LEGACY_SCORER_ID,
        )
