"""The label run's core (AUT-2 r7 WP6, sections 3.5, 3.7.3 and 3.12).

``run_labels`` reads the durable fills, runs EVERY registered C6 plug-in (the registry, not a family
list, is the iteration set), writes the C2 rows, checks the completeness identity, writes the
verdicts and the unresolved journal, and writes the run marker LAST. Delivery of the CRITICALs goes
through the injected ``deliver`` seam (``deliver_critical``: deduped per episode and UTC day).

Exit codes: 0 (a run completed, including FAILED_IDENTITY: it is a detected data condition that was
alerted), 1 (an input could not be read or a plug-in refused/failed: no marker), 4 (a CRITICAL could
not be delivered, after every durable write). Nothing here reads a venue or opens the canary store.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from breezy.adapters.polymarket_us.exec.client import DurableFillRecord
from breezy.analysis.labeling.attribution import UnresolvedRow, write_unresolved_journal
from breezy.analysis.labeling.completeness import (
    Coverage,
    coverage_partition,
    identity_breaches,
    is_final_row,
    run_outcome,
)
from breezy.analysis.labeling.delivery import Deliver, DeliveryStatus, deliver_critical
from breezy.analysis.labeling.fill_source import FillRead, read_durable_fills
from breezy.analysis.labeling.legacy_crh_scorer import LEGACY_SCORER_ID, scorer_may_refuse
from breezy.analysis.labeling.scoring_batch import ScoredBatch, ScoringBatch
from breezy.analysis.labeling.skip_journal import utc_day
from breezy.analysis.labeling.verdicts import (
    LagFill,
    PolicyBlock,
    ReconFacts,
    ReconMode,
    build_label_lag_verdict,
    build_reconciliation_verdict,
)
from breezy.persistence.autonomy.label_schema import LabelRole
from breezy.persistence.autonomy.label_store import (
    LabelRow,
    LabelStoreError,
    MarkerCorrupt,
    RunMarker,
    RunOutcome,
    read_labels,
    read_newest_marker,
    write_labels,
    write_marker,
)
from breezy.persistence.autonomy.paths import AutonomyPaths
from breezy.persistence.autonomy.single_read import SingleReadRefused
from breezy.persistence.autonomy.verdict import Verdict, VerdictOutcome, write_verdict

__all__ = [
    "AlertBatch",
    "FamilyInfo",
    "InputPlan",
    "LabelRunDeps",
    "LegOutcomes",
    "RunResult",
    "inconclusive_legs",
    "run_labels",
]

_NS_PER_DAY: Final = 86_400_000_000_000
_RC_FAILED: Final = 1
_RC_DELIVERY: Final = 4


@dataclass(frozen=True)
class FamilyInfo:
    family_id: str
    kind: str
    retired: bool


@dataclass(frozen=True)
class InputPlan:
    """What the planner made of the durable fills: per-kind scorer inputs, the kind of every fill
    (by ``client_order_id``), and the fills it could not identify (journalled, never labelled)."""

    inputs_by_kind: Mapping[str, Sequence[Any]]
    fill_kinds: Mapping[str, str]
    unresolved: tuple[UnresolvedRow, ...] = ()
    unresolved_fill_keys: frozenset[str] = frozenset()


@dataclass(frozen=True)
class LegOutcomes:
    position: VerdictOutcome
    settlement: VerdictOutcome
    cash: VerdictOutcome


def inconclusive_legs(family: FamilyInfo) -> LegOutcomes:
    """The default leg reading: the reconciliation legs are produced from the venue snapshot
    journals (WP9) and the cash records, so until they are wired the daily verdict says it could
    not decide, never PASS."""
    inconclusive = VerdictOutcome.INCONCLUSIVE
    return LegOutcomes(inconclusive, inconclusive, inconclusive)


Planner = Callable[[Sequence[DurableFillRecord]], InputPlan]


@dataclass(frozen=True)
class LabelRunDeps:
    data_root: Path
    exec_db: Path
    now_ns: int
    venue: str
    registry: Mapping[str, Any]
    families: Callable[[], Sequence[FamilyInfo]]
    plan: Planner
    settlements: Any
    deliver: Deliver
    deadline_ns: Callable[[LabelRow], int]
    lag_start_ns: Callable[[DurableFillRecord], int]
    producer_code_sha: str
    subject_artefact_sha256: str | None
    legs: Callable[[FamilyInfo], LegOutcomes] = inconclusive_legs
    policy: PolicyBlock | None = None
    dry_run_root: Path | None = None
    legacy_scorer_ids: frozenset[str] = frozenset({LEGACY_SCORER_ID})


@dataclass(frozen=True)
class RunResult:
    exit_code: int
    run_outcome: RunOutcome | None = None
    coverage: Coverage | None = None
    lines: tuple[str, ...] = ()
    marker_path: Path | None = None


@dataclass
class AlertBatch:
    """The CRITICALs raised this run, delivered once every durable write is done."""

    deps: LabelRunDeps
    pending: list[tuple[str, str]] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    failed: bool = False

    def raise_critical(self, event: str, subject: str) -> None:
        self.pending.append((event, subject))

    def deliver_all(self) -> None:
        episode = (self.deps.now_ns // _NS_PER_DAY) * _NS_PER_DAY
        for event, subject in self.pending:
            outcome = deliver_critical(
                self.deps.data_root,
                event=event,
                venue=self.deps.venue,
                subject=subject,
                episode=episode,
                payload={"event": event, "severity": "CRITICAL", "subject": subject},
                deliver=self.deps.deliver,
                now_ns=self.deps.now_ns,
                dry_run_root=self.deps.dry_run_root,
            )
            if outcome.line is not None:
                self.lines.append(outcome.line)
            if outcome.status in (DeliveryStatus.FAILED, DeliveryStatus.DEFERRED):
                self.failed = True
                if not any(f"DELIVERY_FAILED event={event}" in ln for ln in self.lines):
                    self.lines.append(f"AUT2 DELIVERY_FAILED event={event}")


def _failed_run(alerts: AlertBatch, line: str, event: str, subject: str) -> RunResult:
    alerts.lines.append(line)
    alerts.raise_critical(event, subject)
    alerts.deliver_all()
    return RunResult(exit_code=_RC_FAILED, lines=tuple(alerts.lines))


def _final_client_orders(rows: Sequence[LabelRow], deps: LabelRunDeps) -> set[str]:
    return {
        row.client_order_id
        for row in rows
        if row.role is LabelRole.ENTRY
        and is_final_row(row, now_ns=deps.now_ns, deadline_ns=deps.deadline_ns(row))
    }


def _refusal(
    deps: LabelRunDeps, plan: InputPlan, prior: Sequence[LabelRow]
) -> tuple[str, str] | None:
    """The first family whose plug-in refuses while it must not: ``(family_id, reason)``."""
    final = _final_client_orders(prior, deps)
    for family in deps.families():
        plugin = deps.registry.get(family.kind)
        if plugin is None:
            return family.family_id, "no_plugin"
        # a plug-in with a real scorer (``has_scorer``) never refuses the label run, even though it
        # stays ``refusing`` for every other member (FQ-R41); a bare RefusingPlugin may refuse only
        # for a retired kind with nothing left to label
        if not getattr(plugin, "refusing", False) or getattr(plugin, "has_scorer", False):
            continue
        unlabelled = sum(
            1 for coid, kind in plan.fill_kinds.items() if kind == family.kind and coid not in final
        )
        if not family.retired or not scorer_may_refuse(family.kind, unlabelled_fills=unlabelled):
            return family.family_id, "refusing"
    return None


def _score(
    deps: LabelRunDeps, plan: InputPlan, prior: tuple[LabelRow, ...]
) -> list[tuple[str, ScoredBatch]]:
    capture_day = dt.date.fromisoformat(utc_day(deps.now_ns))
    scored: list[tuple[str, ScoredBatch]] = []
    for kind, plugin in deps.registry.items():
        if getattr(plugin, "refusing", False) and not getattr(plugin, "has_scorer", False):
            continue
        batch = ScoringBatch(deps.now_ns, prior, tuple(plan.inputs_by_kind.get(kind, ())))
        scored.append((kind, plugin.label(capture_day, batch, deps.settlements)))
    return scored


def _write_rows(deps: LabelRunDeps, rows: Sequence[LabelRow]) -> None:
    by_family: dict[str, list[LabelRow]] = {}
    for row in rows:
        by_family.setdefault(row.family_id, []).append(row)
    for family, family_rows in sorted(by_family.items()):
        write_labels(deps.data_root, family, family_rows, now_ns=deps.now_ns)


def _verdicts(
    deps: LabelRunDeps,
    fills: Sequence[DurableFillRecord],
    plan: InputPlan,
    coverage: Coverage,
    breaches: tuple[str, ...],
    labels: Sequence[LabelRow],
    prev: int | None,
    counts: tuple[int, int],
    alerts: AlertBatch,
) -> None:
    paths = AutonomyPaths(deps.data_root)
    final_ns = {
        r.client_order_id: r.labelled_at_ns
        for r in labels
        if r.role is LabelRole.ENTRY
        and is_final_row(r, now_ns=deps.now_ns, deadline_ns=deps.deadline_ns(r))
    }
    for family in sorted(
        {f.family_id: f for f in deps.families() if not f.retired}.values(),
        key=lambda f: f.family_id,
    ):
        legs = deps.legs(family)
        facts = ReconFacts(
            family_id=family.family_id,
            mode=ReconMode.DAILY,
            produced_at_ns=deps.now_ns,
            producer_code_sha=deps.producer_code_sha,
            subject_artefact_sha256=deps.subject_artefact_sha256,
            position=legs.position,
            settlement=legs.settlement,
            cash=legs.cash,
            coverage=coverage,
            breaches=breaches,
            n=len(fills),
            metrics={
                "durable_fill_count_prev": prev,
                "p_null_count": counts[0],
                "non_c1_post_epoch_count": counts[1],
            },
            policy=deps.policy,
        )
        write_verdict(paths, build_reconciliation_verdict(facts))
        mine = [f for f in fills if plan.fill_kinds.get(f.client_order_id) == family.kind]
        if not mine:
            continue
        lag_fills = [
            LagFill(f.client_order_id, deps.lag_start_ns(f), final_ns.get(f.client_order_id))
            for f in mine
        ]
        lag: Verdict = build_label_lag_verdict(
            family_id=family.family_id,
            mode=ReconMode.DAILY,
            produced_at_ns=deps.now_ns,
            now_ns=deps.now_ns,
            fills=lag_fills,
            producer_code_sha=deps.producer_code_sha,
            subject_artefact_sha256=deps.subject_artefact_sha256,
            policy=deps.policy,
        )
        write_verdict(paths, lag)
        if lag.outcome is VerdictOutcome.FAIL:
            alerts.raise_critical("aut2.label_lag", family.family_id)


def run_labels(deps: LabelRunDeps) -> RunResult:
    alerts = AlertBatch(deps)
    try:
        read: FillRead = read_durable_fills(deps.exec_db)
    except (OSError, sqlite3.Error):
        return _failed_run(
            alerts,
            "AUT2 INPUT_UNREADABLE input=exec_store",
            "aut2.label_input_unreadable",
            "exec_store",
        )
    try:
        prior_marker = read_newest_marker(deps.data_root)
    except (MarkerCorrupt, SingleReadRefused, OSError):
        return _failed_run(
            alerts, "AUT2 INPUT_UNREADABLE input=marker", "aut2.label_input_unreadable", "marker"
        )
    try:
        prior = read_labels(deps.data_root)
    except (LabelStoreError, SingleReadRefused, OSError):
        return _failed_run(
            alerts,
            "AUT2 INPUT_UNREADABLE input=label_store",
            "aut2.label_input_unreadable",
            "label_store",
        )
    fills = read.fills
    try:
        plan = deps.plan(fills)
    except Exception as exc:  # noqa: BLE001 - an unreadable epoch/C1/manifest input is one refusal
        return _failed_run(
            alerts,
            f"AUT2 INPUT_UNREADABLE input=plan cause={type(exc).__name__}",
            "aut2.label_input_unreadable",
            "plan",
        )
    refused = _refusal(deps, plan, prior)
    if refused is not None:
        return _failed_run(
            alerts,
            f"AUT2 SCORER_REFUSED family={refused[0]} reason={refused[1]}",
            "aut2.refusing_scorer",
            refused[0],
        )
    try:
        scored = _score(deps, plan, prior)
    except Exception as exc:  # noqa: BLE001 - a scorer failure (identity break) writes nothing
        return _failed_run(
            alerts,
            f"AUT2 SCORER_FAILED cause={type(exc).__name__}",
            "aut2.scorer_failed",
            "label_run",
        )
    new_rows = tuple(row for _, batch in scored for row in batch.rows)
    counts = (
        sum(b.p_null_count for _, b in scored),
        sum(b.non_c1_post_epoch_count for _, b in scored),
    )
    try:
        _write_rows(deps, new_rows)
        stored = read_labels(deps.data_root)
    except (LabelStoreError, SingleReadRefused, OSError):
        return _failed_run(
            alerts,
            "AUT2 INPUT_UNREADABLE input=label_write",
            "aut2.label_input_unreadable",
            "label_write",
        )
    prev = None if prior_marker is None else prior_marker.durable_fill_count
    coverage = coverage_partition(
        fills,
        stored,
        now_ns=deps.now_ns,
        deadline_ns=deps.deadline_ns,
        unresolved_fill_keys=plan.unresolved_fill_keys,
        n_undecodable=read.n_undecodable,
        legacy_scorer_ids=deps.legacy_scorer_ids,
    )
    breaches = identity_breaches(coverage, durable_fill_count_prev=prev)
    outcome = run_outcome(coverage, rows_written=len(new_rows), durable_fill_count_prev=prev)
    day = utc_day(deps.now_ns)
    try:
        if plan.unresolved:
            write_unresolved_journal(deps.data_root, plan.unresolved, now_ns=deps.now_ns, day=day)
        _verdicts(deps, fills, plan, coverage, breaches, stored, prev, counts, alerts)
        marker = RunMarker(
            run_outcome=outcome,
            durable_fill_count=coverage.durable_fill_count,
            durable_fill_count_prev=prev,
            labelled_final=coverage.c2_final,
            unattributed_pre_epoch=coverage.unattributed_pre_epoch,
            legacy_labelled=coverage.legacy_labelled,
            open=coverage.open,
            pending=coverage.pending,
            unresolved=coverage.unresolved,
            missing_label=coverage.missing_label,
            p_null_count=counts[0],
            non_c1_post_epoch_count=counts[1],
        )
        marker_path = write_marker(deps.data_root, marker, day=day, now_ns=deps.now_ns)
    except (OSError, SingleReadRefused, LabelStoreError, ValueError) as exc:
        return _failed_run(
            alerts,
            f"AUT2 INPUT_UNREADABLE input=journal cause={type(exc).__name__}",
            "aut2.label_input_unreadable",
            "journal",
        )
    for breach in breaches:
        alerts.raise_critical("aut2.identity_breach", breach)
    for row in plan.unresolved:
        alerts.raise_critical("aut2.unresolved_fill", row.fill_key_sha)
    alerts.deliver_all()
    summary = (
        f"LABEL_OUTCOMES run_outcome={outcome.value} "
        f"durable_fill_count={coverage.durable_fill_count} "
        f"labelled_final={coverage.c2_final} pending={coverage.pending} "
        f"unresolved={coverage.unresolved} missing_label={coverage.missing_label}"
    )
    return RunResult(
        exit_code=_RC_DELIVERY if alerts.failed else 0,
        run_outcome=outcome,
        coverage=coverage,
        lines=(*alerts.lines, summary),
        marker_path=marker_path,
    )
