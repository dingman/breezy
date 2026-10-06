"""C4 verdict builders for the AUT-2 producers (AUT-2 r7 WP5, section 3.7).

``build_reconciliation_verdict`` makes the RECONCILIATION verdict (detector
``aut2.reconciliation``) and ``build_label_lag_verdict`` the HEALTH verdict
(``aut2.label_lag``). Both are pure: the caller supplies the legs, the coverage, the producer
code sha (from ``pins.PRODUCER_SOURCE_SHA256``) and the policy block.
``declared_action_class`` and ``policy_ruling_sha256`` come only from the policy block; without
one the verdict carries ``no_policy_ruling`` and the restrictive ``NONE`` class.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Final

from breezy.analysis.labeling.completeness import Coverage
from breezy.analysis.labeling.constants import (
    LABEL_LAG_MAX_H,
    RECON_DAILY_VALIDITY_H,
    RECON_INTRADAY_VALIDITY_H,
)
from breezy.persistence.autonomy.verdict import (
    ActionClass,
    Assumption,
    MetricValue,
    Verdict,
    VerdictInput,
    VerdictKind,
    VerdictOutcome,
)

__all__ = [
    "LABEL_LAG_DETECTOR",
    "RECONCILIATION_DETECTOR",
    "LagFill",
    "PolicyBlock",
    "ReconFacts",
    "ReconMode",
    "build_label_lag_verdict",
    "build_reconciliation_verdict",
    "lag_start_ns",
]

RECONCILIATION_DETECTOR: Final = "aut2.reconciliation"
LABEL_LAG_DETECTOR: Final = "aut2.label_lag"
_NS_PER_H: Final = 3_600_000_000_000
_N_MIN_REASON: Final = "deterministic_equality_check"

MetricInput = int | bool | str | Decimal | None


class ReconMode(StrEnum):
    DAILY = "daily"
    INTRADAY = "intraday"
    POST_STOP = "post_stop"


@dataclass(frozen=True)
class PolicyBlock:
    """The pinned ``autonomy-policy/v1`` block's ruling for this detector."""

    action_class: ActionClass
    ruling_sha256: str


@dataclass(frozen=True)
class ReconFacts:
    family_id: str
    mode: ReconMode
    produced_at_ns: int
    producer_code_sha: str
    subject_artefact_sha256: str | None
    position: VerdictOutcome
    settlement: VerdictOutcome
    cash: VerdictOutcome
    coverage: Coverage
    breaches: tuple[str, ...]
    n: int
    metrics: Mapping[str, MetricInput]
    policy: PolicyBlock | None = None
    inputs: tuple[VerdictInput, ...] = ()


def _metric(value: MetricInput) -> MetricValue:
    if isinstance(value, bool) or value is None or isinstance(value, str | Decimal):
        return value
    return Decimal(value)


def _metrics(raw: Mapping[str, MetricInput]) -> tuple[tuple[str, MetricValue], ...]:
    return tuple((name, _metric(raw[name])) for name in sorted(raw))


def _policy_fields(
    policy: PolicyBlock | None,
) -> tuple[ActionClass, str | None, tuple[Assumption, ...]]:
    if policy is None:
        return ActionClass.NONE, None, (Assumption.NO_POLICY_RULING,)
    return policy.action_class, policy.ruling_sha256, ()


def _validity_h(mode: ReconMode) -> int:
    return RECON_DAILY_VALIDITY_H if mode is ReconMode.DAILY else RECON_INTRADAY_VALIDITY_H


def _recon_outcome(facts: ReconFacts) -> VerdictOutcome:
    legs = (facts.position, facts.settlement, facts.cash)
    if facts.breaches or VerdictOutcome.FAIL in legs:
        return VerdictOutcome.FAIL
    if VerdictOutcome.INCONCLUSIVE in legs:
        return VerdictOutcome.INCONCLUSIVE
    return VerdictOutcome.PASS


def build_reconciliation_verdict(facts: ReconFacts) -> Verdict:
    """One RECONCILIATION verdict. ``unresolved`` and ``missing_label`` are FAILs, folded in here
    (RB-7); ``valid_until_ns`` is 26 h for the daily run and 8 h for intraday and post-STOP."""
    action, ruling, assumptions = _policy_fields(facts.policy)
    cov = facts.coverage
    metrics: dict[str, MetricInput] = {
        "durable_fill_count": cov.durable_fill_count,
        "labelled_final": cov.c2_final,
        "unattributed_pre_epoch": cov.unattributed_pre_epoch,
        "legacy_labelled": cov.legacy_labelled,
        "open": cov.open,
        "pending": cov.pending,
        "unresolved": cov.unresolved,
        "missing_label": cov.missing_label,
        "n_min_reason": _N_MIN_REASON,
        "mode": facts.mode.value,
        **facts.metrics,
    }
    return Verdict(
        kind=VerdictKind.RECONCILIATION,
        subject_family_id=facts.family_id,
        outcome=_recon_outcome(facts),
        detector=RECONCILIATION_DETECTOR,
        declared_action_class=action,
        produced_at_ns=facts.produced_at_ns,
        valid_until_ns=facts.produced_at_ns + _validity_h(facts.mode) * _NS_PER_H,
        producer_code_sha=facts.producer_code_sha,
        metrics=_metrics(metrics),
        inputs=tuple(sorted(facts.inputs, key=lambda i: (i.path_role, i.sha256))),
        assumptions=assumptions,
        subject_artefact_sha256=facts.subject_artefact_sha256,
        n=facts.n,
        policy_ruling_sha256=ruling,
    )


@dataclass(frozen=True)
class LagFill:
    """One live fill's label-lag clock. ``final_label_ns`` is None until a FINAL label exists; a
    ``window_incomplete`` row never stops the clock."""

    client_order_id: str
    lag_start_ns: int
    final_label_ns: int | None
    awaiting_venue_fallback: bool = False


def lag_start_ns(first_settlement_record_ts: int | None, settlement_deadline_ns: int) -> int:
    """``min(first SettlementRecord.ts_ns, settlement_deadline_ns)``: a missing record (an NWS
    outage) still starts the clock at the venue settlement instant."""
    if first_settlement_record_ts is None:
        return settlement_deadline_ns
    return min(first_settlement_record_ts, settlement_deadline_ns)


def _lagging(fill: LagFill, now_ns: int) -> bool:
    horizon = LABEL_LAG_MAX_H * _NS_PER_H
    end = fill.final_label_ns if fill.final_label_ns is not None else now_ns
    return end - fill.lag_start_ns > horizon


def build_label_lag_verdict(
    *,
    family_id: str,
    mode: ReconMode,
    produced_at_ns: int,
    now_ns: int,
    fills: Sequence[LagFill],
    producer_code_sha: str,
    subject_artefact_sha256: str | None,
    policy: PolicyBlock | None = None,
) -> Verdict:
    """HEALTH ``aut2.label_lag``: FAIL when any fill has gone more than 24 h from its lag start
    without a final label (or got one only after 24 h)."""
    action, ruling, assumptions = _policy_fields(policy)
    lagging = [f for f in fills if _lagging(f, now_ns)]
    metrics: dict[str, MetricInput] = {
        "fills_checked": len(fills),
        "fills_lagging": len(lagging),
        "awaiting_venue_fallback": sum(1 for f in lagging if f.awaiting_venue_fallback),
    }
    return Verdict(
        kind=VerdictKind.HEALTH,
        subject_family_id=family_id,
        outcome=VerdictOutcome.FAIL if lagging else VerdictOutcome.PASS,
        detector=LABEL_LAG_DETECTOR,
        declared_action_class=action,
        produced_at_ns=produced_at_ns,
        valid_until_ns=produced_at_ns + _validity_h(mode) * _NS_PER_H,
        producer_code_sha=producer_code_sha,
        metrics=_metrics(metrics),
        assumptions=assumptions,
        subject_artefact_sha256=subject_artefact_sha256,
        n=len(fills),
        policy_ruling_sha256=ruling,
    )
