"""The three reconciliation legs and the C2 cash records (AUT-2 r7 WP5, section 3.6).

* **Position leg.** The venue's net per base slug against ``net_signed_qty`` of the durable
  ledger, exact Decimal, the leg sign applied BEFORE the compare (a NO holding nets as short
  YES). The compared set is ledger slugs union venue-page slugs. A fill within
  ``POSITION_SETTLE_GRACE_S`` of the snapshot is not compared; a later fill is fenced out. The
  venue net comes only from a ``venue_get`` read.
* **Settlement leg.** The venue settles the base slug's YES outcome: it must equal ``held`` for
  a YES label and ``not held`` for a NO label. A disagreement unreconciles the label and never
  adopts the venue's value.
* **Cash leg.** ``cash_records`` emits ``ResidualSettlement``-shaped records (payout, exit
  proceeds, YES/NO netting offset) for the existing ``reconcile_daily`` to fold in.
  ``cash_leg_outcome`` maps its cumulative result to PASS, FAIL or INCONCLUSIVE.

Everything here is pure except the write-once position-compare journal.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Final

from breezy.adapters.polymarket_us.exec.client import DurableFillRecord
from breezy.analysis.labeling.constants import (
    INCONCLUSIVE_ALERT_DAYS,
    POSITION_SETTLE_GRACE_S,
    SNAPSHOT_MAX_AGE_MIN,
)
from breezy.analysis.labeling.fill_source import net_by_base_slug
from breezy.analysis.labeling.legacy_crh_scorer import LEGACY_SCORER_ID
from breezy.analysis.labeling.skip_journal import utc_day, write_json_once
from breezy.domain.instrument_leg import base_symbol_of, symbol_of_instrument_id
from breezy.persistence.autonomy.canonical import sha256_hex
from breezy.persistence.autonomy.label_schema import LabelRole
from breezy.persistence.autonomy.label_store import LabelRow
from breezy.persistence.autonomy.single_read import (
    ReadPolicy,
    SingleReadReason,
    SingleReadRefused,
    open_root,
    read_once_at,
    walk_dirs,
)
from breezy.persistence.autonomy.verdict import VerdictOutcome
from breezy.runtime.venue_positions_read import PositionRow, ReadStatus, VenuePositionsRead

__all__ = [
    "COMPARE_DIR",
    "CashRecord",
    "CashRecords",
    "CashSourceOverlap",
    "CompareResult",
    "DailyPositionLeg",
    "PositionLeg",
    "ReconAlert",
    "ReconSource",
    "SettlementEvidence",
    "SettlementLeg",
    "SlugCompare",
    "StoredSnapshot",
    "cash_leg_outcome",
    "cash_records",
    "daily_position_leg",
    "fills_never_position_compared",
    "governing_comparison",
    "position_leg_for_family",
    "read_position_compares",
    "reconcile_labels",
    "reconcile_positions",
    "reconcile_settlement",
    "snapshot_sha256",
    "streak_alert",
    "write_position_compare",
]

COMPARE_DIR: Final[tuple[str, ...]] = ("evidence", "aut2", "position_compare")
COMPARE_SCHEMA: Final = "aut2_position_compare/v1"
_NS_PER_S: Final = 1_000_000_000
_NS_PER_MIN: Final = 60 * _NS_PER_S
_MAX_COMPARE_BYTES: Final = 16 * 1024 * 1024
_ONE: Final = Decimal(1)

#: ``base_slug -> the venue settlement deadline of its climate day`` (None when unknown).
DeadlineNs = Callable[[str], int | None]


class CompareResult(StrEnum):
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    NOT_COMPARED_GRACE = "NOT_COMPARED_GRACE"
    NOT_COMPARED_INTENT = "NOT_COMPARED_INTENT"
    SETTLED_AWAY = "SETTLED_AWAY"


class ReconSource(StrEnum):
    VENUE_GET = "venue_get"
    NODE_BELIEF = "node_belief"


@dataclass(frozen=True)
class ReconAlert:
    severity: str
    code: str
    subject: str


@dataclass(frozen=True)
class SlugCompare:
    base_slug: str
    venue_net_qty: Decimal
    ledger_net_qty: Decimal
    result: CompareResult


@dataclass(frozen=True)
class PositionLeg:
    outcome: VerdictOutcome
    compares: tuple[SlugCompare, ...]
    venue_only_slugs: tuple[str, ...]
    inconclusive_causes: tuple[str, ...]
    alerts: tuple[ReconAlert, ...]

    @property
    def mismatches(self) -> tuple[str, ...]:
        return tuple(c.base_slug for c in self.compares if c.result is CompareResult.MISMATCH)

    @property
    def not_compared_grace(self) -> int:
        return sum(1 for c in self.compares if c.result is CompareResult.NOT_COMPARED_GRACE)

    @property
    def slugs_compared(self) -> int:
        return sum(
            1 for c in self.compares if c.result in (CompareResult.MATCH, CompareResult.MISMATCH)
        )


def _slug_of(fill: DurableFillRecord) -> str:
    return base_symbol_of(symbol_of_instrument_id(fill.instrument_id))


def _inconclusive(*causes: str, alerts: tuple[ReconAlert, ...] = ()) -> PositionLeg:
    return PositionLeg(VerdictOutcome.INCONCLUSIVE, (), (), tuple(causes), alerts)


def _venue_nets(rows: Iterable[PositionRow]) -> dict[str, Decimal] | None:
    nets: dict[str, Decimal] = {}
    for row in rows:
        if row.base_slug in nets:
            return None
        nets[row.base_slug] = row.net_qty
    return nets


def reconcile_positions(
    snapshot: VenuePositionsRead | None,
    fills: Sequence[DurableFillRecord],
    *,
    now_ns: int,
    deadline_ns: DeadlineNs,
    open_intent_slugs: Collection[str] = frozenset(),
    source: ReconSource = ReconSource.VENUE_GET,
) -> PositionLeg:
    """Compare the venue's net with the ledger's, per base slug, at one snapshot."""
    if source is not ReconSource.VENUE_GET:
        return _inconclusive("node_belief_only")
    if snapshot is None or snapshot.read_status is not ReadStatus.OK:
        status = "no_snapshot" if snapshot is None else snapshot.read_status.value.lower()
        return _inconclusive(status)
    if not snapshot.complete:
        return _inconclusive("incomplete_snapshot")
    if now_ns - snapshot.snapshot_ns > SNAPSHOT_MAX_AGE_MIN * _NS_PER_MIN:
        return _inconclusive("stale_snapshot", alerts=(ReconAlert("WARN", "stale_snapshot", ""),))
    venue = _venue_nets(snapshot.rows)
    if venue is None:
        return _inconclusive("duplicate_venue_slug")

    snap = snapshot.snapshot_ns
    grace_ns = POSITION_SETTLE_GRACE_S * _NS_PER_S
    seen = [f for f in fills if f.ts_event <= snap]  # later fills are fenced out
    by_slug: dict[str, list[DurableFillRecord]] = {}
    for fill in seen:
        by_slug.setdefault(_slug_of(fill), []).append(fill)

    compares: list[SlugCompare] = []
    venue_only: list[str] = []
    causes: list[str] = []
    alerts: list[ReconAlert] = []
    for slug in sorted(set(by_slug) | set(venue)):
        in_ledger = by_slug.get(slug, [])
        venue_net = venue.get(slug, Decimal(0))
        if not in_ledger:
            venue_only.append(slug)
            compares.append(SlugCompare(slug, venue_net, Decimal(0), CompareResult.MISMATCH))
            alerts.append(ReconAlert("CRITICAL", "venue_only_slug", slug))
            continue
        settled = [f for f in in_ledger if f.ts_event <= snap - grace_ns]
        ledger_net = next(iter(net_by_base_slug(settled).values()), Decimal(0))
        if any(f.ts_event > snap - grace_ns for f in in_ledger):
            result = CompareResult.NOT_COMPARED_GRACE
        elif slug in open_intent_slugs:
            result = CompareResult.NOT_COMPARED_INTENT
            causes.append("open_intent")
        elif slug not in venue and _is_settled_away(slug, snap, deadline_ns):
            result = CompareResult.SETTLED_AWAY
        else:
            result = CompareResult.MATCH if ledger_net == venue_net else CompareResult.MISMATCH
            if result is CompareResult.MISMATCH:
                alerts.append(ReconAlert("CRITICAL", "position_mismatch", slug))
        compares.append(SlugCompare(slug, venue_net, ledger_net, result))

    if any(c.result is CompareResult.MISMATCH for c in compares):
        outcome = VerdictOutcome.FAIL
    elif causes:
        outcome = VerdictOutcome.INCONCLUSIVE
    else:
        outcome = VerdictOutcome.PASS
    return PositionLeg(
        outcome, tuple(compares), tuple(venue_only), tuple(dict.fromkeys(causes)), tuple(alerts)
    )


def _is_settled_away(slug: str, snapshot_ns: int, deadline_ns: DeadlineNs) -> bool:
    deadline = deadline_ns(slug)
    return deadline is not None and snapshot_ns >= deadline


def position_leg_for_family(leg: PositionLeg, family_slugs: Collection[str]) -> VerdictOutcome:
    """A venue-only slug cannot be attributed to a family, so it fails every family's leg."""
    if leg.venue_only_slugs:
        return VerdictOutcome.FAIL
    own = [c for c in leg.compares if c.base_slug in family_slugs]
    if any(c.result is CompareResult.MISMATCH for c in own):
        return VerdictOutcome.FAIL
    return leg.outcome if leg.outcome is VerdictOutcome.INCONCLUSIVE else VerdictOutcome.PASS


# -- the write-once per-snapshot journal --------------------------------------------------------


@dataclass(frozen=True)
class StoredSnapshot:
    snapshot_ns: int
    mode: str
    rows: tuple[SlugCompare, ...]


def write_position_compare(
    data_root: Path,
    snapshot_ns: int,
    mode: str,
    compares: Sequence[SlugCompare],
    *,
    snapshot_sha256: str,
) -> Path:
    """One write-once file per snapshot: quantities and results only, no amounts or ids."""
    body = {
        "schema": COMPARE_SCHEMA,
        "snapshot_ns": snapshot_ns,
        "snapshot_sha256": snapshot_sha256,
        "mode": mode,
        "rows": [
            {
                "base_slug": c.base_slug,
                "venue_net_qty": str(c.venue_net_qty),
                "ledger_net_qty": str(c.ledger_net_qty),
                "result": c.result.value,
            }
            for c in compares
        ],
    }
    return write_json_once(
        data_root, (*COMPARE_DIR, utc_day(snapshot_ns), f"{snapshot_ns}_{mode}.json"), body
    )


def read_position_compares(data_root: Path) -> tuple[StoredSnapshot, ...]:
    """Every stored snapshot comparison, oldest first; an absent journal is empty."""
    rootfd = open_root(data_root)
    out: list[StoredSnapshot] = []
    try:
        try:
            root = walk_dirs(rootfd, COMPARE_DIR)
        except SingleReadRefused as exc:
            if exc.reason is SingleReadReason.NOT_FOUND:
                return ()
            raise
        try:
            days = sorted(os.listdir(root))
        finally:
            os.close(root)
        for day in days:
            dayfd = walk_dirs(rootfd, (*COMPARE_DIR, day))
            try:
                for name in sorted(os.listdir(dayfd)):
                    raw = read_once_at(
                        dayfd, name, max_bytes=_MAX_COMPARE_BYTES, policy=ReadPolicy.STRICT
                    )
                    out.append(_stored_of(json.loads(raw)))
            finally:
                os.close(dayfd)
    finally:
        os.close(rootfd)
    return tuple(sorted(out, key=lambda s: (s.snapshot_ns, s.mode)))


def _stored_of(body: Mapping[str, object]) -> StoredSnapshot:
    rows = body["rows"]
    assert isinstance(rows, list)
    return StoredSnapshot(
        snapshot_ns=int(str(body["snapshot_ns"])),
        mode=str(body["mode"]),
        rows=tuple(
            SlugCompare(
                str(r["base_slug"]),
                Decimal(str(r["venue_net_qty"])),
                Decimal(str(r["ledger_net_qty"])),
                CompareResult(str(r["result"])),
            )
            for r in rows
        ),
    )


def snapshot_sha256(rows: Sequence[PositionRow]) -> str:
    """A stable digest of the page the comparison was made from (slug, net, expired)."""
    return sha256_hex(json.dumps([[r.base_slug, str(r.net_qty), r.expired] for r in rows]).encode())


# -- the governing comparison, label reconciliation and coverage ---------------------------------


def governing_comparison(
    slug: str,
    snapshots: Sequence[StoredSnapshot],
    slug_fills: Sequence[DurableFillRecord],
    deadline_ns: DeadlineNs,
) -> tuple[int, SlugCompare] | None:
    """The newest journaled MATCH/MISMATCH with ``max(fill ts) + grace <= snapshot < deadline``."""
    if not slug_fills:
        return None
    floor = max(f.ts_event for f in slug_fills) + POSITION_SETTLE_GRACE_S * _NS_PER_S
    deadline = deadline_ns(slug)
    best: tuple[int, SlugCompare] | None = None
    for snap in snapshots:
        if snap.snapshot_ns < floor or (deadline is not None and snap.snapshot_ns >= deadline):
            continue
        for row in snap.rows:
            if row.base_slug != slug or row.result not in (
                CompareResult.MATCH,
                CompareResult.MISMATCH,
            ):
                continue
            if best is None or snap.snapshot_ns > best[0]:
                best = (snap.snapshot_ns, row)
    return best


def _fills_by_slug(fills: Iterable[DurableFillRecord]) -> dict[str, list[DurableFillRecord]]:
    grouped: dict[str, list[DurableFillRecord]] = {}
    for fill in fills:
        grouped.setdefault(_slug_of(fill), []).append(fill)
    return grouped


def reconcile_labels(
    rows: Sequence[LabelRow],
    snapshots: Sequence[StoredSnapshot],
    fills: Sequence[DurableFillRecord],
    deadline_ns: DeadlineNs,
) -> tuple[LabelRow, ...]:
    """Recompute every row's position component from its governing comparison (RB-4).

    No governing comparison means ``reconciled=False``, no delta and ``node_belief``. The caller
    stamps ``label_seq`` against the prior run (``apply_prior``).
    """
    by_slug = _fills_by_slug(fills)
    out: list[LabelRow] = []
    for row in rows:
        found = governing_comparison(
            row.net_position_key, snapshots, by_slug.get(row.net_position_key, []), deadline_ns
        )
        if found is None:
            out.append(
                replace(
                    row,
                    reconciled=False,
                    reconciliation_delta=None,
                    reconciliation_source=ReconSource.NODE_BELIEF.value,
                )
            )
            continue
        compare = found[1]
        out.append(
            replace(
                row,
                reconciled=compare.result is CompareResult.MATCH,
                reconciliation_delta=compare.venue_net_qty - compare.ledger_net_qty,
                reconciliation_source=ReconSource.VENUE_GET.value,
            )
        )
    return tuple(out)


def fills_never_position_compared(
    fills: Sequence[DurableFillRecord],
    snapshots: Sequence[StoredSnapshot],
    deadline_ns: DeadlineNs,
    *,
    now_ns: int,
) -> int:
    """Fills whose slug deadline has passed with no governing comparison (any is a FAIL)."""
    count = 0
    for slug, slug_fills in _fills_by_slug(fills).items():
        deadline = deadline_ns(slug)
        if deadline is None or now_ns < deadline:
            continue
        if governing_comparison(slug, snapshots, slug_fills, deadline_ns) is None:
            count += len(slug_fills)
    return count


@dataclass(frozen=True)
class DailyPositionLeg:
    outcome: VerdictOutcome
    position_mismatches_transient: int
    standing_mismatches: tuple[str, ...]
    fills_never_position_compared: int


def daily_position_leg(
    fills: Sequence[DurableFillRecord],
    snapshots: Sequence[StoredSnapshot],
    deadline_ns: DeadlineNs,
    *,
    now_ns: int,
) -> DailyPositionLeg:
    """PASS iff every compared slug's governing comparison is MATCH and no past-deadline fill was
    never compared. A MISMATCH that a later MATCH cleared is counted as transient."""
    standing: list[str] = []
    transient = 0
    pending = False
    for slug, slug_fills in sorted(_fills_by_slug(fills).items()):
        found = governing_comparison(slug, snapshots, slug_fills, deadline_ns)
        if found is None:
            deadline = deadline_ns(slug)
            pending = pending or deadline is None or now_ns < deadline
            continue
        if found[1].result is CompareResult.MISMATCH:
            standing.append(slug)
        elif any(
            r.base_slug == slug and r.result is CompareResult.MISMATCH
            for s in snapshots
            for r in s.rows
        ):
            transient += 1
    never = fills_never_position_compared(fills, snapshots, deadline_ns, now_ns=now_ns)
    if standing or never:
        outcome = VerdictOutcome.FAIL
    elif pending:
        outcome = VerdictOutcome.INCONCLUSIVE
    else:
        outcome = VerdictOutcome.PASS
    return DailyPositionLeg(outcome, transient, tuple(standing), never)


def streak_alert(
    statuses_newest_first: Sequence[str], status: str, *, threshold: int = INCONCLUSIVE_ALERT_DAYS
) -> bool:
    """Whether the newest ``threshold`` daily statuses are all ``status`` (unbroken)."""
    head = list(statuses_newest_first)[:threshold]
    return len(head) == threshold and all(s == status for s in head)


# -- settlement leg ----------------------------------------------------------------------------


@dataclass(frozen=True)
class SettlementEvidence:
    """The venue's own YES resolution for a base slug (None until it has published one)."""

    venue_yes_resolved: bool | None
    overdue: bool = False


@dataclass(frozen=True)
class SettlementLeg:
    outcome: VerdictOutcome
    rows: tuple[LabelRow, ...]
    mismatches: int
    pending: int
    alerts: tuple[ReconAlert, ...]


def reconcile_settlement(
    rows: Sequence[LabelRow], evidence: Mapping[str, SettlementEvidence]
) -> SettlementLeg:
    """Compare each entry label's outcome with the venue's YES resolution of its base slug."""
    out: list[LabelRow] = []
    alerts: list[ReconAlert] = []
    mismatches = pending = missing = 0
    for row in rows:
        seen = evidence.get(row.net_position_key)
        if row.role is not LabelRole.ENTRY:
            out.append(row)
            continue
        if row.settled_outcome is None or seen is None or seen.venue_yes_resolved is None:
            if row.settled_outcome is not None and seen is not None and seen.overdue:
                missing += 1
            else:
                pending += 1
            out.append(row)
            continue
        expected = row.settled_outcome if row.leg == "yes" else not row.settled_outcome
        if seen.venue_yes_resolved == expected:
            out.append(row)
            continue
        mismatches += 1
        alerts.append(
            ReconAlert("CRITICAL", "settlement_source_disagreement", row.net_position_key)
        )
        out.append(replace(row, reconciled=False))
    if mismatches or missing:
        outcome = VerdictOutcome.FAIL
    elif pending:
        outcome = VerdictOutcome.INCONCLUSIVE
    else:
        outcome = VerdictOutcome.PASS
    return SettlementLeg(outcome, tuple(out), mismatches, pending, tuple(alerts))


# -- cash leg -----------------------------------------------------------------------------------


class CashSourceOverlap(Exception):
    """A fill key is in both a legacy cash source and a C2 cash record."""


@dataclass(frozen=True)
class CashRecord:
    """Shaped like ``portfolio_roi_report.ResidualSettlement`` plus its kind and fill key."""

    kind: str
    fill_key: str
    trial_id: str
    climate_day: str
    payout: Decimal
    dated_at_ns: int
    settlement_basis: str
    realised_pnl: Decimal


@dataclass(frozen=True)
class CashRecords:
    records: tuple[CashRecord, ...]
    unknown_netting_slugs: tuple[str, ...]


def _lot_fraction(fills: Sequence[DurableFillRecord], instrument_id: str) -> Decimal:
    bought = sum(
        (
            f.cumulative_qty
            for f in fills
            if f.instrument_id == instrument_id and f.order_side == "BUY"
        ),
        Decimal(0),
    )
    sold = sum(
        (
            f.cumulative_qty
            for f in fills
            if f.instrument_id == instrument_id and f.order_side != "BUY"
        ),
        Decimal(0),
    )
    if bought == 0:
        return Decimal(0)
    return max(Decimal(0), (bought - sold) / bought)


def cash_records(
    rows: Sequence[LabelRow],
    fills: Sequence[DurableFillRecord],
    *,
    legacy_fill_keys: Collection[str],
    deadline_ns: DeadlineNs,
    netting_ns: Callable[[str], int | None],
) -> CashRecords:
    """C2 cash records: payouts, exit proceeds net of fee and YES/NO netting offsets.

    Rows of the legacy scorer are skipped (their cash stays in the legacy sources); any other row
    whose fill key is in a legacy source raises ``CashSourceOverlap``. A payout is
    ``realized_pnl + cost + fee`` (so a perturbed ``realized_pnl`` reaches the cash leg).
    """
    by_coid = {f.client_order_id: f for f in fills}
    records: list[CashRecord] = []
    pairs: dict[str, dict[str, list[tuple[LabelRow, DurableFillRecord]]]] = {}
    for row in rows:
        fill = by_coid.get(row.client_order_id)
        if fill is None:
            continue
        if fill.venue_order_id in legacy_fill_keys:
            if row.scorer_id == LEGACY_SCORER_ID:
                continue
            raise CashSourceOverlap("a fill key is in both a legacy source and a C2 cash record")
        if row.role is LabelRole.EXIT:
            records.append(_exit_record(row, fill))
        elif row.settled_outcome is not None and row.realized_pnl is not None:
            pairs.setdefault(row.net_position_key, {"yes": [], "no": []})[row.leg].append(
                (row, fill)
            )
    unknown: list[str] = []
    for slug, sides in sorted(pairs.items()):
        records.extend(_entry_records(slug, sides, fills, deadline_ns, netting_ns, unknown))
    return CashRecords(tuple(records), tuple(unknown))


def _exit_record(row: LabelRow, fill: DurableFillRecord) -> CashRecord:
    proceeds = fill.cumulative_cost - fill.cumulative_fee
    return CashRecord(
        "exit_proceeds",
        fill.venue_order_id,
        row.trial_id,
        row.climate_day,
        proceeds,
        fill.ts_event,
        "nws_final",
        proceeds,
    )


def _entry_records(
    slug: str,
    sides: Mapping[str, Sequence[tuple[LabelRow, DurableFillRecord]]],
    fills: Sequence[DurableFillRecord],
    deadline_ns: DeadlineNs,
    netting_ns: Callable[[str], int | None],
    unknown: list[str],
) -> list[CashRecord]:
    q_yes = sum((f.cumulative_qty for _, f in sides["yes"]), Decimal(0))
    q_no = sum((f.cumulative_qty for _, f in sides["no"]), Decimal(0))
    paired = min(q_yes, q_no)
    out: list[CashRecord] = []
    first_row = (sides["yes"] or sides["no"])[0][0]
    if paired > 0:
        when = netting_ns(slug)
        if when is None:
            unknown.append(slug)
        else:
            out.append(
                CashRecord(
                    "netting_offset",
                    first_row.client_order_id,
                    first_row.trial_id,
                    first_row.climate_day,
                    paired * _ONE,
                    when,
                    first_row.settlement_basis or "nws_final",
                    Decimal(0),
                )
            )
    deadline = deadline_ns(slug)
    for leg, q_side in (("yes", q_yes), ("no", q_no)):
        keep = Decimal(0) if q_side == 0 else (q_side - paired) / q_side
        for row, fill in sides[leg]:
            fraction = keep * _lot_fraction(fills, row.instrument_id)
            if fraction == 0 or deadline is None or row.realized_pnl is None:
                continue
            payout = (row.realized_pnl + fill.cumulative_cost + fill.cumulative_fee) * fraction
            out.append(
                CashRecord(
                    "settlement_payout",
                    fill.venue_order_id,
                    row.trial_id,
                    row.climate_day,
                    payout,
                    deadline,
                    row.settlement_basis or "nws_final",
                    row.realized_pnl,
                )
            )
    return out


def cash_leg_outcome(
    *,
    settled_cumulative_passes_net: bool,
    n_balance_unknown_days: int,
    external_flow_evidence_status: str,
    unknown_netting_slugs: Collection[str] = (),
) -> VerdictOutcome:
    """PASS on the net cumulative flag; an unknown balance, unverified external flows or an
    unobservable netting event is INCONCLUSIVE, never coerced to zero or FAIL."""
    if (
        n_balance_unknown_days > 0
        or external_flow_evidence_status != "OK"
        or len(unknown_netting_slugs) > 0
    ):
        return VerdictOutcome.INCONCLUSIVE
    return VerdictOutcome.PASS if settled_cumulative_passes_net else VerdictOutcome.FAIL
