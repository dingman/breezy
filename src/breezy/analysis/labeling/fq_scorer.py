"""The FQ ``Scorer``: durable fills to C2 ``label/v1`` rows (AUT-2 r7 WP3, sections 3.3 and 3.5).

The settlement oracle is ``score_trial`` (reused unchanged); this module maps its outcome to C2 and
never evaluates a settlement condition of its own, including the 7-day venue fallback trigger. A row
is a pure function of the durable fill, its attribution, the settlement record and ``now_ns``:

* ``realized_pnl = qty * payoff - cumulative_cost - fee_reconciled``, and for ``qty == 1`` it must
  equal ``ScoredTrial.pnl * qty`` exactly (:class:`ScorerIdentityError` otherwise, never smoothed).
* ``excluded_reason`` precedence: canary, then drill / voided pair (C1) or unattributed (pre-epoch),
  then ``q != 1``, ``fee_unreconciled``, ``slippage_defect``; a row with none is
  ``window_incomplete`` until every attributed fill of its ``(family, climate_day)`` is final.
* A row is re-labelled at ``label_seq + 1`` only when its content changed since the prior run.

An exit (SELL) row carries the settlement facts only; its P&L is WP4's.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any, ClassVar, Final

from breezy.adapters.polymarket_us.exec.client import DurableFillRecord
from breezy.analysis.labeling.attribution import (
    Attribution,
    PreEpochAttribution,
    fq_rung_id,
    fq_trial_id,
    label_family_of,
)
from breezy.analysis.labeling.constants import LABEL_LAG_MAX_H, WINDOW_INCOMPLETE_MAX_H
from breezy.analysis.labeling.decision_link import BridgeMatch, BridgeUnmatched
from breezy.analysis.labeling.instrument_facts import bucket_facts_from_instrument_id
from breezy.analysis.labeling.probability import LegMismatch, bought_leg_probabilities
from breezy.analysis.labeling.settlement_source import SettlementSource
from breezy.domain.instrument_leg import base_symbol_of, leg_of_symbol, symbol_of_instrument_id
from breezy.domain.weather_bucket_facts import WeatherBucketFacts
from breezy.persistence.autonomy.label_schema import ExcludedReason, LabelRole, PSource
from breezy.persistence.autonomy.label_store import LabelRow, UnmappedScorerReason
from breezy.settlement.trial_scorer import FilledTrial, ScoredTrial, ScoreRefusal, score_trial

__all__ = [
    "FQ_SCORER_ID",
    "ForecastQuantileLadderScorer",
    "FqFillInput",
    "LabelAlert",
    "LabelResult",
    "LagBreach",
    "Reconciliation",
    "ScorerIdentityError",
    "apply_prior",
    "label_id_of",
]

FQ_SCORER_ID: Final = "forecast_quantile_ladder/v1"
_NS_PER_H: Final = 3_600_000_000_000
_PENDING_REASONS: Final = frozenset(
    {"no_record", "preliminary_only", "superseded", "sentinel_tmax"}
)
_FALLBACK_BASIS: Final = "venue_last_fair_price_fallback"
_FALLBACK_REASON: Final = "venue_settled_without_nws"
#: Reasons that end a fill's label life on their own (``fee_unreconciled`` only past its horizon).
_SELF_FINAL: Final = frozenset(
    {
        ExcludedReason.DUPLICATE_FILL,
        ExcludedReason.QTY_NOT_ONE,
        ExcludedReason.CANARY,
        ExcludedReason.DRILL,
        ExcludedReason.VOIDED_PAIR,
        ExcludedReason.SLIPPAGE_DEFECT,
        ExcludedReason.UNATTRIBUTED,
    }
)


class ScorerIdentityError(Exception):
    """``realized_pnl`` differs from ``ScoredTrial.pnl * qty`` for a q = 1 settled entry."""


@dataclass(frozen=True)
class Reconciliation:
    """The governing reconciliation comparison for a fill (WP5 supplies it; the default is the
    node's own belief, which never makes a row reconciled)."""

    reconciled: bool = False
    delta: Decimal | None = None
    source: str = "node_belief"


@dataclass(frozen=True)
class FqFillInput:
    fill: DurableFillRecord
    attribution: Attribution | PreEpochAttribution
    scheduled_release_at_ns: int
    venue_settlement_tmax_f: int | None = None
    canary: bool = False
    reconciliation: Reconciliation = Reconciliation()
    bridge: BridgeMatch | BridgeUnmatched | None = None


@dataclass(frozen=True)
class LabelAlert:
    severity: str
    code: str
    client_order_id: str


@dataclass(frozen=True)
class LagBreach:
    client_order_id: str
    cause: str


@dataclass(frozen=True)
class LabelResult:
    rows: tuple[LabelRow, ...]
    alerts: tuple[LabelAlert, ...]
    lag_breaches: tuple[LagBreach, ...]
    p_null_count: int
    non_c1_post_epoch_count: int


def label_id_of(family_id: str, client_order_id: str, trade_id: str | None, role: LabelRole) -> str:
    """First 32 hex characters of ``sha256("label/v1"|family|client_order_id|trade_id|role)``."""
    material = "|".join(("label/v1", family_id, client_order_id, trade_id or "", role.value))
    return hashlib.sha256(material.encode()).hexdigest()[:32]


def apply_prior(rows: Sequence[LabelRow], prior: Sequence[LabelRow]) -> tuple[LabelRow, ...]:
    """Stamp ``label_seq`` against the prior run; drop rows whose content did not change."""
    latest: dict[str, LabelRow] = {}
    for row in prior:
        held = latest.get(row.label_id)
        if held is None or row.label_seq > held.label_seq:
            latest[row.label_id] = row
    out: list[LabelRow] = []
    for row in rows:
        before = latest.get(row.label_id)
        if before is None:
            out.append(row)
            continue
        unchanged = replace(row, labelled_at_ns=before.labelled_at_ns, label_seq=before.label_seq)
        if unchanged == before:
            continue
        out.append(replace(row, label_seq=before.label_seq + 1))
    return tuple(out)


@dataclass(frozen=True)
class _Scored:
    """The mapped ``score_trial`` outcome: ``scored`` is None while the settlement is pending."""

    scored: ScoredTrial | None


@dataclass(frozen=True)
class _Draft:
    row: LabelRow
    release_ns: int
    done: bool
    group: tuple[str, str]
    alerts: tuple[LabelAlert, ...]


def _map_outcome(result: ScoredTrial | ScoreRefusal) -> _Scored:
    if isinstance(result, ScoreRefusal):
        if result.reason in _PENDING_REASONS:
            return _Scored(None)
        raise UnmappedScorerReason(f"score_trial refused for an unmapped reason: {result.reason}")
    if result.settlement_basis == "nws_final" and result.excluded_reason is None:
        return _Scored(result)
    if result.settlement_basis == _FALLBACK_BASIS and result.excluded_reason == _FALLBACK_REASON:
        return _Scored(result)
    raise UnmappedScorerReason(
        f"score_trial returned an unmapped basis/reason: "
        f"{result.settlement_basis}/{result.excluded_reason}"
    )


def _rung_id(attribution: Attribution | PreEpochAttribution, facts: WeatherBucketFacts) -> str:
    if isinstance(attribution, Attribution):
        return attribution.decision.rung_id
    rung = fq_rung_id(facts.lower_f, facts.upper_f)
    return rung if rung is not None else f"gte_{facts.lower_f}"


class ForecastQuantileLadderScorer:
    """C6 ``Scorer`` for ``forecast_quantile_ladder`` (both legs, both roles)."""

    legs: ClassVar[frozenset[str]] = frozenset({"yes", "no"})
    roles: ClassVar[frozenset[str]] = frozenset({"entry", "exit"})

    def __init__(self, *, now_ns: int, prior: Sequence[LabelRow] = ()) -> None:
        self._now_ns = now_ns
        self._prior = tuple(prior)

    def label(
        self, capture_day: Any, exec_fills: Sequence[FqFillInput], settlements: SettlementSource
    ) -> tuple[LabelRow, ...]:
        return self.label_with_alerts(capture_day, exec_fills, settlements).rows

    def label_with_alerts(
        self, capture_day: Any, exec_fills: Sequence[FqFillInput], settlements: SettlementSource
    ) -> LabelResult:
        """Label every fill. ``capture_day`` is the run's capture day, kept for the C6 signature."""
        drafts = [self._draft(inp, settlements) for inp in exec_fills]
        group_done: dict[tuple[str, str], bool] = {}
        for draft in drafts:
            if draft.row.role is LabelRole.ENTRY:
                group_done[draft.group] = group_done.get(draft.group, True) and draft.done
        rows = [self._finish(draft, group_done) for draft in drafts]
        entries = [r for r in rows if r.role is LabelRole.ENTRY]
        return LabelResult(
            rows=apply_prior(rows, self._prior),
            alerts=tuple(a for d in drafts for a in d.alerts),
            lag_breaches=self._lag_breaches(rows, drafts),
            p_null_count=sum(1 for r in entries if r.p_source is PSource.NONE),
            non_c1_post_epoch_count=sum(
                1
                for r in entries
                if r.p_source is not PSource.C1_DECISION and r.decision_id is not None
            ),
        )

    def _finish(self, draft: _Draft, group_done: Mapping[tuple[str, str], bool]) -> LabelRow:
        row = draft.row
        if row.role is LabelRole.EXIT:
            if row.settled_outcome is None:
                return replace(row, excluded_reason=ExcludedReason.WINDOW_INCOMPLETE)
            return row
        if row.excluded_reason is None and not (
            row.settled_outcome is not None and group_done[draft.group]
        ):
            return replace(row, excluded_reason=ExcludedReason.WINDOW_INCOMPLETE)
        admissible = (
            row.reconciled
            and row.excluded_reason is None
            and row.p_source is PSource.C1_DECISION
            and row.settlement_basis == "nws_final"
        )
        return replace(row, admissible=admissible)

    def _lag_breaches(
        self, rows: Sequence[LabelRow], drafts: Sequence[_Draft]
    ) -> tuple[LagBreach, ...]:
        limit = WINDOW_INCOMPLETE_MAX_H * _NS_PER_H
        return tuple(
            LagBreach(
                row.client_order_id,
                "awaiting_venue_fallback" if row.settled_outcome is None else "awaiting_window",
            )
            for row, draft in zip(rows, drafts, strict=True)
            if row.excluded_reason is ExcludedReason.WINDOW_INCOMPLETE
            and self._now_ns - draft.release_ns > limit
        )

    def _draft(self, inp: FqFillInput, settlements: SettlementSource) -> _Draft:
        fill = inp.fill
        facts = bucket_facts_from_instrument_id(fill.instrument_id)
        if facts is None:
            raise ValueError("a fill's instrument id is not a weather rung")
        if fill.cumulative_qty <= 0:
            raise ValueError("a durable fill must have a positive quantity")
        leg = leg_of_symbol(symbol_of_instrument_id(fill.instrument_id))
        role = LabelRole.ENTRY if fill.order_side == "BUY" else LabelRole.EXIT
        attribution = inp.attribution
        family = label_family_of(attribution)
        climate_day = facts.climate_day.isoformat()
        rung = _rung_id(attribution, facts)
        qty = fill.cumulative_qty
        fill_px = fill.cumulative_cost / qty
        entry_ask = (
            Decimal(attribution.decision.ask_px) if isinstance(attribution, Attribution) else None
        )
        alerts: list[LabelAlert] = []
        coid = fill.client_order_id

        p_at, p_raw, p_source, mismatch = self._probability(inp, leg, role)
        if mismatch:
            alerts.append(LabelAlert("CRITICAL", "side_leg_mismatch", coid))
        if isinstance(attribution, Attribution):
            alerts.extend(LabelAlert("CRITICAL", code, coid) for code in attribution.alerts)

        trial_id = fq_trial_id(facts.settlement_station, climate_day, rung, leg)
        scored = self._score(inp, facts, trial_id, fill_px, entry_ask, settlements)
        fee_ok = fill.fee_reconciled
        realized = self._realized(scored, fill, qty, fee_ok) if role is LabelRole.ENTRY else None
        slippage = None if entry_ask is None else fill_px - entry_ask

        reason = self._reason(inp, role, qty, fee_ok, fill_px, entry_ask, alerts)
        release = inp.scheduled_release_at_ns
        done = self._done(reason, scored, release)
        row = LabelRow(
            label_id=label_id_of(family, coid, fill.trade_id, role),
            decision_id=attribution.decision.decision_id
            if isinstance(attribution, Attribution)
            else None,
            family_id=family,
            trial_id=trial_id,
            client_order_id=coid,
            trade_id=fill.trade_id,
            station=facts.settlement_station,
            climate_day=climate_day,
            instrument_id=fill.instrument_id,
            rung_id=rung,
            leg=leg,
            role=role,
            qty=qty,
            fill_px=fill_px,
            entry_ask=entry_ask,
            fee_reconciled=fill.cumulative_fee if fee_ok else None,
            slippage=slippage,
            p_at_decision=p_at,
            p_raw_at_decision=p_raw,
            p_source=p_source,
            settled_outcome=None if scored is None else scored.held,
            settlement_tmax_f=None if scored is None else Decimal(scored.settlement_tmax_f),
            settlement_basis=None if scored is None else scored.settlement_basis,
            realized_pnl=realized,
            counterfactual_hold_pnl=None,
            reconciled=inp.reconciliation.reconciled and not mismatch,
            reconciliation_delta=inp.reconciliation.delta,
            reconciliation_source=inp.reconciliation.source,
            net_position_key=base_symbol_of(symbol_of_instrument_id(fill.instrument_id)),
            admissible=False,
            excluded_reason=reason,
            labelled_at_ns=self._now_ns,
            label_seq=0,
            scorer_id=FQ_SCORER_ID,
        )
        return _Draft(
            row=row,
            release_ns=release,
            done=done,
            group=(family, climate_day),
            alerts=tuple(alerts),
        )

    def _probability(
        self, inp: FqFillInput, leg: str, role: LabelRole
    ) -> tuple[float | None, float | None, PSource, bool]:
        if role is LabelRole.EXIT:
            return None, None, PSource.NONE, False
        attribution = inp.attribution
        if isinstance(attribution, Attribution):
            decision = attribution.decision
            found = bought_leg_probabilities(
                p_hat=decision.p_hat, p_hat_raw=decision.p_hat_raw, side=decision.side, leg=leg
            )
            if isinstance(found, LegMismatch):
                return None, None, PSource.NONE, True
            return found.p_at_decision, found.p_raw_at_decision, PSource.C1_DECISION, False
        if isinstance(inp.bridge, BridgeMatch):
            bridge = inp.bridge
            return (
                bridge.p_at_decision,
                bridge.p_raw_at_decision,
                PSource.ARTEFACT_RECOMPUTE,
                False,
            )
        return None, None, PSource.NONE, False

    def _score(
        self,
        inp: FqFillInput,
        facts: WeatherBucketFacts,
        trial_id: str,
        fill_px: Decimal,
        entry_ask: Decimal | None,
        settlements: SettlementSource,
    ) -> ScoredTrial | None:
        fill = inp.fill
        record = settlements.record(facts.settlement_station, facts.climate_day)
        trial = FilledTrial(
            trial_id=trial_id,
            station=facts.settlement_station,
            climate_day=facts.climate_day.isoformat(),
            instrument_id=fill.instrument_id,
            bucket=facts,
            fill_px=fill_px,
            fee=fill.cumulative_fee / fill.cumulative_qty,
            qty=fill.cumulative_qty,
            filled_at_ns=fill.ts_event,
            entry_ask=fill_px if entry_ask is None else entry_ask,
            scheduled_release_at_ns=inp.scheduled_release_at_ns,
            venue_settlement_tmax_f=inp.venue_settlement_tmax_f,
        )
        return _map_outcome(score_trial(trial, record, now_ns=self._now_ns)).scored

    @staticmethod
    def _realized(
        scored: ScoredTrial | None, fill: DurableFillRecord, qty: Decimal, fee_ok: bool
    ) -> Decimal | None:
        if scored is None or not fee_ok:
            return None
        payoff = Decimal(1) if scored.held else Decimal(0)
        realized = qty * payoff - fill.cumulative_cost - fill.cumulative_fee
        if qty == 1 and realized != scored.pnl * qty:
            raise ScorerIdentityError("realized_pnl differs from ScoredTrial.pnl x qty")
        return realized

    def _reason(
        self,
        inp: FqFillInput,
        role: LabelRole,
        qty: Decimal,
        fee_ok: bool,
        fill_px: Decimal,
        entry_ask: Decimal | None,
        alerts: list[LabelAlert],
    ) -> ExcludedReason | None:
        coid = inp.fill.client_order_id
        if role is LabelRole.EXIT:
            return None
        if not fee_ok:
            overdue = self._now_ns >= inp.scheduled_release_at_ns + LABEL_LAG_MAX_H * _NS_PER_H
            alerts.append(LabelAlert("CRITICAL" if overdue else "WARN", "fee_unreconciled", coid))
        defect = entry_ask is not None and fill_px < entry_ask
        if defect:
            alerts.append(LabelAlert("WARN", "slippage_defect", coid))
        attribution = inp.attribution
        if inp.canary:
            return ExcludedReason.CANARY
        if isinstance(attribution, PreEpochAttribution):
            return attribution.excluded_reason
        if attribution.excluded_reason is not None:
            return attribution.excluded_reason
        if qty != 1:
            return ExcludedReason.QTY_NOT_ONE
        if not fee_ok:
            return ExcludedReason.FEE_UNRECONCILED
        return ExcludedReason.SLIPPAGE_DEFECT if defect else None

    def _done(
        self, reason: ExcludedReason | None, scored: ScoredTrial | None, release_ns: int
    ) -> bool:
        if reason in _SELF_FINAL:
            return True
        if reason is ExcludedReason.FEE_UNRECONCILED:
            return self._now_ns >= release_ns + LABEL_LAG_MAX_H * _NS_PER_H
        return scored is not None
